# Triage evaluation

## Development tickets (60)

| Mode | Category | Article | Article in top 3 | Linking | Incident linked | Escalation | Drafts failing guards |
|---|---|---|---|---|---|---|---|
| bm25 | 73.3% | 73.3% | 98.3% | 100.0% | 90.9% (33) | 80.0% | 2 |
| rules | 100.0% | 100.0% | 100.0% | 100.0% | 90.9% (33) | 100.0% | 0 |

Not handled correctly by `bm25`: D-06 (expected tower_outage/KB-01/escalate, got poor_coverage/KB-06/reply), D-07 (expected tower_outage/KB-01/escalate, got weather_low_charge/KB-07/reply), D-14 (expected battery_fade/KB-02/escalate, got weather_low_charge/KB-07/reply), D-16 (expected firmware_bad/KB-03/escalate, got weather_low_charge/KB-07/reply), D-17 (expected firmware_bad/KB-03/escalate, got gps_drift/KB-05/escalate), D-18 (expected firmware_bad/KB-03/escalate, got weather_low_charge/KB-07/reply), D-22 (expected water_ingress/KB-04/escalate, got tower_outage/KB-01/escalate), D-24 (expected water_ingress/KB-04/escalate, got tower_outage/KB-01/escalate), D-25 (expected water_ingress/KB-04/escalate, got tower_outage/KB-01/escalate), D-27 (expected water_ingress/KB-04/escalate, got collar_fit/KB-08/reply), D-33 (expected gps_drift/KB-05/escalate, got firmware_bad/KB-03/escalate), D-39 (expected weather_low_charge/KB-07/reply, got firmware_bad/KB-03/escalate), D-40 (expected weather_low_charge/KB-07/reply, got alert_settings/KB-12/reply), D-43 (expected weather_low_charge/KB-07/reply, got battery_fade/KB-02/escalate), D-47 (expected collar_fit/KB-08/escalate, got collar_fit/KB-08/reply), D-49 (expected account_access/KB-09/reply, got setup_howto/KB-11/reply), D-50 (expected account_access/KB-09/escalate, got account_access/KB-09/reply), D-53 (expected billing/KB-10/escalate, got billing/KB-10/reply), D-54 (expected billing/KB-10/escalate, got billing/KB-10/reply), D-55 (expected setup_howto/KB-11/reply, got account_access/KB-09/reply)

## Held-out tickets (never tuned on) (15)

| Mode | Category | Article | Article in top 3 | Linking | Incident linked | Escalation | Drafts failing guards |
|---|---|---|---|---|---|---|---|
| bm25 | 93.3% | 93.3% | 100.0% | 100.0% | 100.0% (8) | 93.3% | 0 |
| rules | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% (8) | 100.0% | 0 |

Not handled correctly by `bm25`: H-07 (expected water_ingress/KB-04/escalate, got tower_outage/KB-01/escalate), H-13 (expected billing/KB-10/escalate, got billing/KB-10/reply)
