"""FastAPI app: REST API, WebSocket live updates, simulator control, static frontend."""
from __future__ import annotations

import asyncio
import os
import random
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional, Union

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import llm, notifier, simulator, statusdraft
from .correlation import Engine
from .db import Database
from .seed import seed

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = os.getenv("OCC_DB", str(ROOT / "data" / "occ.db"))
HOLD = float(os.getenv("OCC_RESOLVE_HOLD", "15"))
WINDOW = float(os.getenv("OCC_WINDOW", "120"))
KEEP_STATE = os.getenv("OCC_KEEP_STATE", "0") == "1"
FRONTEND_DIST = ROOT.parent / "frontend" / "dist"


class Live:
    """Process-wide state shared by the endpoints and the background loops."""

    def __init__(self):
        self.db: Database | None = None
        self.engine: Engine | None = None
        self.clients: set[WebSocket] = set()
        self.feed_all: deque = deque(maxlen=300)
        self.feed_new: list[dict] = []
        self.notifs_new: list[dict] = []
        self.dirty = False
        self.tasks: set[asyncio.Task] = set()


live = Live()


# ------------------------------------------------------------------ processing
def spawn(coro) -> asyncio.Task:
    t = asyncio.create_task(coro)
    live.tasks.add(t)
    t.add_done_callback(live.tasks.discard)
    return t


def process(alert: dict) -> dict:
    """Run one alert through the engine and queue everything the UI needs to hear about."""
    eng = live.engine
    res = eng.ingest(alert)
    node = eng.topo.nodes[res["node_id"]]
    item = {
        "ts": res["ts"], "node_id": res["node_id"], "node_name": node["name"], "type": res["type"],
        "message": alert.get("message") or res["type"].replace("_", " ").title(),
        "result": res["result"], "incident_id": res.get("incident_id"),
    }
    live.feed_all.append(item)
    live.feed_new.append(item)
    live.dirty = True
    handle_outbox()
    return res


def safe_process(alert: dict) -> None:
    try:
        process(alert)
    except Exception as e:  # keep a scenario running even if one event is bad
        print("alert rejected:", e)


def handle_outbox() -> None:
    for kind, payload in live.engine.drain_outbox():
        if kind == "notification":
            live.notifs_new.append(payload)
            if notifier.email_configured() and payload["level"] in ("major", "critical", "info"):
                asyncio.get_running_loop().run_in_executor(
                    None, notifier.send_email, f"[OCC] {payload['title']}", f"{payload['title']}\n\n{payload['body']}"
                )
        elif kind == "ai_draft":
            spawn(ai_draft(payload["incident_id"]))


async def ai_draft(inc_id: int) -> bool:
    if not llm.llm_configured():
        return False
    eng = live.engine
    inc, root, areas, dominant = eng.context(inc_id)
    if not inc or inc["status_update_source"] == "edited":
        return False
    system, prompt = statusdraft.ai_prompt(inc, root, areas, dominant)
    text = await asyncio.to_thread(llm.llm_complete, system, prompt)
    if not text:
        return False
    eng.set_status_update(inc_id, text, "ai")
    live.dirty = True
    return True


def snapshot() -> dict:
    eng = live.engine
    return {
        "statuses": eng.statuses(),
        "incidents": eng.list_incidents(),
        "metrics": eng.metrics(),
    }


async def broadcaster() -> None:
    while True:
        await asyncio.sleep(0.25)
        if not (live.dirty or live.feed_new or live.notifs_new):
            continue
        payload = {"type": "tick", **snapshot(), "feed": live.feed_new, "notifications": live.notifs_new}
        live.feed_new, live.notifs_new, live.dirty = [], [], False
        for ws in list(live.clients):
            try:
                await ws.send_json(payload)
            except Exception:
                live.clients.discard(ws)


async def ticker() -> None:
    while True:
        await asyncio.sleep(1.0)
        try:
            if live.engine.tick():
                live.dirty = True
            handle_outbox()  # also sends notifications that finished settling
        except Exception as e:
            print("tick error:", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    live.db = Database(DB_PATH)
    seed(live.db)
    live.engine = Engine(live.db, window=WINDOW, hold=HOLD, settle=float(os.getenv("OCC_NOTIFY_SETTLE", "3")))
    if not KEEP_STATE:
        live.engine.reset()
    bg = [asyncio.create_task(broadcaster()), asyncio.create_task(ticker())]
    yield
    for t in bg + list(live.tasks):
        t.cancel()


app = FastAPI(title="Network Outage Command Center", version="1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ---------------------------------------------------------------------- models
class AlertIn(BaseModel):
    node_id: str
    type: str
    severity: Optional[str] = None
    message: Optional[str] = None
    event_id: Optional[str] = None
    ts: Optional[float] = None


class SimIn(BaseModel):
    scenario: str
    target: Optional[str] = None
    speed: float = 1.0
    noise: bool = True


class RestoreIn(BaseModel):
    incident_id: Optional[int] = None
    node_id: Optional[str] = None


class StatusIn(BaseModel):
    status: str
    note: str = ""
    author: str = "engineer"


class NoteIn(BaseModel):
    message: str
    author: str = "engineer"


class UpdateTextIn(BaseModel):
    text: str


class RegenIn(BaseModel):
    mode: str = "ai"  # ai | template


# ------------------------------------------------------------------------- API
@app.get("/api/health")
async def health():
    return {"ok": True}


@app.get("/api/config")
async def config():
    return {
        "llm_configured": llm.llm_configured(),
        "email_configured": notifier.email_configured(),
        "resolve_hold_seconds": HOLD,
        "correlation_window_seconds": WINDOW,
        "scenarios": simulator.SCENARIOS,
    }


@app.get("/api/topology")
async def topology():
    eng = live.engine
    per_node = {nid: sum(c["counts"].values()) for nid, c in eng.cust.items()}
    nodes = []
    for n in eng.topo.nodes.values():
        nodes.append({**{k: n[k] for k in ("id", "name", "type", "parent_id", "backup_parent_id", "lat", "lng", "area")},
                      "status": eng.status[n["id"]], "customers": per_node.get(n["id"], 0)})
    return {"nodes": nodes}


@app.get("/api/incidents")
async def incidents(status: Optional[str] = None):
    return live.engine.list_incidents(status)


@app.get("/api/incidents/{inc_id}")
async def incident(inc_id: int):
    d = live.engine.incident_detail(inc_id)
    if not d:
        raise HTTPException(404, "incident not found")
    return d


@app.post("/api/incidents/{inc_id}/status")
async def set_status(inc_id: int, body: StatusIn):
    try:
        live.engine.set_status(inc_id, body.status, body.note, body.author)
    except LookupError:
        raise HTTPException(404, "incident not found")
    except ValueError as e:
        raise HTTPException(409, str(e))
    handle_outbox()
    live.dirty = True
    return live.engine.incident_detail(inc_id)


@app.post("/api/incidents/{inc_id}/notes")
async def add_note(inc_id: int, body: NoteIn):
    try:
        live.engine.add_note(inc_id, body.message, body.author)
    except LookupError:
        raise HTTPException(404, "incident not found")
    live.dirty = True
    return live.engine.incident_detail(inc_id)


@app.put("/api/incidents/{inc_id}/status-update")
async def edit_update(inc_id: int, body: UpdateTextIn):
    if not live.engine.incident_detail(inc_id):
        raise HTTPException(404, "incident not found")
    live.engine.set_status_update(inc_id, body.text, "edited")
    live.dirty = True
    return live.engine.incident_detail(inc_id)


@app.post("/api/incidents/{inc_id}/status-update")
async def regenerate_update(inc_id: int, body: RegenIn):
    if not live.engine.incident_detail(inc_id):
        raise HTTPException(404, "incident not found")
    if body.mode == "template":
        live.engine.refresh_text(inc_id, "template")
    else:
        if not llm.llm_configured():
            raise HTTPException(400, "No LLM API key configured (set ANTHROPIC_API_KEY or OPENAI_API_KEY); template update kept")
        live.engine.db.execute("UPDATE incidents SET status_update_source='template' WHERE id=?", (inc_id,))
        ok = await ai_draft(inc_id)
        if not ok:
            raise HTTPException(502, "LLM call failed; template update kept")
    live.dirty = True
    return live.engine.incident_detail(inc_id)


@app.post("/api/alerts")
async def ingest(body: Union[AlertIn, list[AlertIn]]):
    """Webhook for monitoring tools. Accepts one alert or a list."""
    items = body if isinstance(body, list) else [body]
    out = []
    for it in items:
        try:
            out.append(process(it.model_dump(exclude_none=True)))
        except ValueError as e:
            raise HTTPException(422, str(e))
    return out if isinstance(body, list) else out[0]


@app.get("/api/alerts")
async def recent_alerts(limit: int = 100):
    return list(live.feed_all)[-limit:]


@app.post("/api/simulate")
async def simulate(body: SimIn):
    try:
        sc = simulator.build(live.engine.topo, body.scenario, body.target, random.Random(), noise=body.noise)
    except ValueError as e:
        raise HTTPException(422, str(e))
    speed = max(0.1, min(body.speed, 50.0))
    spawn(simulator.play(safe_process, sc.events, speed))
    return {"scenario": sc.name, "target": sc.target, "description": sc.description, "events": len(sc.events),
            "duration_seconds": round(sc.duration / speed, 1), "expected_root": sc.truth.get("root")}


@app.post("/api/restore")
async def restore(body: RestoreIn):
    eng = live.engine
    if body.incident_id is not None:
        inc = eng.incident_detail(body.incident_id)
        if not inc:
            raise HTTPException(404, "incident not found")
        root = inc["root_node_id"]
    elif body.node_id:
        if body.node_id not in eng.topo.nodes:
            raise HTTPException(404, "node not found")
        root = body.node_id
    else:
        raise HTTPException(422, "give incident_id or node_id")
    sub = eng.topo.subtree_set(root)
    nodes = sorted({r["node_id"] for r in eng.db.query("SELECT node_id FROM alerts WHERE state='open'") if r["node_id"] in sub})
    if not nodes:
        return {"restoring": 0}
    events = simulator.restore_events(eng.topo, nodes, random.Random())
    spawn(simulator.play(safe_process, events, 1.0))
    return {"restoring": len(nodes)}


@app.post("/api/reset")
async def reset():
    for t in list(live.tasks):
        t.cancel()
    live.engine.reset()
    live.feed_all.clear()
    live.feed_new.clear()
    live.notifs_new.clear()
    live.dirty = True
    return {"ok": True}


@app.get("/api/metrics")
async def metrics():
    return live.engine.metrics()


@app.get("/api/notifications")
async def notifications(limit: int = 50):
    return live.engine.db.query("SELECT * FROM notifications ORDER BY id DESC LIMIT ?", (limit,))


@app.post("/api/notifications/read")
async def notifications_read():
    live.engine.db.execute("UPDATE notifications SET is_read=1")
    return {"ok": True}


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    live.clients.add(websocket)
    try:
        notifs = live.engine.db.query("SELECT * FROM notifications ORDER BY id DESC LIMIT 30")
        await websocket.send_json({"type": "snapshot", **snapshot(), "feed": list(live.feed_all)[-80:],
                                   "notifications": notifs})
        while True:
            await websocket.receive_text()  # keep-alive; clients send nothing important
    except WebSocketDisconnect:
        pass
    finally:
        live.clients.discard(websocket)


# ------------------------------------------------------- built frontend (optional)
if FRONTEND_DIST.exists():
    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        if path.startswith(("api/", "ws")):
            raise HTTPException(404)
        f = (FRONTEND_DIST / path).resolve()
        if path and f.is_file() and FRONTEND_DIST.resolve() in f.parents:
            return FileResponse(f)
        return FileResponse(FRONTEND_DIST / "index.html")
