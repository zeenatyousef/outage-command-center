"""Measure the correlation engine against simulated scenarios with known ground truth.

    python evaluate.py            # 10 randomised runs of every scenario type
    python evaluate.py --runs 25  # more runs

For each run a fresh in-memory database is used and alerts are replayed with virtual time (no
sleeping). Ground truth comes from the scenario generator: which node really failed, how many
incidents there should be, and the customer impact computed from the topology alone.
Writes evaluation_results.md next to this file.
"""
from __future__ import annotations

import argparse
import random
import statistics
from pathlib import Path

from app import simulator
from app.correlation import Engine
from app.db import Database
from app.seed import seed

BASE = 1_700_000_000.0


def run_one(name: str, seed_value: int) -> dict:
    db = Database(":memory:")
    seed(db)
    eng = Engine(db, hold=15.0)
    rng = random.Random(seed_value)
    sc = simulator.build(eng.topo, name, None, rng, noise=True)
    simulator.run_instant(eng, sc.events, BASE)
    truth = sc.truth
    incs = eng.list_incidents()
    raw = sum(1 for e in sc.events if e.alert["type"] not in ("CLEARED", "RECOVERED", "UP"))

    roots = truth.get("roots") or [truth["root"]]
    by_root = {i["root_node_id"]: i for i in incs}
    root_ok = all(r in by_root for r in roots)

    # impact: compare each true root's incident against impact computed from the failure set alone
    impact_ok = True
    if truth.get("ends_clear"):
        impact_ok = all(i["customers_offline"] == 0 for i in incs)
    else:
        for r in roots:
            if r not in by_root:
                impact_ok = False
                continue
            down = {r} if r in truth["down"] else set()
            deg = {r} if r in truth["degraded"] else set()
            t = eng.impact_for(down, deg, r)
            i = by_root[r]
            if (i["customers_offline"], i["customers_degraded"]) != (t["offline"], t["degraded"]):
                impact_ok = False

    kind_ok = all(by_root[r]["kind"] == truth["kind"] for r in roots if r in by_root) and root_ok
    infer_ok = all(bool(by_root[r]["inferred"]) == truth["inferred"] for r in roots if r in by_root) and root_ok
    return {
        "scenario": name, "raw": raw, "incidents": len(incs), "expected_incidents": truth["incidents"],
        "count_ok": len(incs) == truth["incidents"], "root_ok": root_ok, "impact_ok": impact_ok,
        "kind_ok": kind_ok, "infer_ok": infer_ok,
        "merged": db.scalar("SELECT COUNT(*) FROM incidents WHERE merged_into IS NOT NULL", default=0),
    }


def pct(xs) -> float:
    xs = list(xs)
    return 100.0 * sum(xs) / len(xs) if xs else 0.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=10)
    args = ap.parse_args()

    results = []
    for name in simulator.SCENARIOS:
        for k in range(args.runs):
            results.append(run_one(name, 1000 + k))

    lines = [
        "# Correlation engine evaluation",
        "",
        f"{len(results)} randomised runs ({args.runs} per scenario type), fresh database each run, virtual-time replay.",
        "",
        "| Scenario | Runs | Raw alerts (avg) | Incidents (avg) | Noise reduction | Incident count correct | Root cause correct | Impact exact | Kind correct |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for name in simulator.SCENARIOS:
        rs = [r for r in results if r["scenario"] == name]
        raw = statistics.mean(r["raw"] for r in rs)
        inc = statistics.mean(r["incidents"] for r in rs)
        lines.append(
            f"| {name} | {len(rs)} | {raw:.1f} | {inc:.1f} | {100 * (1 - inc / raw):.0f}% | "
            f"{pct(r['count_ok'] for r in rs):.0f}% | {pct(r['root_ok'] for r in rs):.0f}% | "
            f"{pct(r['impact_ok'] for r in rs):.0f}% | {pct(r['kind_ok'] for r in rs):.0f}% |"
        )
    tot_raw = sum(r["raw"] for r in results)
    tot_inc = sum(r["incidents"] for r in results)
    lines += [
        f"| **All** | {len(results)} | {tot_raw / len(results):.1f} | {tot_inc / len(results):.1f} | "
        f"{100 * (1 - tot_inc / tot_raw):.0f}% | {pct(r['count_ok'] for r in results):.0f}% | "
        f"{pct(r['root_ok'] for r in results):.0f}% | {pct(r['impact_ok'] for r in results):.0f}% | "
        f"{pct(r['kind_ok'] for r in results):.0f}% |",
        "",
        f"Total: {tot_raw} raw alerts became {tot_inc} incidents.",
        "",
        "How to read this: *incident count correct* means the number of incidents equals the number of real,"
        " independent faults injected (including one unrelated noise blip in `fiber_cut`). *Impact exact* means offline and degraded"
        " customer counts equal the figures computed directly from the topology for the true failure.",
        "",
        "Limits: the scenarios come from the same topology model the engine uses, so this checks correlation logic,"
        " not accuracy on real-world monitoring data.",
    ]
    failures = [r for r in results if not (r["count_ok"] and r["root_ok"] and r["impact_ok"] and r["kind_ok"] and r["infer_ok"])]
    if failures:
        lines += ["", "## Failed runs", ""] + [f"- {r['scenario']}: {r}" for r in failures]
    text = "\n".join(lines)
    print(text)
    (Path(__file__).parent / "evaluation_results.md").write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
