"""Network topology as a tree with optional backup (failover) uplinks."""
from __future__ import annotations

from collections import defaultdict


class Topology:
    def __init__(self, nodes: list[dict]):
        self.nodes: dict[str, dict] = {n["id"]: n for n in nodes}
        self.children: dict[str, list[str]] = defaultdict(list)
        for n in nodes:
            if n["parent_id"]:
                self.children[n["parent_id"]].append(n["id"])
        self.depth: dict[str, int] = {}
        for nid in self.nodes:
            self.depth[nid] = len(self.ancestors(nid))
        self.order = sorted(self.nodes, key=lambda i: (self.depth[i], i))
        self._subtree: dict[str, list[str]] = {}
        self._subtree_set: dict[str, frozenset[str]] = {}

    def parent(self, nid: str) -> str | None:
        return self.nodes[nid]["parent_id"]

    def ancestors(self, nid: str) -> list[str]:
        out = []
        cur = self.nodes[nid]["parent_id"]
        while cur:
            out.append(cur)
            cur = self.nodes[cur]["parent_id"]
        return out

    def is_ancestor(self, a: str, b: str) -> bool:
        """True if a is a strict ancestor of b."""
        return a != b and a in self.ancestors(b)

    def is_ancestor_or_self(self, a: str, b: str) -> bool:
        return a == b or a in self.ancestors(b)

    def subtree(self, nid: str) -> list[str]:
        """nid and all descendants."""
        if nid not in self._subtree:
            out = [nid]
            for c in self.children.get(nid, []):
                out.extend(self.subtree(c))
            self._subtree[nid] = out
            self._subtree_set[nid] = frozenset(out)
        return self._subtree[nid]

    def subtree_set(self, nid: str) -> frozenset[str]:
        self.subtree(nid)
        return self._subtree_set[nid]

    def effective_status(self, down: set[str], degraded: set[str]) -> dict[str, str]:
        """Propagate direct faults down the tree.

        - a node with a direct DOWN fault is down
        - a node below a down parent is down, unless it has a backup uplink whose own
          parent chain is still healthy: then it is degraded (running on the backup path)
        - a node below a degraded parent, or with a direct degradation fault, is degraded
        Backup parents sit at the same depth as the primary parent, so processing nodes
        in depth order always has the backup's status ready.
        """
        status: dict[str, str] = {}
        for nid in self.order:
            n = self.nodes[nid]
            if nid in down:
                s = "down"
            else:
                p = n["parent_id"]
                if p is None:
                    s = "degraded" if nid in degraded else "up"
                else:
                    ps = status[p]
                    if ps == "down":
                        b = n.get("backup_parent_id")
                        s = "degraded" if (b and status.get(b) != "down") else "down"
                    elif ps == "degraded" or nid in degraded:
                        s = "degraded"
                    else:
                        s = "up"
            status[nid] = s
        return status
