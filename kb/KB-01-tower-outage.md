---
id: KB-01
title: Base tower offline, collars on it go quiet
category: tower_outage
escalate: true
---
## Symptoms
- Many collars on one farm stop reporting at the same time, often "half the herd" or "everything near the woolshed".
- The farm app shows animals frozen at their last known position.
- Often follows a storm or several grey days, because the tower runs on a solar panel and battery.

## Cause
A base tower relays collar messages to the network. If its battery runs flat (days of low sun, an aged battery)
or its backhaul radio faults, every collar it serves loses uplink. The collars keep working and resume reporting
as soon as the tower is back.

## What the data shows
- Tower heartbeat missing for two hours or more.
- Most collars on that tower silent at the same hour, while collars on the farm's other tower carry on.
- For a power outage: tower battery falling below 25 % before the heartbeat stops.

## What to tell the farmer
The collars are fine; the tower that relays them is offline. Reporting comes back once the tower recovers.
Positions shown in the app are stale until then.

## Escalation
Escalate to field operations with the tower id. A tower that does not recover after the next sunny morning needs
a site visit (battery or radio swap).
