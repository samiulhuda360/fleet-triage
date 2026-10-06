---
id: KB-03
title: Known issue - firmware 3.5.0 drains batteries and loses GPS fixes
category: firmware_bad
escalate: true
---
## Symptoms
- Several collars on the same farm losing battery faster than usual since a recent update.
- Positions missing or jumping, gaps in the tracks, animals showing in the last place for hours.
- Started within a day of the firmware update, across many collars at once.

## Cause
Firmware 3.5.0 keeps the GPS receiver in a high-power search mode after a failed fix. Batteries drain about 1.7
times faster and the GPS fix rate falls by around 17 points.

## What the data shows
- All affected collars are on version 3.5.0 and the change starts at each collar's update time.
- The same collars on their previous version had normal drain and fix rates.
- Collars on other versions on the same farms are unaffected.

## What to tell the farmer
This is a known software issue affecting a group of collars, not their farm or their animals. Engineering owns
the fix and support will pass on news when there is any. Do not promise a date.

## Escalation
Link the ticket to the open firmware incident rather than raising a new one.
