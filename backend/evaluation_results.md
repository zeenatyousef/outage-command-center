# Correlation engine evaluation

70 randomised runs (10 per scenario type), fresh database each run, virtual-time replay.

| Scenario | Runs | Raw alerts (avg) | Incidents (avg) | Noise reduction | Incident count correct | Root cause correct | Impact exact | Kind correct |
|---|---|---|---|---|---|---|---|---|
| fiber_cut | 10 | 19.6 | 2.0 | 90% | 100% | 100% | 100% | 100% |
| tower_power_failure | 10 | 5.0 | 1.0 | 80% | 100% | 100% | 100% | 100% |
| silent_hub_failure | 10 | 14.0 | 1.0 | 93% | 100% | 100% | 100% | 100% |
| latency_spike | 10 | 9.2 | 1.0 | 89% | 100% | 100% | 100% | 100% |
| flapping_link | 10 | 5.0 | 1.0 | 80% | 100% | 100% | 100% | 100% |
| cabinet_failure | 10 | 1.0 | 1.0 | 0% | 100% | 100% | 100% | 100% |
| double_incident | 10 | 9.8 | 2.0 | 80% | 100% | 100% | 100% | 100% |
| **All** | 70 | 9.1 | 1.3 | 86% | 100% | 100% | 100% | 100% |

Total: 636 raw alerts became 90 incidents.

How to read this: *incident count correct* means the number of incidents equals the number of real, independent faults injected (including one unrelated noise blip in `fiber_cut`). *Impact exact* means offline and degraded customer counts equal the figures computed directly from the topology for the true failure.

Limits: the scenarios come from the same topology model the engine uses, so this checks correlation logic, not accuracy on real-world monitoring data.
