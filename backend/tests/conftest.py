import os
import random
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.correlation import Engine  # noqa: E402
from app.db import Database  # noqa: E402
from app.seed import seed  # noqa: E402

BASE = 1_700_000_000.0


@pytest.fixture()
def engine():
    db = Database(":memory:")
    seed(db)
    return Engine(db, hold=15.0)


@pytest.fixture()
def rng():
    return random.Random(7)


def alert(node, typ="NODE_UNREACHABLE", t=0.0, event_id=None):
    a = {"node_id": node, "type": typ, "ts": BASE + t}
    if event_id:
        a["event_id"] = event_id
    return a
