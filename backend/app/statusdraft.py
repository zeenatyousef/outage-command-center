"""Human-readable text for incidents: customer status updates, technical summaries, runbooks.

The template drafts are always available. llm.py can replace the customer update with an
AI-written version when an API key is configured.
"""
from __future__ import annotations

from datetime import datetime

CAUSE_TEXT = {
    "LINK_DOWN": "a fibre uplink failure",
    "POWER_FAILURE": "a power failure at a network site",
    "NODE_UNREACHABLE": "an equipment outage",
    "HIGH_LATENCY": "network congestion",
    "PACKET_LOSS": "degraded link quality",
}

RUNBOOKS = {
    "LINK_DOWN": [
        "Check optical power levels and port status on both ends of the uplink",
        "Look for planned maintenance or third-party digging/cable work near the route",
        "If light levels are zero, dispatch the fibre crew with an OTDR to locate the break",
        "Confirm traffic has moved to any backup path and watch its utilisation",
    ],
    "POWER_FAILURE": [
        "Check mains supply, generator and UPS/battery runtime at the site",
        "Dispatch the power/field team with fuel if the site is on battery",
        "Notify the electricity provider and request a restoration ETA",
        "Prepare to shed non-critical load if battery runtime is short",
    ],
    "NODE_UNREACHABLE": [
        "Check the upstream node first: unreachable alerts are often symptoms of a parent failure",
        "Poll the device over an out-of-band path and check local power",
        "Dispatch a technician only if the upstream node is healthy",
    ],
    "HIGH_LATENCY": [
        "Check link utilisation and queue drops on the affected uplink",
        "Look for routing changes or traffic shifted onto a backup path",
        "Identify heavy flows or abnormal traffic and rate-limit if needed",
    ],
    "PACKET_LOSS": [
        "Inspect interface error counters (CRC/FCS) and optics",
        "Clean/replace the suspect patch cord or transceiver",
        "Check for interference if the link is wireless",
    ],
}


def fmt_time(ts: float | None) -> str:
    if not ts:
        return "-"
    return datetime.fromtimestamp(ts).strftime("%H:%M:%S")


def fmt_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 90:
        return f"{seconds} seconds"
    minutes = round(seconds / 60)
    if minutes < 90:
        return f"{minutes} minutes"
    return f"{seconds / 3600:.1f} hours"


def _join_areas(areas: list[str], limit: int = 4) -> str:
    areas = [a for a in areas if a]
    if not areas:
        return "the affected area"
    if len(areas) > limit:
        return ", ".join(areas[:limit]) + f" and {len(areas) - limit} other areas"
    if len(areas) == 1:
        return areas[0]
    return ", ".join(areas[:-1]) + " and " + areas[-1]


def dominant_type(type_counts: dict[str, int], root_types: list[str]) -> str:
    for t in ("LINK_DOWN", "POWER_FAILURE"):
        if t in root_types:
            return t
    for t in ("LINK_DOWN", "POWER_FAILURE", "NODE_UNREACHABLE", "PACKET_LOSS", "HIGH_LATENCY"):
        if t in type_counts:
            return t
    return "NODE_UNREACHABLE"


def _cause_phrase(cause: str, inferred: bool) -> str:
    """CAUSE_TEXT values may already start with an article ('a fibre uplink failure')."""
    if not inferred:
        return cause
    for art in ("a ", "an "):
        if cause.startswith(art):
            return f"a suspected {cause[len(art):]}"
    return f"suspected {cause}"


def template_update(inc: dict, root: dict, areas: list[str], dominant: str, now: float | None = None) -> str:
    off, deg = inc["customers_offline"], inc["customers_degraded"]
    area_txt = _join_areas(areas)
    cause = CAUSE_TEXT.get(dominant, "a network fault")

    if inc["status"] == "resolved":
        dur = fmt_duration((inc["resolved_ts"] or now or inc["started_ts"]) - inc["started_ts"])
        peak = inc["peak_offline"] + (inc["peak_degraded"] if not inc["peak_offline"] else 0)
        return (
            f"Update: Service has been restored for customers in {area_txt}. "
            f"The issue, caused by {cause} near {root['name']}, lasted about {dur} and affected up to "
            f"{peak:,} customers. We apologise for the inconvenience and will review how to prevent a repeat."
        )
    if inc["status"] == "mitigated":
        return (
            f"Update: Services for customers in {area_txt} are recovering after {cause} near {root['name']}. "
            "Our team is monitoring the network to confirm it stays stable."
        )

    cause_phrase = _cause_phrase(cause, bool(inc["inferred"]))
    if inc["kind"] == "flapping":
        return (
            f"We are aware of intermittent connectivity for customers in {area_txt}, caused by an unstable link "
            f"near {root['name']}. Our engineers are working to stabilise it."
        )
    if off and deg:
        impact = f"{off:,} customers have no service and {deg:,} are seeing slower speeds"
    elif off:
        impact = f"approximately {off:,} customers have no service"
    elif deg:
        impact = f"approximately {deg:,} customers are experiencing slow or unstable service"
    else:
        impact = "a small number of customers may notice issues"
    return (
        f"We are aware of a service disruption affecting {area_txt}. "
        f"Our monitoring points to {cause_phrase} near {root['name']}, and {impact}. "
        "Our network team is investigating and we will share another update within 30 minutes."
    )


def technical_summary(inc: dict, root: dict, type_counts: dict[str, int], affected_nodes: int) -> str:
    raw = inc["raw_alert_count"]
    reduction = f"{(1 - 1 / raw) * 100:.0f}%" if raw > 1 else "0%"
    types = ", ".join(f"{t} x{c}" for t, c in sorted(type_counts.items(), key=lambda kv: -kv[1])) or "none"
    how = (
        "inferred: several downstream nodes alerted within the correlation window while the root node itself did not"
        if inc["inferred"]
        else "direct alert on the root node"
    )
    lines = [
        f"Root cause: {root['name']} [{root['id']}] ({root['type']}), {how}.",
        f"Kind: {inc['kind']}. First alert at {fmt_time(inc['started_ts'])}.",
        f"Alert noise: {raw} raw alerts correlated into 1 incident ({reduction} reduction). Types: {types}.",
        f"Impact now: {inc['customers_offline']:,} offline, {inc['customers_degraded']:,} degraded across "
        f"{affected_nodes} affected nodes ({inc['business_affected']:,} business/enterprise customers affected).",
        f"Peak impact: {inc['peak_offline']:,} offline, {inc['peak_degraded']:,} degraded.",
    ]
    if inc["flap_count"]:
        lines.append(f"Flaps observed: {inc['flap_count']}.")
    return "\n".join(lines)


def runbook(type_counts: dict[str, int], root_types: list[str]) -> list[str]:
    return RUNBOOKS.get(dominant_type(type_counts, root_types), [])


def ai_prompt(inc: dict, root: dict, areas: list[str], dominant: str) -> tuple[str, str]:
    system = (
        "You write short, calm, factual status updates for a telecom/ISP network operations team. "
        "Use only the facts provided. Do not invent causes, ETAs, or numbers. Plain text, no markdown."
    )
    facts = {
        "incident_status": inc["status"],
        "kind": inc["kind"],
        "root_cause_location": root["name"],
        "root_cause_is_inferred_not_confirmed": bool(inc["inferred"]),
        "likely_cause": CAUSE_TEXT.get(dominant, "network fault"),
        "areas": areas,
        "customers_offline": inc["customers_offline"],
        "customers_degraded": inc["customers_degraded"],
        "peak_customers_offline": inc["peak_offline"],
        "business_customers_affected": inc["business_affected"],
    }
    prompt = (
        "Write a customer-facing status update (max 70 words) for this network incident. "
        "Acknowledge the problem, say who is affected, say what we are doing, and promise the next update "
        "in 30 minutes unless the status is resolved. If the cause is inferred, say 'suspected'.\n\n"
        f"Facts: {facts}"
    )
    return system, prompt
