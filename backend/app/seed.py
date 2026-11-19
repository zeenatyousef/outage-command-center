"""Deterministic demo data: a small fibre/wireless network around Faisalabad.

Coordinates and area names are illustrative demo values, not a real network map.

Hierarchy:  CORE -> 5 hubs -> 4 towers per hub -> 3 cabinets per tower -> customers
Tower T1 of every hub has a backup uplink to the next hub in a ring, so a hub failure
leaves that tower degraded (failover) instead of offline.
"""
from __future__ import annotations

import math
import random

from .db import Database

CORE = ("CORE", "Faisalabad Core POP", 31.4504, 73.1350)

# code, name, lat, lng, tower areas
HUBS = [
    ("N", "North Hub", 31.4900, 73.1350, ["Madina Town", "Gulberg", "Kohinoor City", "Ghulam Muhammad Abad"]),
    ("E", "East Hub", 31.4550, 73.1900, ["Millat Town", "Jinnah Colony", "Sitara Colony", "Raza Abad"]),
    ("S", "South Hub", 31.4100, 73.1400, ["Samanabad", "Batala Colony", "Eden Garden", "Sargodha Road"]),
    ("W", "West Hub", 31.4500, 73.0800, ["Peoples Colony", "Satiana Road", "Canal Road", "Gulistan Colony"]),
    ("C", "Central Hub", 31.4400, 73.1500, ["D Ground", "Civil Lines", "Susan Road", "Clock Tower"]),
]

FIRST = ["Ahmed", "Ali", "Hassan", "Usman", "Bilal", "Hamza", "Zain", "Fahad", "Imran", "Kashif",
         "Ayesha", "Fatima", "Zainab", "Maryam", "Sana", "Hina", "Nida", "Saima", "Rabia", "Amna"]
LAST = ["Khan", "Malik", "Butt", "Chaudhry", "Sheikh", "Ansari", "Qureshi", "Raza", "Iqbal", "Siddiqui"]
HOME_PLANS = ["Home 10 Mbps", "Home 20 Mbps", "Home 50 Mbps"]
BIZ_PLANS = ["Business 100 Mbps", "Business 200 Mbps"]


def seed(db: Database, rng_seed: int = 42, force: bool = False) -> bool:
    """Create topology + customers. Returns False if data already exists."""
    if db.scalar("SELECT COUNT(*) FROM nodes", default=0) and not force:
        return False
    rng = random.Random(rng_seed)

    with db.transaction():
        for t in ("notifications", "incident_events", "alerts", "incidents", "customers", "nodes"):
            db.execute(f"DELETE FROM {t}")

        nodes, customers = [], []
        nodes.append((CORE[0], CORE[1], "core", None, None, CORE[2], CORE[3], "Core POP"))

        for hi, (hc, hname, hlat, hlng, areas) in enumerate(HUBS):
            hid = f"HUB-{hc}"
            nodes.append((hid, hname, "hub", "CORE", None, hlat, hlng, hname))
        ring = [f"HUB-{h[0]}" for h in HUBS]

        cust_id = 1
        for hi, (hc, hname, hlat, hlng, areas) in enumerate(HUBS):
            hid = f"HUB-{hc}"
            for ti, area in enumerate(areas):
                tid = f"{hid}-T{ti + 1}"
                ang = (ti / len(areas)) * 2 * math.pi + rng.uniform(-0.3, 0.3)
                tlat = hlat + 0.013 * math.sin(ang)
                tlng = hlng + 0.016 * math.cos(ang)
                backup = ring[(hi + 1) % len(ring)] if ti == 0 else None
                nodes.append((tid, f"{area} Tower", "tower", hid, backup, tlat, tlng, area))
                for ci in range(3):
                    cid = f"{tid}-C{ci + 1}"
                    cang = (ci / 3) * 2 * math.pi + rng.uniform(-0.4, 0.4)
                    clat = tlat + 0.0045 * math.sin(cang)
                    clng = tlng + 0.0055 * math.cos(cang)
                    nodes.append((cid, f"{area} Cabinet {ci + 1}", "cabinet", tid, None, clat, clng, area))
                    for _ in range(rng.randint(35, 65)):
                        r = rng.random()
                        if r < 0.02:
                            prio, plan = "enterprise", "Dedicated Fibre"
                        elif r < 0.15:
                            prio, plan = "business", rng.choice(BIZ_PLANS)
                        else:
                            prio, plan = "home", rng.choice(HOME_PLANS)
                        customers.append((cust_id, f"{rng.choice(FIRST)} {rng.choice(LAST)}", area, cid, plan, prio))
                        cust_id += 1

        db.executemany(
            "INSERT INTO nodes(id,name,type,parent_id,backup_parent_id,lat,lng,area) VALUES (?,?,?,?,?,?,?,?)",
            nodes,
        )
        db.executemany(
            "INSERT INTO customers(id,name,area,node_id,plan,priority) VALUES (?,?,?,?,?,?)", customers
        )
    return True


if __name__ == "__main__":
    import os
    import sys

    path = os.environ.get("OCC_DB", os.path.join(os.path.dirname(__file__), "..", "data", "occ.db"))
    d = Database(path)
    seed(d, force="--force" in sys.argv)
    print("nodes:", d.scalar("SELECT COUNT(*) FROM nodes"), "customers:", d.scalar("SELECT COUNT(*) FROM customers"))
