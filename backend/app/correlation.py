"""Topology-aware alert correlation.

Raw alerts go in; a handful of incidents come out.

Rules, in order, for every incoming fault alert:
 1. Exact redelivery (same event_id) or same node+type already open -> deduplicated, only counted.
 2. If an open incident is rooted at the alert's node or one of its ancestors, the alert is a
    symptom of that incident -> attached.
 3. If the alert's node is an ancestor of existing incidents' roots, the root cause is further
    upstream than we thought -> those incidents are merged and the root is promoted.
 4. Otherwise a new incident is opened.
 5. Common-ancestor inference: if at least ceil(ratio * n) siblings under one parent are alerting
    within the correlation window (and at least one of them is down) the parent is the probable
    root cause even though it raised no alert itself -> merge into an "inferred" incident rooted
    at the parent. Repeats upward.
Recovery is two-stage: all alerts cleared -> "mitigated"; after a quiet hold period -> "resolved".
A fault reappearing at a node that cleared recently counts as a flap; 3+ flaps -> "flapping" incident.
"""
from __future__ import annotations

import math
import time
import uuid

from . import statusdraft
from .db import Database
from .topology import Topology

DOWN_TYPES = {"LINK_DOWN", "POWER_FAILURE", "NODE_UNREACHABLE"}
DEGRADE_TYPES = {"HIGH_LATENCY", "PACKET_LOSS"}
FAULT_TYPES = DOWN_TYPES | DEGRADE_TYPES
CLEAR_TYPES = {"CLEARED", "RECOVERED", "UP"}

PRIORITY_WEIGHT = {"home": 1.0, "business": 3.0, "enterprise": 8.0}
DEGRADED_FACTOR = 0.3
RANK = {"": 0, "minor": 1, "major": 2, "critical": 3}


class Engine:
    def __init__(
        self,
        db: Database,
        window: float = 120.0,
        hold: float = 15.0,
        flap_threshold: int = 3,
        infer_ratio: float = 0.6,
        critical_score: float = 600.0,
        major_score: float = 150.0,
        settle: float = 3.0,
        max_wait: float = 12.0,
    ):
        self.db = db
        self.window = window
        self.hold = hold
        self.settle = settle
        self.max_wait = max_wait
        self.flap_threshold = flap_threshold
        self.infer_ratio = infer_ratio
        self.critical_score = critical_score
        self.major_score = major_score
        self.outbox: list[tuple[str, dict]] = []  # ("notification"|"ai_draft", payload) for the API layer
        self.load_topology()

    # ------------------------------------------------------------------ setup
    def load_topology(self) -> None:
        nodes = self.db.query("SELECT * FROM nodes")
        self.topo = Topology(nodes)
        self.cust: dict[str, dict] = {}
        for r in self.db.query(
            "SELECT node_id, priority, COUNT(*) AS n, MIN(area) AS area FROM customers GROUP BY node_id, priority"
        ):
            e = self.cust.setdefault(r["node_id"], {"counts": {}, "area": r["area"]})
            e["counts"][r["priority"]] = r["n"]
        self.status: dict[str, str] = {n["id"]: n["status"] for n in nodes}

    def reset(self) -> None:
        with self.db.transaction():
            for t in ("alerts", "incidents", "incident_events", "notifications"):
                self.db.execute(f"DELETE FROM {t}")
            self.db.execute("UPDATE nodes SET status='up'")
        self.status = {n: "up" for n in self.topo.nodes}
        self.outbox.clear()

    # ---------------------------------------------------------------- helpers
    def _inc(self, inc_id: int) -> dict:
        return self.db.one("SELECT * FROM incidents WHERE id=?", (inc_id,))

    def _name(self, node_id: str) -> str:
        return self.topo.nodes[node_id]["name"]

    def _event(self, inc_id: int, ts: float, message: str, author: str = "system") -> None:
        self.db.execute(
            "INSERT INTO incident_events(incident_id, ts, message, author) VALUES (?,?,?,?)",
            (inc_id, ts, message, author),
        )

    def _open_incidents(self) -> list[dict]:
        return self.db.query("SELECT * FROM incidents WHERE status!='resolved' AND merged_into IS NULL")

    def _title(self, inc: dict) -> str:
        name = self._name(inc["root_node_id"])
        if inc["kind"] == "flapping":
            return f"Flapping link at {name} ({inc['flap_count']} flaps)"
        if inc["inferred"]:
            return f"Suspected upstream failure at {name}"
        if inc["kind"] == "degradation":
            return f"Degraded performance at {name}"
        return f"Outage at {name}"

    def _retitle(self, inc_id: int) -> None:
        inc = self._inc(inc_id)
        self.db.execute("UPDATE incidents SET title=? WHERE id=?", (self._title(inc), inc_id))

    # ----------------------------------------------------------------- ingest
    def ingest(self, alert: dict) -> dict:
        a = self._normalize(alert)
        with self.db.transaction():
            res = self._ingest(a)
            self._recompute(a["ts"])
        res["node_id"] = a["node_id"]
        res["type"] = a["type"]
        res["ts"] = a["ts"]
        return res

    def _normalize(self, alert: dict) -> dict:
        a = dict(alert)
        if a.get("node_id") not in self.topo.nodes:
            raise ValueError(f"unknown node_id: {a.get('node_id')!r}")
        a["type"] = str(a.get("type", "")).upper()
        if a["type"] not in FAULT_TYPES | CLEAR_TYPES:
            raise ValueError(f"unknown alert type: {a['type']!r}")
        a["ts"] = float(a["ts"]) if a.get("ts") is not None else time.time()
        a["event_id"] = a.get("event_id") or uuid.uuid4().hex
        a.setdefault("severity", "critical" if a["type"] in DOWN_TYPES else "warning")
        a.setdefault("message", a["type"].replace("_", " ").title())
        return a

    def _ingest(self, a: dict) -> dict:
        if a["type"] in CLEAR_TYPES:
            return self._clear(a)

        existing = self.db.one("SELECT * FROM alerts WHERE event_id=?", (a["event_id"],))
        if existing:
            self._bump(existing, a["ts"])
            return {"result": "duplicate", "incident_id": existing["incident_id"], "alert_id": existing["id"]}
        same = self.db.one(
            "SELECT * FROM alerts WHERE node_id=? AND type=? AND state='open'", (a["node_id"], a["type"])
        )
        if same:
            self._bump(same, a["ts"])
            return {"result": "deduplicated", "incident_id": same["incident_id"], "alert_id": same["id"]}

        flapped = self.db.one(
            "SELECT 1 AS x FROM alerts WHERE node_id=? AND type=? AND state='cleared' AND cleared_ts>=?",
            (a["node_id"], a["type"], a["ts"] - self.window),
        )
        cur = self.db.execute(
            "INSERT INTO alerts(event_id,node_id,type,severity,message,ts,last_ts) VALUES (?,?,?,?,?,?,?)",
            (a["event_id"], a["node_id"], a["type"], a["severity"], a["message"], a["ts"], a["ts"]),
        )
        alert_id = cur.lastrowid
        inc_id = self._assign(alert_id, a, bool(flapped))
        return {"result": "new", "incident_id": inc_id, "alert_id": alert_id}

    def _bump(self, row: dict, ts: float) -> None:
        self.db.execute("UPDATE alerts SET count=count+1, last_ts=MAX(last_ts, ?) WHERE id=?", (ts, row["id"]))
        if row["incident_id"]:
            self.db.execute(
                "UPDATE incidents SET raw_alert_count=raw_alert_count+1, last_alert_ts=MAX(last_alert_ts, ?) WHERE id=?",
                (ts, row["incident_id"]),
            )

    # ------------------------------------------------------------- assignment
    def _assign(self, alert_id: int, a: dict, flapped: bool) -> int:
        node, ts, typ = a["node_id"], a["ts"], a["type"]
        incs = self._open_incidents()

        target = None
        for inc in incs:
            if self.topo.is_ancestor_or_self(inc["root_node_id"], node):
                if target is None or self.topo.depth[inc["root_node_id"]] > self.topo.depth[target["root_node_id"]]:
                    target = inc

        if target:
            inc_id = target["id"]
        else:
            contained = [i for i in incs if self.topo.is_ancestor(node, i["root_node_id"])]
            if contained:
                inc_id = self._merge(
                    contained, node, ts, inferred=False,
                    reason=f"Alert at {self._name(node)} is upstream of {len(contained)} open incident(s)",
                )
            else:
                inc_id = self._create(node, typ, ts)

        self.db.execute("UPDATE alerts SET incident_id=? WHERE id=?", (inc_id, alert_id))
        self._touch(inc_id, a, flapped)
        return self._infer(inc_id, ts)

    def _create(self, node: str, typ: str, ts: float) -> int:
        kind = "outage" if typ in DOWN_TYPES else "degradation"
        cur = self.db.execute(
            "INSERT INTO incidents(root_node_id, kind, started_ts, last_alert_ts, title) VALUES (?,?,?,?,?)",
            (node, kind, ts, ts, ""),
        )
        inc_id = cur.lastrowid
        self._retitle(inc_id)
        self._event(inc_id, ts, f"Incident opened by {typ} alert at {self._name(node)}")
        return inc_id

    def _touch(self, inc_id: int, a: dict, flapped: bool) -> None:
        node, ts, typ = a["node_id"], a["ts"], a["type"]
        inc = self._inc(inc_id)
        self.db.execute(
            "UPDATE incidents SET raw_alert_count=raw_alert_count+1, last_alert_ts=MAX(last_alert_ts, ?) WHERE id=?",
            (ts, inc_id),
        )
        if inc["status"] == "mitigated":
            self.db.execute("UPDATE incidents SET status='investigating', mitigated_ts=NULL WHERE id=?", (inc_id,))
            self._event(inc_id, ts, f"Reopened: new {typ} alert at {self._name(node)} during stability hold")
        if inc["inferred"] and inc["root_node_id"] == node and typ in DOWN_TYPES:
            self.db.execute("UPDATE incidents SET inferred=0 WHERE id=?", (inc_id,))
            self._event(inc_id, ts, f"Root cause confirmed: direct {typ} alert from {self._name(node)}")
        if typ in DOWN_TYPES and inc["kind"] == "degradation":
            self.db.execute("UPDATE incidents SET kind='outage' WHERE id=?", (inc_id,))
            self._event(inc_id, ts, "Escalated from degradation to outage")
        if flapped:
            self.db.execute("UPDATE incidents SET flap_count=flap_count+1 WHERE id=?", (inc_id,))
            cur = self._inc(inc_id)
            if cur["flap_count"] >= self.flap_threshold and cur["kind"] != "flapping":
                self.db.execute("UPDATE incidents SET kind='flapping' WHERE id=?", (inc_id,))
                self._event(inc_id, ts, f"Classified as flapping after {cur['flap_count']} recoveries and relapses")
        self._retitle(inc_id)

    def _merge(self, incs: list[dict], new_root: str, ts: float, inferred: bool, reason: str) -> int:
        incs = sorted(incs, key=lambda i: i["id"])
        target, others = incs[0], incs[1:]
        kinds = {i["kind"] for i in incs}
        kind = "outage" if "outage" in kinds else ("flapping" if "flapping" in kinds else "degradation")
        raw = sum(i["raw_alert_count"] for i in incs)
        flaps = sum(i["flap_count"] for i in incs)
        started = min(i["started_ts"] for i in incs)
        notified = max((i["notified_level"] for i in incs), key=lambda l: RANK[l])
        statuses = {i["status"] for i in incs}
        status = "investigating" if "investigating" in statuses else "mitigated"
        for o in others:
            self.db.execute("UPDATE alerts SET incident_id=? WHERE incident_id=?", (target["id"], o["id"]))
            # the merged incident's own "Incident opened by ..." line becomes an earlier alert of the survivor
            self.db.execute(
                "UPDATE incident_events SET message='Earlier alert (merged from incident #' || ? || '): ' || substr(message, 20)"
                " WHERE incident_id=? AND message LIKE 'Incident opened by %'",
                (o["id"], o["id"]),
            )
            self.db.execute("UPDATE incident_events SET incident_id=? WHERE incident_id=?", (target["id"], o["id"]))
            self.db.execute(
                "UPDATE incidents SET merged_into=?, status='resolved', resolved_ts=? WHERE id=?",
                (target["id"], ts, o["id"]),
            )
        self.db.execute(
            "UPDATE incidents SET root_node_id=?, inferred=?, kind=?, raw_alert_count=?, flap_count=?, started_ts=?,"
            " notified_level=?, status=?, mitigated_ts=CASE WHEN ?='investigating' THEN NULL ELSE mitigated_ts END"
            " WHERE id=?",
            (new_root, int(inferred), kind, raw, flaps, started, notified, status, status, target["id"]),
        )
        merged_ids = ", ".join(f"#{o['id']}" for o in others)
        msg = f"Root cause set to {self._name(new_root)}. {reason}"
        if others:
            msg += f"; merged incident(s) {merged_ids}"
        self._event(target["id"], ts, msg)
        self._retitle(target["id"])
        return target["id"]

    def _infer(self, inc_id: int, ts: float) -> int:
        """Promote the root to a parent when most of its children are alerting."""
        for _ in range(8):
            inc = self._inc(inc_id)
            parent = self.topo.parent(inc["root_node_id"])
            if parent is None:
                return inc_id
            sibs = self.topo.children[parent]
            need = max(2, math.ceil(self.infer_ratio * len(sibs)))
            rows = self.db.query("SELECT node_id, type FROM alerts WHERE state='open' AND last_ts>=?", (ts - self.window,))
            hits, hit_nodes = [], set()
            for s in sibs:
                sub = self.topo.subtree_set(s)
                if any(r["node_id"] in sub for r in rows):
                    hits.append(s)
                    hit_nodes |= sub
            has_down = any(r["type"] in DOWN_TYPES and r["node_id"] in hit_nodes for r in rows)
            if len(hits) < need or not has_down:
                return inc_id
            sub = self.topo.subtree_set(parent)
            in_sub = [i for i in self._open_incidents() if i["root_node_id"] in sub]
            inc_id = self._merge(
                in_sub, parent, ts, inferred=True,
                reason=f"{len(hits)} of {len(sibs)} children alerting within {int(self.window)}s while "
                       f"{self._name(parent)} itself raised no alert (inferred)",
            )
        return inc_id

    # ------------------------------------------------------------------ clear
    def _clear(self, a: dict) -> dict:
        node, ts = a["node_id"], a["ts"]
        rows = self.db.query("SELECT * FROM alerts WHERE node_id=? AND state='open'", (node,))
        if not rows:
            return {"result": "ignored", "incident_id": None}
        self.db.execute(
            "UPDATE alerts SET state='cleared', cleared_ts=? WHERE node_id=? AND state='open'", (ts, node)
        )
        inc_ids = sorted({r["incident_id"] for r in rows if r["incident_id"]})
        for inc_id in inc_ids:
            inc = self._inc(inc_id)
            if inc["root_node_id"] == node:
                self._event(inc_id, ts, f"Root node recovered: {self._name(node)}")
            remaining = self.db.scalar(
                "SELECT COUNT(*) FROM alerts WHERE incident_id=? AND state='open'", (inc_id,), default=0
            )
            if remaining == 0 and inc["status"] == "investigating":
                self.db.execute(
                    "UPDATE incidents SET status='mitigated', mitigated_ts=? WHERE id=?", (ts, inc_id)
                )
                self._event(
                    inc_id, ts,
                    f"All alerts cleared. Monitoring for stability; auto-resolves after {int(self.hold)}s without new alerts",
                )
        return {"result": "cleared", "incident_id": inc_ids[0] if inc_ids else None, "alerts_cleared": len(rows)}

    # --------------------------------------------------------- tick / resolve
    def tick(self, now: float | None = None, hold: float | None = None) -> list[int]:
        """Resolve mitigated incidents that stayed quiet for the hold period. Returns resolved ids."""
        now = time.time() if now is None else now
        hold = self.hold if hold is None else hold
        resolved = []
        with self.db.transaction():
            for inc in self.db.query(
                "SELECT * FROM incidents WHERE status='mitigated' AND merged_into IS NULL AND mitigated_ts<=?",
                (now - hold,),
            ):
                self._resolve(inc["id"], now, "Stable for the hold period; incident resolved automatically")
                resolved.append(inc["id"])
            if resolved:
                self._recompute(now)
            self._flush_notifications(now)
        return resolved

    def _resolve(self, inc_id: int, ts: float, message: str, author: str = "system") -> None:
        self.db.execute(
            "UPDATE incidents SET status='resolved', resolved_ts=?, status_update_source=CASE "
            "WHEN status_update_source='edited' THEN 'edited' ELSE 'template' END WHERE id=?",
            (ts, inc_id),
        )
        self._event(inc_id, ts, message, author)
        inc = self._inc(inc_id)
        if inc["notified_level"]:
            self._notify(
                inc, "info", f"Resolved: {inc['title']}",
                f"Service restored after {statusdraft.fmt_duration(ts - inc['started_ts'])}. "
                f"Peak impact {inc['peak_offline']:,} offline, {inc['peak_degraded']:,} degraded.",
                ts,
            )
        self._refresh_text(inc_id, ts)
        self.outbox.append(("ai_draft", {"incident_id": inc_id}))

    # ---------------------------------------------------------- manual actions
    def set_status(self, inc_id: int, status: str, note: str = "", author: str = "engineer", now: float | None = None) -> dict:
        now = time.time() if now is None else now
        if status not in ("investigating", "mitigated", "resolved"):
            raise ValueError("status must be investigating, mitigated or resolved")
        with self.db.transaction():
            inc = self._inc(inc_id)
            if not inc or inc["merged_into"]:
                raise LookupError("incident not found")
            open_alerts = self.db.scalar(
                "SELECT COUNT(*) FROM alerts WHERE incident_id=? AND state='open'", (inc_id,), default=0
            )
            if status in ("mitigated", "resolved") and open_alerts:
                raise ValueError(f"{open_alerts} alert(s) still open; restore the affected nodes first")
            if status == "resolved":
                self._resolve(inc_id, now, note or "Marked resolved by engineer", author)
            else:
                self.db.execute(
                    "UPDATE incidents SET status=?, mitigated_ts=? WHERE id=?",
                    (status, now if status == "mitigated" else None, inc_id),
                )
                self._event(inc_id, now, note or f"Status set to {status}", author)
            self._recompute(now)
        return self._inc(inc_id)

    def add_note(self, inc_id: int, message: str, author: str = "engineer", now: float | None = None) -> None:
        if not self._inc(inc_id):
            raise LookupError("incident not found")
        self._event(inc_id, time.time() if now is None else now, message, author)

    def set_status_update(self, inc_id: int, text: str, source: str) -> None:
        self.db.execute(
            "UPDATE incidents SET status_update=?, status_update_source=? WHERE id=?", (text, source, inc_id)
        )

    # -------------------------------------------------------------- recompute
    def _impact(self, root: str, status: dict[str, str]):
        off = deg = biz = 0
        score = 0.0
        areas: set[str] = set()
        nodes = 0
        for nid in self.topo.subtree(root):
            st = status.get(nid, "up")
            if st == "up":
                continue
            nodes += 1
            c = self.cust.get(nid)
            if not c:
                continue
            for prio, n in c["counts"].items():
                w = PRIORITY_WEIGHT.get(prio, 1.0)
                if st == "down":
                    off += n
                    score += n * w
                else:
                    deg += n
                    score += n * w * DEGRADED_FACTOR
                if prio != "home":
                    biz += n
            areas.add(c["area"])
        return off, deg, biz, score, sorted(areas), nodes

    def impact_for(self, down: set[str], degraded: set[str], root: str) -> dict:
        """Ground-truth style impact for a hypothetical failure set (used by the evaluation)."""
        st = self.topo.effective_status(down, degraded)
        off, deg, biz, score, areas, nodes = self._impact(root, st)
        return {"offline": off, "degraded": deg, "business": biz, "score": score, "areas": areas, "nodes": nodes}

    def _label(self, peak_score: float, biz: int, peak_off: int) -> str:
        if peak_score >= self.critical_score:
            return "critical"
        if peak_score >= self.major_score or (biz > 0 and peak_off > 0):
            return "major"
        return "minor"

    def _recompute(self, ts: float) -> None:
        rows = self.db.query("SELECT node_id, type FROM alerts WHERE state='open'")
        down = {r["node_id"] for r in rows if r["type"] in DOWN_TYPES}
        degraded = {r["node_id"] for r in rows if r["type"] in DEGRADE_TYPES}
        incs = self._open_incidents()
        for i in incs:
            if i["inferred"] and i["status"] == "investigating":
                down.add(i["root_node_id"])
        status = self.topo.effective_status(down, degraded)
        changed = [(s, n) for n, s in status.items() if self.status.get(n) != s]
        if changed:
            self.db.executemany("UPDATE nodes SET status=? WHERE id=?", changed)
            self.status = status
        for inc in incs:
            self._update_incident(inc["id"], status, ts)

    def _update_incident(self, inc_id: int, status: dict[str, str], ts: float) -> None:
        inc = self._inc(inc_id)
        off, deg, biz, score, areas, _nodes = self._impact(inc["root_node_id"], status)
        peak_off = max(inc["peak_offline"], off)
        peak_deg = max(inc["peak_degraded"], deg)
        peak_score = max(inc["peak_score"], score)
        label = self._label(peak_score, biz, peak_off)
        self.db.execute(
            "UPDATE incidents SET customers_offline=?, customers_degraded=?, business_affected=?, severity_score=?,"
            " peak_offline=?, peak_degraded=?, peak_score=?, severity=?, areas=? WHERE id=?",
            (off, deg, biz, score, peak_off, peak_deg, peak_score, label, ", ".join(areas), inc_id),
        )
        self._refresh_text(inc_id, ts)

    def _flush_notifications(self, now: float) -> None:
        """Notify for major/critical incidents once correlation has settled.

        Alerts for one failure arrive over several seconds, and an early child incident can still be
        merged into a bigger one. Notifying immediately would send several 'major' messages for what
        turns out to be one outage, so we wait until the incident has been quiet for `settle` seconds
        (or has been open for `max_wait`, so a long alert storm still gets announced).
        """
        for inc in self._open_incidents():
            level = inc["severity"]
            if inc["status"] != "investigating" or RANK[level] < 2 or RANK[level] <= RANK[inc["notified_level"]]:
                continue
            quiet = now - inc["last_alert_ts"] >= self.settle
            old = now - inc["started_ts"] >= self.max_wait
            if not (quiet or old):
                continue
            self.db.execute("UPDATE incidents SET notified_level=? WHERE id=?", (level, inc["id"]))
            areas = [a for a in (inc["areas"] or "").split(", ") if a]
            body = f"{inc['customers_offline']:,} customers offline, {inc['customers_degraded']:,} degraded"
            if areas:
                body += " in " + ", ".join(areas[:3]) + (" and more" if len(areas) > 3 else "")
            self._notify(inc, level, f"{level.upper()}: {inc['title']}", body, now)
            self.outbox.append(("ai_draft", {"incident_id": inc["id"]}))

    def _refresh_text(self, inc_id: int, ts: float) -> None:
        inc = self._inc(inc_id)
        root = self.topo.nodes[inc["root_node_id"]]
        counts = {
            r["type"]: r["c"]
            for r in self.db.query(
                "SELECT type, SUM(count) AS c FROM alerts WHERE incident_id=? GROUP BY type", (inc_id,)
            )
        }
        root_types = [
            r["type"]
            for r in self.db.query(
                "SELECT type FROM alerts WHERE incident_id=? AND node_id=?", (inc_id, inc["root_node_id"])
            )
        ]
        dominant = statusdraft.dominant_type(counts, root_types)
        areas = [a for a in (inc["areas"] or "").split(", ") if a]
        if inc["status_update_source"] in (None, "", "template"):
            self.db.execute(
                "UPDATE incidents SET status_update=?, status_update_source='template' WHERE id=?",
                (statusdraft.template_update(inc, root, areas, dominant, ts), inc_id),
            )
        affected = sum(1 for n in self.topo.subtree(inc["root_node_id"]) if self.status.get(n, "up") != "up")
        self.db.execute(
            "UPDATE incidents SET technical_summary=? WHERE id=?",
            (statusdraft.technical_summary(inc, root, counts, affected), inc_id),
        )

    def refresh_text(self, inc_id: int, source: str = "template") -> None:
        """Public: regenerate the template draft (source='template') or leave it untouched."""
        with self.db.transaction():
            if source == "template":
                self.db.execute("UPDATE incidents SET status_update_source='template' WHERE id=?", (inc_id,))
            self._refresh_text(inc_id, time.time())

    def context(self, inc_id: int) -> tuple[dict, dict, list[str], str]:
        """(incident, root node, affected areas, dominant alert type) for text generation."""
        inc = self._inc(inc_id)
        root = self.topo.nodes[inc["root_node_id"]]
        counts = {
            r["type"]: r["c"]
            for r in self.db.query("SELECT type, SUM(count) AS c FROM alerts WHERE incident_id=? GROUP BY type", (inc_id,))
        }
        root_types = [
            r["type"]
            for r in self.db.query(
                "SELECT type FROM alerts WHERE incident_id=? AND node_id=?", (inc_id, inc["root_node_id"])
            )
        ]
        areas = [a for a in (inc["areas"] or "").split(", ") if a]
        return inc, root, areas, statusdraft.dominant_type(counts, root_types)

    def _notify(self, inc: dict, level: str, title: str, body: str, ts: float) -> None:
        cur = self.db.execute(
            "INSERT INTO notifications(ts, incident_id, level, title, body) VALUES (?,?,?,?,?)",
            (ts, inc["id"], level, title, body),
        )
        self.outbox.append((
            "notification",
            {"id": cur.lastrowid, "ts": ts, "incident_id": inc["id"], "level": level, "title": title, "body": body},
        ))

    # ---------------------------------------------------------------- queries
    def list_incidents(self, status: str | None = None) -> list[dict]:
        sql = "SELECT * FROM incidents WHERE merged_into IS NULL"
        params: tuple = ()
        if status == "active":
            sql += " AND status!='resolved'"
        elif status:
            sql += " AND status=?"
            params = (status,)
        sql += " ORDER BY (status='resolved'), CASE severity WHEN 'critical' THEN 0 WHEN 'major' THEN 1 ELSE 2 END, started_ts DESC"
        out = []
        for i in self.db.query(sql, params):
            i["root_name"] = self._name(i["root_node_id"])
            i["root_type"] = self.topo.nodes[i["root_node_id"]]["type"]
            i["areas"] = [a for a in (i["areas"] or "").split(", ") if a]
            out.append(i)
        return out

    def incident_detail(self, inc_id: int) -> dict | None:
        inc = self._inc(inc_id)
        if not inc or inc["merged_into"]:
            return None
        inc["root_name"] = self._name(inc["root_node_id"])
        inc["root_type"] = self.topo.nodes[inc["root_node_id"]]["type"]
        inc["areas"] = [a for a in (inc["areas"] or "").split(", ") if a]
        alerts = self.db.query(
            "SELECT id, node_id, type, severity, message, ts, count, state, cleared_ts FROM alerts "
            "WHERE incident_id=? ORDER BY ts, id LIMIT 600", (inc_id,),
        )
        for a in alerts:
            a["node_name"] = self._name(a["node_id"])
        events = self.db.query(
            "SELECT ts, message, author FROM incident_events WHERE incident_id=? ORDER BY ts, id", (inc_id,)
        )
        affected = [
            {"id": n, "name": self._name(n), "type": self.topo.nodes[n]["type"], "status": self.status[n]}
            for n in self.topo.subtree(inc["root_node_id"])
            if self.status.get(n, "up") != "up"
        ]
        counts = {}
        for a in alerts:
            counts[a["type"]] = counts.get(a["type"], 0) + a["count"]
        root_types = [a["type"] for a in alerts if a["node_id"] == inc["root_node_id"]]
        inc.update(alerts=alerts, events=events, affected_nodes=affected, alert_type_counts=counts,
                   runbook=statusdraft.runbook(counts, root_types))
        return inc

    def statuses(self) -> dict[str, str]:
        return dict(self.status)

    def metrics(self) -> dict:
        raw = self.db.scalar("SELECT COALESCE(SUM(count),0) FROM alerts", default=0)
        total = self.db.scalar("SELECT COUNT(*) FROM incidents WHERE merged_into IS NULL", default=0)
        active = self.db.scalar(
            "SELECT COUNT(*) FROM incidents WHERE merged_into IS NULL AND status!='resolved'", default=0
        )
        off = deg = 0
        for nid, st in self.status.items():
            c = self.cust.get(nid)
            if not c or st == "up":
                continue
            n = sum(c["counts"].values())
            if st == "down":
                off += n
            else:
                deg += n
        mttr = self.db.scalar(
            "SELECT AVG(resolved_ts - started_ts) FROM incidents WHERE merged_into IS NULL AND status='resolved'"
        )
        total_customers = sum(sum(c["counts"].values()) for c in self.cust.values())
        return {
            "raw_alerts": int(raw),
            "incidents_total": int(total),
            "incidents_active": int(active),
            "noise_reduction_pct": round((1 - total / raw) * 100, 1) if raw > 0 and total > 0 else 0.0,
            "customers_offline": off,
            "customers_degraded": deg,
            "customers_total": total_customers,
            "mttr_seconds": round(mttr, 1) if mttr is not None else None,
            "nodes_down": sum(1 for s in self.status.values() if s == "down"),
            "nodes_degraded": sum(1 for s in self.status.values() if s == "degraded"),
        }

    def drain_outbox(self) -> list[tuple[str, dict]]:
        items, self.outbox = self.outbox, []
        return items
