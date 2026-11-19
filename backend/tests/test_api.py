import os
import time

os.environ["OCC_DB"] = ":memory:"
os.environ["OCC_RESOLVE_HOLD"] = "1"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    with TestClient(app) as c:
        c.post("/api/reset")
        yield c


def wait_for(fn, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.1)
    return None


def test_topology_and_config(client):
    topo = client.get("/api/topology").json()["nodes"]
    assert len(topo) == 86 and {n["status"] for n in topo} == {"up"}
    cfg = client.get("/api/config").json()
    assert "fiber_cut" in cfg["scenarios"]


def test_webhook_ingest_and_incident_detail(client):
    r = client.post("/api/alerts", json={"node_id": "HUB-S", "type": "LINK_DOWN", "message": "uplink down"})
    assert r.status_code == 200 and r.json()["result"] == "new"
    r = client.post("/api/alerts", json=[{"node_id": "HUB-S-T2", "type": "NODE_UNREACHABLE"},
                                         {"node_id": "HUB-S-T3", "type": "NODE_UNREACHABLE"}])
    assert [x["result"] for x in r.json()] == ["new", "new"]
    incs = client.get("/api/incidents?status=active").json()
    assert len(incs) == 1 and incs[0]["root_node_id"] == "HUB-S" and incs[0]["raw_alert_count"] == 3
    d = client.get(f"/api/incidents/{incs[0]['id']}").json()
    assert d["alerts"] and d["events"] and d["runbook"] and d["affected_nodes"]
    assert "Our monitoring points to" in d["status_update"]
    assert client.post("/api/alerts", json={"node_id": "NOPE", "type": "LINK_DOWN"}).status_code == 422


def test_simulate_then_restore_then_auto_resolve(client):
    r = client.post("/api/simulate", json={"scenario": "tower_power_failure", "target": "HUB-E-T3", "speed": 20})
    assert r.status_code == 200 and r.json()["expected_root"] == "HUB-E-T3"
    inc = wait_for(lambda: next(iter(client.get("/api/incidents?status=active").json()), None))
    assert inc and inc["root_node_id"] == "HUB-E-T3"
    assert wait_for(lambda: client.get("/api/metrics").json()["customers_offline"] > 0)
    # settle, then restore
    time.sleep(0.8)
    client.post("/api/restore", json={"incident_id": inc["id"]})
    assert wait_for(lambda: client.get("/api/metrics").json()["customers_offline"] == 0)
    done = wait_for(lambda: [i for i in client.get("/api/incidents").json() if i["status"] == "resolved"], timeout=10)
    assert done, "incident should auto-resolve after the hold period"


def test_manual_status_conflict_and_notes(client):
    client.post("/api/alerts", json={"node_id": "HUB-W-T4", "type": "POWER_FAILURE"})
    inc = client.get("/api/incidents").json()[0]
    assert client.post(f"/api/incidents/{inc['id']}/status", json={"status": "resolved"}).status_code == 409
    r = client.post(f"/api/incidents/{inc['id']}/notes", json={"message": "crew dispatched"})
    assert any(e["message"] == "crew dispatched" for e in r.json()["events"])
    r = client.put(f"/api/incidents/{inc['id']}/status-update", json={"text": "Custom text"})
    assert r.json()["status_update"] == "Custom text" and r.json()["status_update_source"] == "edited"


def test_websocket_receives_snapshot_and_ticks(client):
    with client.websocket_connect("/ws") as ws:
        snap = ws.receive_json()
        assert snap["type"] == "snapshot" and "statuses" in snap and "metrics" in snap
        client.post("/api/alerts", json={"node_id": "HUB-C-T4-C1", "type": "NODE_UNREACHABLE"})
        tick = ws.receive_json()
        assert tick["type"] == "tick" and tick["statuses"]["HUB-C-T4-C1"] == "down"
        assert tick["feed"][0]["node_id"] == "HUB-C-T4-C1"


def test_reset_clears_everything(client):
    client.post("/api/alerts", json={"node_id": "HUB-N", "type": "LINK_DOWN"})
    assert client.get("/api/metrics").json()["customers_offline"] > 0
    client.post("/api/reset")
    m = client.get("/api/metrics").json()
    assert m["customers_offline"] == 0 and m["raw_alerts"] == 0 and client.get("/api/incidents").json() == []
