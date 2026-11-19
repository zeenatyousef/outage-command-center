import random

import pytest

from app import simulator
from app.simulator import run_instant
from conftest import BASE, alert


def active(engine):
    return engine.list_incidents("active")


def test_hub_fiber_cut_collapses_into_one_incident(engine):
    sc = simulator.build(engine.topo, "fiber_cut", "HUB-N", random.Random(1), noise=False)
    run_instant(engine, sc.events, BASE)
    incs = active(engine)
    assert len(incs) == 1
    inc = incs[0]
    assert inc["root_node_id"] == "HUB-N" and inc["kind"] == "outage" and not inc["inferred"]
    truth = engine.impact_for({"HUB-N"}, set(), "HUB-N")
    assert inc["customers_offline"] == truth["offline"] > 0
    assert inc["customers_degraded"] == truth["degraded"] > 0  # T1 fails over to its backup hub
    assert inc["raw_alert_count"] == len(sc.events) > 10  # every raw alert is counted, none lost
    assert inc["severity"] == "critical"


def test_customer_update_reads_naturally(engine):
    sc = simulator.build(engine.topo, "fiber_cut", "HUB-N", random.Random(1), noise=False)
    run_instant(engine, sc.events, BASE)
    text = active(engine)[0]["status_update"]
    assert "points to a fibre uplink failure near North Hub" in text
    assert " a a " not in text and "a an " not in text
    engine.reset()
    sc = simulator.build(engine.topo, "silent_hub_failure", "HUB-W", random.Random(3))
    run_instant(engine, sc.events, BASE)
    text = active(engine)[0]["status_update"]
    assert "points to a suspected equipment outage near West Hub" in text


def test_backup_path_makes_tower_degraded_not_down(engine):
    run_instant(engine, [simulator.SimEvent(0, {"node_id": "HUB-N", "type": "LINK_DOWN"})], BASE)
    st = engine.statuses()
    assert st["HUB-N"] == "down"
    assert st["HUB-N-T1"] == "degraded"  # has backup uplink via HUB-E
    assert st["HUB-N-T1-C1"] == "degraded"
    assert st["HUB-N-T2"] == "down" and st["HUB-N-T2-C3"] == "down"
    assert st["HUB-E"] == "up"


def test_symptoms_before_root_still_merge_into_one_incident(engine):
    # cabinet and tower alerts arrive first, the hub alert last
    engine.ingest(alert("HUB-S-T2-C1", t=0))
    engine.ingest(alert("HUB-S-T2-C2", t=1))
    engine.ingest(alert("HUB-S-T3-C1", t=2))
    engine.ingest(alert("HUB-S", "LINK_DOWN", t=3))
    incs = active(engine)
    assert len(incs) == 1 and incs[0]["root_node_id"] == "HUB-S"
    assert incs[0]["raw_alert_count"] == 4


def test_common_ancestor_inference_when_parent_is_silent(engine):
    sc = simulator.build(engine.topo, "silent_hub_failure", "HUB-W", random.Random(3))
    run_instant(engine, sc.events, BASE)
    incs = active(engine)
    assert len(incs) == 1
    assert incs[0]["root_node_id"] == "HUB-W" and incs[0]["inferred"] == 1
    assert "Suspected" in incs[0]["title"]
    # a late direct alert confirms the root cause
    engine.ingest(alert("HUB-W", "LINK_DOWN", t=sc.duration + 5))
    inc = active(engine)[0]
    assert inc["inferred"] == 0 and inc["title"].startswith("Outage")


def test_merged_incident_timeline_has_one_opening_entry(engine):
    sc = simulator.build(engine.topo, "silent_hub_failure", "HUB-W", random.Random(3))
    run_instant(engine, sc.events, BASE)
    detail = engine.incident_detail(active(engine)[0]["id"])
    messages = [e["message"] for e in detail["events"]]
    assert sum(m.startswith("Incident opened by") for m in messages) == 1
    assert any(m.startswith("Earlier alert (merged from incident #") for m in messages)
    assert any("itself raised no alert (inferred)" in m for m in messages)


def test_two_independent_failures_stay_separate(engine):
    engine.ingest(alert("HUB-N-T2", "POWER_FAILURE", t=0))
    engine.ingest(alert("HUB-N-T2-C1", t=1))
    engine.ingest(alert("HUB-S-T3", "POWER_FAILURE", t=1))
    engine.ingest(alert("HUB-S-T3-C2", t=2))
    roots = sorted(i["root_node_id"] for i in active(engine))
    assert roots == ["HUB-N-T2", "HUB-S-T3"]


def test_single_cabinet_does_not_trigger_inference(engine):
    engine.ingest(alert("HUB-E-T2-C1", t=0))
    incs = active(engine)
    assert len(incs) == 1 and incs[0]["root_node_id"] == "HUB-E-T2-C1" and incs[0]["severity"] in ("minor", "major")


def test_duplicate_and_repeated_alerts_are_deduplicated(engine):
    for i in range(50):
        engine.ingest(alert("HUB-C-T2", "HIGH_LATENCY", t=i))
    engine.ingest(alert("HUB-C-T2", "HIGH_LATENCY", t=60, event_id="same"))
    engine.ingest(alert("HUB-C-T2", "HIGH_LATENCY", t=61, event_id="same"))
    assert engine.db.scalar("SELECT COUNT(*) FROM alerts") == 1
    assert engine.db.scalar("SELECT SUM(count) FROM alerts") == 52
    incs = active(engine)
    assert len(incs) == 1 and incs[0]["raw_alert_count"] == 52 and incs[0]["kind"] == "degradation"
    assert engine.metrics()["noise_reduction_pct"] > 95


def test_flapping_link_is_classified_once(engine):
    sc = simulator.build(engine.topo, "flapping_link", "HUB-E-T3", random.Random(5))
    run_instant(engine, sc.events, BASE)
    incs = engine.list_incidents()
    assert len(incs) == 1
    assert incs[0]["kind"] == "flapping" and incs[0]["flap_count"] >= 3
    assert incs[0]["status"] == "mitigated"  # ended up, still in stability hold
    assert "Flapping" in incs[0]["title"]


def test_recovery_goes_mitigated_then_resolved_after_hold(engine):
    run_instant(engine, [simulator.SimEvent(0, {"node_id": "HUB-W-T2", "type": "POWER_FAILURE"}),
                         simulator.SimEvent(1, {"node_id": "HUB-W-T2-C1", "type": "NODE_UNREACHABLE"})], BASE)
    assert engine.metrics()["customers_offline"] > 0
    engine.ingest(alert("HUB-W-T2", "CLEARED", t=100))
    assert active(engine)[0]["status"] == "investigating"  # cabinet alert still open
    engine.ingest(alert("HUB-W-T2-C1", "CLEARED", t=101))
    assert active(engine)[0]["status"] == "mitigated"
    assert engine.metrics()["customers_offline"] == 0
    assert engine.tick(BASE + 105) == []  # still inside the 15 s hold
    assert engine.tick(BASE + 120) != []
    inc = engine.list_incidents()[0]
    assert inc["status"] == "resolved" and inc["resolved_ts"] is not None
    assert inc["status_update"].startswith("Update: Service has been restored")


def test_new_alert_during_hold_reopens_incident(engine):
    engine.ingest(alert("HUB-N-T3-C2", t=0))
    engine.ingest(alert("HUB-N-T3-C2", "CLEARED", t=5))
    assert active(engine)[0]["status"] == "mitigated"
    engine.ingest(alert("HUB-N-T3-C2", t=8))
    incs = active(engine)
    assert len(incs) == 1 and incs[0]["status"] == "investigating"


def notifications(engine):
    return [p for k, p in engine.drain_outbox() if k == "notification"]


def test_notifications_only_for_major_and_critical(engine):
    engine.ingest(alert("HUB-E-T4-C3", t=0))  # tiny incident
    engine.tick(BASE + 10)
    assert [n["level"] for n in notifications(engine)] in ([], ["major"])  # never critical for one cabinet
    engine.ingest(alert("HUB-E", "LINK_DOWN", t=11))
    engine.tick(BASE + 20)
    assert "critical" in [n["level"] for n in notifications(engine)]


def test_notification_waits_for_correlation_to_settle(engine):
    engine.ingest(alert("HUB-S-T2", "POWER_FAILURE", t=0))
    engine.tick(BASE + 1)
    assert notifications(engine) == []  # still inside the settle window
    engine.tick(BASE + 4)
    assert len(notifications(engine)) == 1


def test_silent_hub_failure_sends_one_notification_not_one_per_child(engine):
    sc = simulator.build(engine.topo, "silent_hub_failure", "HUB-W", random.Random(3))
    for e in sorted(sc.events, key=lambda e: e.t):
        a = dict(e.alert)
        a["ts"] = BASE + e.t
        engine.ingest(a)
        engine.tick(BASE + e.t)  # the ticker runs once a second in the live app
    engine.tick(BASE + sc.duration + 10)
    notes = notifications(engine)
    assert len(notes) == 1, [n["title"] for n in notes]
    assert notes[0]["level"] == "critical" and "West Hub" in notes[0]["title"]


def test_recovery_before_settle_sends_nothing(engine):
    engine.ingest(alert("HUB-N-T2", "POWER_FAILURE", t=0))
    engine.ingest(alert("HUB-N-T2", "CLEARED", t=1))
    engine.tick(BASE + 10)
    assert notifications(engine) == []


def test_manual_resolve_requires_no_open_alerts(engine):
    engine.ingest(alert("HUB-S-T4", "POWER_FAILURE", t=0))
    inc_id = active(engine)[0]["id"]
    with pytest.raises(ValueError):
        engine.set_status(inc_id, "resolved", now=BASE + 5)
    engine.ingest(alert("HUB-S-T4", "CLEARED", t=10))
    engine.set_status(inc_id, "resolved", "fixed generator", now=BASE + 11)
    assert engine.list_incidents()[0]["status"] == "resolved"


def test_unknown_node_and_type_rejected(engine):
    with pytest.raises(ValueError):
        engine.ingest({"node_id": "NOPE", "type": "LINK_DOWN"})
    with pytest.raises(ValueError):
        engine.ingest({"node_id": "HUB-N", "type": "BOGUS"})
