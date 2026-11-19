"""Outage scenario generator.

A scenario is a timed list of raw alerts plus ground truth (which node really failed and how many
customers that should affect). The same scenario can be replayed in real time for the live demo,
or run instantly with virtual timestamps for tests and evaluation.
"""
from __future__ import annotations

import asyncio
import random
import time
import uuid
from dataclasses import dataclass, field

from .topology import Topology

SCENARIOS = {
    "fiber_cut": "Fibre cut on a hub uplink: the hub and everything behind it goes dark (one tower fails over to a backup path)",
    "tower_power_failure": "Power failure at a tower: its cabinets become unreachable",
    "silent_hub_failure": "Hub fails without sending its own alert; only downstream nodes report (root cause must be inferred)",
    "latency_spike": "Congestion on a node: repeated latency and packet-loss alerts, many duplicates",
    "flapping_link": "Unstable link that goes down and up repeatedly",
    "cabinet_failure": "Single street cabinet goes offline (small incident)",
    "double_incident": "Two unrelated failures in different parts of the network at the same time",
}


@dataclass
class SimEvent:
    t: float
    alert: dict


@dataclass
class Scenario:
    name: str
    description: str
    target: str
    events: list[SimEvent] = field(default_factory=list)
    truth: dict = field(default_factory=dict)  # root, down, degraded, incidents, kind

    @property
    def duration(self) -> float:
        return max((e.t for e in self.events), default=0.0)


def _alert(node: str, typ: str, msg: str, t: float, severity: str | None = None) -> SimEvent:
    sev = severity or ("critical" if typ in ("LINK_DOWN", "POWER_FAILURE", "NODE_UNREACHABLE") else "warning")
    return SimEvent(t, {"event_id": uuid.uuid4().hex, "node_id": node, "type": typ, "severity": sev, "message": msg})


def _pick(rng: random.Random, topo: Topology, node_type: str, exclude_sub: set[str] | None = None) -> str:
    choices = [n for n, v in topo.nodes.items() if v["type"] == node_type and not (exclude_sub and n in exclude_sub)]
    return rng.choice(sorted(choices))


def _descendant_alerts(topo: Topology, rng: random.Random, root: str, status: dict[str, str], t0: float,
                       skip_cabinets_prob: float = 0.0, spread: float = 3.0) -> list[SimEvent]:
    ev: list[SimEvent] = []
    for d in topo.subtree(root):
        if d == root:
            continue
        st = status[d]
        n = topo.nodes[d]
        if st == "down":
            if n["type"] == "cabinet" and rng.random() < skip_cabinets_prob:
                continue
            t = t0 + rng.uniform(0.2, spread)
            ev.append(_alert(d, "NODE_UNREACHABLE", f"{n['name']} not responding to polls", t))
            if rng.random() < 0.35:  # duplicate from a second poller
                ev.append(_alert(d, "NODE_UNREACHABLE", f"{n['name']} not responding to polls (retry)", t + rng.uniform(1, 3)))
        elif st == "degraded":
            if n["type"] == "tower":
                ev.append(_alert(d, "HIGH_LATENCY", f"{n['name']} running on backup uplink, latency high", t0 + rng.uniform(0.5, spread)))
    return ev


def build(topo: Topology, name: str, target: str | None = None, rng: random.Random | None = None,
          noise: bool = True) -> Scenario:
    rng = rng or random.Random()
    if name not in SCENARIOS:
        raise ValueError(f"unknown scenario {name!r}")
    sc = Scenario(name, SCENARIOS[name], target or "")

    def noise_alert(avoid: set[str], t: float):
        # an unrelated, minor latency blip elsewhere in the network
        cab = _pick(rng, topo, "cabinet", avoid)
        sc.events.append(_alert(cab, "HIGH_LATENCY", f"{topo.nodes[cab]['name']} latency above threshold", t))
        return cab

    if name == "fiber_cut":
        hub = target if target in topo.nodes else _pick(rng, topo, "hub")
        sc.target = hub
        status = topo.effective_status({hub}, set())
        root_delay = rng.choice([0.0, 0.0, 0.0, rng.uniform(1.0, 2.5)])  # sometimes the root alert lags its symptoms
        sc.events.append(_alert(hub, "LINK_DOWN", f"Uplink to {topo.nodes[hub]['name']} lost (loss of light)", root_delay))
        sc.events += _descendant_alerts(topo, rng, hub, status, 0.0)
        sc.truth = {"root": hub, "down": {hub}, "degraded": set(), "incidents": 1, "kind": "outage", "inferred": False}
        if noise:
            noise_alert(set(topo.subtree(hub)), rng.uniform(0.5, 4))
            sc.truth["incidents"] += 1

    elif name == "tower_power_failure":
        tower = target if target in topo.nodes else _pick(rng, topo, "tower")
        sc.target = tower
        status = topo.effective_status({tower}, set())
        sc.events.append(_alert(tower, "POWER_FAILURE", f"Mains failure at {topo.nodes[tower]['name']}, on battery then lost", 0.0))
        sc.events += _descendant_alerts(topo, rng, tower, status, 0.0, spread=2.0)
        sc.truth = {"root": tower, "down": {tower}, "degraded": set(), "incidents": 1, "kind": "outage", "inferred": False}

    elif name == "silent_hub_failure":
        hub = target if target in topo.nodes else _pick(rng, topo, "hub")
        sc.target = hub
        status = topo.effective_status({hub}, set())
        sc.events += _descendant_alerts(topo, rng, hub, status, 0.0, skip_cabinets_prob=0.4, spread=6.0)
        sc.truth = {"root": hub, "down": {hub}, "degraded": set(), "incidents": 1, "kind": "outage", "inferred": True}

    elif name == "latency_spike":
        node = target if target in topo.nodes else _pick(rng, topo, "tower")
        sc.target = node
        n = topo.nodes[node]
        t = 0.0
        for i in range(rng.randint(5, 9)):  # repeated alerts for the same condition
            sc.events.append(_alert(node, "HIGH_LATENCY", f"{n['name']} latency {rng.randint(180, 420)} ms", t))
            t += rng.uniform(0.5, 2.0)
        sc.events.append(_alert(node, "PACKET_LOSS", f"{n['name']} packet loss {rng.randint(3, 9)}%", rng.uniform(1, 4)))
        for d in topo.subtree(node):
            if d != node and rng.random() < 0.3:
                sc.events.append(_alert(d, "HIGH_LATENCY", f"{topo.nodes[d]['name']} slow", rng.uniform(1, 6)))
        sc.truth = {"root": node, "down": set(), "degraded": {node}, "incidents": 1, "kind": "degradation", "inferred": False}

    elif name == "flapping_link":
        node = target if target in topo.nodes else _pick(rng, topo, "tower")
        sc.target = node
        n = topo.nodes[node]
        t = 0.0
        for _ in range(5):
            sc.events.append(_alert(node, "LINK_DOWN", f"{n['name']} link down", t))
            t += rng.uniform(5, 9)
            sc.events.append(_alert(node, "CLEARED", f"{n['name']} link up", t, severity="info"))
            t += rng.uniform(5, 9)
        # ends in a stable "up" state; the incident then goes mitigated and later resolved
        sc.truth = {"root": node, "down": set(), "degraded": set(), "incidents": 1, "kind": "flapping", "inferred": False,
                    "ends_clear": True}

    elif name == "cabinet_failure":
        cab = target if target in topo.nodes else _pick(rng, topo, "cabinet")
        sc.target = cab
        sc.events.append(_alert(cab, "NODE_UNREACHABLE", f"{topo.nodes[cab]['name']} unreachable", 0.0))
        sc.truth = {"root": cab, "down": {cab}, "degraded": set(), "incidents": 1, "kind": "outage", "inferred": False}

    elif name == "double_incident":
        t1 = _pick(rng, topo, "tower")
        hub1 = topo.parent(t1)
        other = _pick(rng, topo, "tower", set(topo.subtree(hub1)))
        sc.target = f"{t1},{other}"
        for tw, delay in ((t1, 0.0), (other, rng.uniform(0.2, 1.5))):
            status = topo.effective_status({tw}, set())
            sc.events.append(_alert(tw, "POWER_FAILURE", f"Mains failure at {topo.nodes[tw]['name']}", delay))
            sc.events += _descendant_alerts(topo, rng, tw, status, delay, spread=2.0)
        sc.truth = {"root": t1, "roots": [t1, other], "down": {t1, other}, "degraded": set(), "incidents": 2,
                    "kind": "outage", "inferred": False}

    sc.events.sort(key=lambda e: e.t)
    return sc


def restore_events(topo: Topology, open_nodes: list[str], rng: random.Random | None = None, spread: float = 3.0) -> list[SimEvent]:
    """CLEARED events for the given nodes, children recovering slightly after their parent."""
    rng = rng or random.Random()
    out = []
    for n in open_nodes:
        t = topo.depth[n] * 0.4 + rng.uniform(0, spread)
        out.append(SimEvent(t, {"event_id": uuid.uuid4().hex, "node_id": n, "type": "CLEARED",
                                "severity": "info", "message": f"{topo.nodes[n]['name']} recovered"}))
    out.sort(key=lambda e: e.t)
    return out


def run_instant(engine, events: list[SimEvent], base_ts: float = 1_700_000_000.0) -> list[dict]:
    """Feed events using virtual timestamps (no sleeping). Returns the ingest results."""
    results = []
    for e in sorted(events, key=lambda e: e.t):
        a = dict(e.alert)
        a["ts"] = base_ts + e.t
        results.append(engine.ingest(a))
    return results


async def play(ingest_cb, events: list[SimEvent], speed: float = 1.0) -> None:
    """Replay events in real time. ingest_cb(alert_dict) is called with a live timestamp."""
    start = time.monotonic()
    for e in sorted(events, key=lambda e: e.t):
        delay = e.t / max(speed, 0.01) - (time.monotonic() - start)
        if delay > 0:
            await asyncio.sleep(delay)
        a = dict(e.alert)
        a["ts"] = time.time()
        ingest_cb(a)
