# Network Outage Command Center

A live dashboard that turns a flood of raw network alerts into a few incidents, each with a root cause, a customer-impact count and a ready-to-send status update.

It runs on your own machine with no Docker and no Telegram. Data lives in a local SQLite file.

## Documentation

- `docs/Outage-Command-Center-Documentation.pdf`: the full guide (how it works, architecture, running it, using the dashboard, connecting real tools, results, limits).

## Run it

You need **Python 3.10 or newer**. Node.js is only needed if you want to change the UI.

**Windows:** double-click `start.bat`
**macOS / Linux:** run `./start.sh`

The first run creates a virtual environment, installs the Python packages, seeds the sample network and opens http://localhost:8000. Later runs start in a few seconds.

The map tiles and fonts load from the internet. Without a connection the map background is blank and the font falls back to the system font, but the network itself still draws and everything works.

### Change the UI (optional)

```
cd frontend
npm install
npm run dev        # http://localhost:5173, proxies to the backend on :8000
npm run build      # rebuilds frontend/dist, which the backend serves
```

## Walkthrough script (about 5 minutes)

1. Show the healthy map: 86 nodes, 2,973 customers.
2. Pick **Fiber cut**, location **North Hub**, press **Run scenario**.
3. Watch the map turn red from the hub outward. Raw alerts pile up in the **Raw alerts** tab, but **Incidents** shows one. The counter shows how much noise was removed.
4. A **critical** notification appears a few seconds later (the app waits for correlation to settle so it announces one outage, not one per tower). Open the incident to see the customer update, technical summary, what to check, and the timeline.
5. Point out the dashed purple line: one tower on the North Hub fails over to a backup uplink, so those customers are *degraded*, not offline.
6. Press **Restore network**. The incident goes to *Recovering*, then resolves itself after a 15-second stability hold.
7. Run **Silent hub failure**. The hub never raises an alert, yet the incident is rooted at the hub and marked *Root cause inferred*. This is the strongest moment of the walkthrough.
8. Finish with **Two faults at once** to show unrelated failures are not merged, and **Flapping link** to show repeated down/up is grouped and labelled.

Use **Reset** between runs.

## How correlation works

Every alert goes through these rules (`backend/app/correlation.py`):

1. **Deduplicate.** The same event, or the same node and type while still open, is counted but not stored again.
2. **Attach to a parent incident.** If an open incident is rooted at the alert's node or one of its ancestors, the alert is a symptom of it.
3. **Promote the root.** If the alert is upstream of existing incidents, those incidents merge and the root moves up.
4. **Infer a silent parent.** If at least 60% of a node's children are alerting within 120 seconds and at least one is down, the parent is the probable root cause even though it sent nothing.
5. **Open a new incident** if none of the above apply.
6. **Flapping.** A fault that returns within 120 seconds of clearing counts as a flap. Three flaps classify the incident as flapping.
7. **Recovery.** All alerts cleared means *Recovering*. After 15 quiet seconds it becomes *Resolved*. A new alert during that hold reopens it.

Customer impact is computed from the topology: a node under a failed parent is down, unless it has a backup uplink with a healthy path, in which case it is degraded. Severity combines customer counts with weights (home 1, business 3, enterprise 8).

## Measured results

`python evaluate.py` replays 70 randomised scenarios with known ground truth (`backend/evaluation_results.md`). Latest run: 636 raw alerts became 90 incidents (86% less noise), with the correct root cause, incident count, impact figures and incident type in all 70 runs.

Be clear about what this shows: the scenarios are generated from the same topology model the engine uses, so it validates the correlation logic, not accuracy on a real network's monitoring data. Switching the inference rule off drops the silent-hub scenario to 0% correct, so the check can fail.

## Optional settings

Set these as environment variables before starting. None are required.

| Variable | Effect |
|---|---|
| `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` | Enables **Rewrite with AI** on the customer update. Optional `LLM_MODEL`, `OPENAI_BASE_URL`. Without a key, the template draft is used. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `ALERT_EMAIL_TO` | Emails major and critical notifications. For Gmail use an app password. |
| `OCC_RESOLVE_HOLD` | Seconds of quiet before an incident auto-resolves (default 15). |
| `OCC_NOTIFY_SETTLE` | Seconds an incident must be quiet before it is announced (default 3). |
| `OCC_KEEP_STATE=1` | Keep incidents across restarts (default: start clean). |
| `OCC_DB` | Path of the SQLite file. |

## Connect a real monitoring tool

Send alerts to `POST /api/alerts` as JSON (one object or a list):

```json
{"node_id": "HUB-N", "type": "LINK_DOWN", "message": "uplink down"}
```

Types: `LINK_DOWN`, `POWER_FAILURE`, `NODE_UNREACHABLE`, `HIGH_LATENCY`, `PACKET_LOSS`, and `CLEARED` to report recovery. `node_id` must match a node in the topology (`seed.py` defines the sample one; replace it with your real nodes and customers). Interactive API docs are at http://localhost:8000/docs.

## Project layout

```
backend/
  app/correlation.py   correlation engine, impact, severity, notifications
  app/topology.py      tree with backup uplinks, status propagation
  app/simulator.py     fault scenarios with ground truth
  app/main.py          REST API, WebSocket, background loops
  app/statusdraft.py   customer update, technical summary, runbooks
  app/llm.py           optional AI rewrite   app/notifier.py  optional email
  app/seed.py          sample network and customers
  tests/               24 tests            evaluate.py   accuracy report
frontend/              React + Leaflet dashboard (built copy in dist/)
```

Run the tests with `cd backend && python -m pytest`.

## Known limits

- The topology is a tree with single backup uplinks. Meshed networks would need a graph model.
- The sample network and customers are generated, not real.
- The AI rewrite and email paths are implemented but were not run against live services during development.
- `start.bat` was written but not run on Windows.
