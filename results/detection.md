# Detection evaluation

## Seed 7: development seed (tuned on)

| Method | Recall | Precision | Collars flagged | False-positive collars | Noisy group flagged | Alerts to on-call |
|---|---|---|---|---|---|---|
| threshold | 72.2% | 78.7% | 395 | 84 | 72 of 72 | 1175 |
| rules | 100.0% | 100.0% | 431 | 0 | 0 of 72 | 47 |
| rules+anomaly | 100.0% | 99.8% | 432 | 1 | 1 of 72 | 79 |

Per failure mode (recall / correctly typed / median hours to detect):

| Mode | Collars | threshold | rules | rules+anomaly |
|---|---|---|---|---|
| tower_outage | 62 | 100.0% / 0.0% / 6 h | 100.0% / 100.0% / 3 h | 100.0% / 100.0% / 3 h |
| firmware_bad | 317 | 62.1% / 0.0% / 327 h | 100.0% / 100.0% / 16 h | 100.0% / 100.0% / 16 h |
| battery_fade | 25 | 100.0% / 100.0% / 219 h | 100.0% / 100.0% / 114 h | 100.0% / 100.0% / 102 h |
| water_ingress | 12 | 100.0% / 41.7% / 30 h | 100.0% / 100.0% / 6 h | 100.0% / 100.0% / 6 h |
| gps_drift | 15 | 100.0% / 100.0% / 114 h | 100.0% / 100.0% / 59 h | 100.0% / 100.0% / 34 h |

## Seed 2026: held-out seed (never tuned on)

| Method | Recall | Precision | Collars flagged | False-positive collars | Noisy group flagged | Alerts to on-call |
|---|---|---|---|---|---|---|
| threshold | 65.0% | 78.6% | 345 | 74 | 56 of 56 | 988 |
| rules | 100.0% | 99.8% | 418 | 1 | 0 of 56 | 52 |
| rules+anomaly | 100.0% | 99.8% | 418 | 1 | 0 of 56 | 79 |

Per failure mode (recall / correctly typed / median hours to detect):

| Mode | Collars | threshold | rules | rules+anomaly |
|---|---|---|---|---|
| tower_outage | 63 | 100.0% / 0.0% / 6 h | 100.0% / 100.0% / 3 h | 100.0% / 100.0% / 3 h |
| firmware_bad | 302 | 51.7% / 0.0% / 294 h | 100.0% / 100.0% / 17 h | 100.0% / 100.0% / 17 h |
| battery_fade | 25 | 100.0% / 100.0% / 212 h | 100.0% / 100.0% / 116 h | 100.0% / 100.0% / 104 h |
| water_ingress | 12 | 100.0% / 66.7% / 28 h | 100.0% / 100.0% / 6 h | 100.0% / 100.0% / 6 h |
| gps_drift | 15 | 100.0% / 100.0% / 116 h | 100.0% / 100.0% / 59 h | 100.0% / 100.0% / 34 h |
