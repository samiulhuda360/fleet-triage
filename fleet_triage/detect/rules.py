"""Rules for the known failure modes in the knowledge base.

Each rule encodes how a fault-finder would confirm the failure: compare a collar with its own normal level,
with the rest of its farm at the same hour, or with its own firmware cohort before and after an update.
"""

from __future__ import annotations

import numpy as np

from ..sim.fleet import Fleet
from .features import FleetFeatures
from .model import CHECK_EVERY, FIRST_CHECK, Finding

# Thresholds, tuned on the development seed only.
FADE_NIGHT_DRAIN = 0.5  # %/h over the last 72 h
FADE_RATIO = 1.5  # times the collar's own earlier night drain
FW_SETTLE_HOURS = 7 * 24  # a firmware change this recent is left to the cohort check
INGRESS_TEMP_RESID = 3.0  # degC above the farm median, 6 h mean
INGRESS_SIGNAL_DROP = -4.0  # dB below the collar's own level, 6 h mean
DRIFT_HDOP = 2.8
DRIFT_HDOP_RISE = 1.0
OFFLINE_HOURS = 8
TOWER_SILENT_SHARE = 0.6
TOWER_SILENT_HOURS = 2
TOWER_BATTERY_LOW = 15.0
FW_MIN_DEVICES = 15
FW_MIN_POST_HOURS = 24
FW_DRAIN_DELTA = 0.08
FW_FIX_DELTA = -0.06
FW_WORSE_SHARE = 0.65


def run_rules(fleet: Fleet, feats: FleetFeatures | None = None) -> list[Finding]:
    feats = feats or FleetFeatures(fleet)
    out: list[Finding] = []
    n = fleet.n_devices
    dev_tower = fleet.device_tower
    tower_size = np.bincount(dev_tower, minlength=len(fleet.towers))
    fw = fleet.firmware
    # hour of the most recent firmware change for each collar at each hour
    changed = np.concatenate([np.zeros((n, 1), bool), fw[:, 1:] != fw[:, :-1]], axis=1)
    last_change = np.maximum.accumulate(np.where(changed, np.arange(fleet.hours)[None, :], -10_000), axis=1)

    for t in range(FIRST_CHECK, fleet.hours + 1, CHECK_EVERY):
        silent = feats.hours_silent(t)

        # --- towers: heartbeat lost, or most of a tower's collars silent at once -----------------
        down_towers: set[int] = set()
        for j in range(len(fleet.towers)):
            members = np.where(dev_tower == j)[0]
            # collars already silent for over a day are dead on their own; don't count them
            live = members[silent[members] < 24 + TOWER_SILENT_HOURS]
            quiet = live[silent[live] >= TOWER_SILENT_HOURS]
            hb_lost = (fleet.tower_online[j, max(0, t - TOWER_SILENT_HOURS) : t] == 0).all()
            share = len(quiet) / max(len(live), 1)
            if hb_lost or (len(live) >= 5 and share >= TOWER_SILENT_SHARE):
                down_towers.add(j)
                why = "tower heartbeat missing" if hb_lost else "tower heartbeat present"
                out.append(
                    Finding(
                        hour=t,
                        type="tower_outage",
                        source="rule",
                        rule="R-TOWER",
                        detail=f"{why}; {len(quiet)} of {tower_size[j]} collars silent >= {TOWER_SILENT_HOURS} h",
                        tower_idx=j,
                        device_idxs=[int(d) for d in quiet],
                        value=share,
                    )
                )
            else:
                tb = fleet.tower_battery[j, t - 6 : t]
                if np.isfinite(tb).all() and tb[-1] < TOWER_BATTERY_LOW and tb[-1] < tb[0]:
                    out.append(
                        Finding(
                            hour=t,
                            type="tower_power_low",
                            source="rule",
                            rule="R-TOWER-POWER",
                            detail=f"tower battery {tb[-1]:.0f} % and falling",
                            tower_idx=j,
                            value=float(tb[-1]),
                        )
                    )

        # --- single collars offline while their tower is fine ---------------------------------
        for d in np.where(silent >= OFFLINE_HOURS)[0]:
            if dev_tower[d] in down_towers:
                continue
            out.append(
                Finding(
                    hour=t,
                    type="device_offline",
                    source="rule",
                    rule="R-OFFLINE",
                    detail=f"no report for {int(silent[d])} h while tower {fleet.towers[dev_tower[d]].id} is up",
                    device_idx=int(d),
                    value=float(silent[d]),
                )
            )

        # --- battery fade: night drain high against the collar's own history --------------------
        drain72 = feats.r_drain.mean(t - 72, t, min_count=12)
        ref = feats.r_drain.mean(t - 240, t - 120, min_count=12)
        ref = np.where(np.isnan(ref), 0.28, ref)
        settled = (t - last_change[:, t - 1]) > FW_SETTLE_HOURS
        with np.errstate(invalid="ignore"):
            fade = (drain72 > FADE_NIGHT_DRAIN) & (drain72 > FADE_RATIO * ref) & settled
        for d in np.where(fade)[0]:
            out.append(
                Finding(
                    hour=t,
                    type="battery_fade",
                    source="rule",
                    rule="R-FADE",
                    detail=f"night drain {drain72[d]:.2f} %/h vs {ref[d]:.2f} %/h before",
                    device_idx=int(d),
                    value=float(drain72[d]),
                    feature="night_drain",
                )
            )

        # --- water ingress: hot against the farm and signal down against itself ----------------
        temp6 = feats.r_temp_resid.mean(t - 6, t, min_count=3)
        sig6 = feats.r_signal.mean(t - 6, t, min_count=3)
        sig_ref = feats.r_signal.mean(t - 168, t - 24, min_count=24)
        with np.errstate(invalid="ignore"):
            ingress = (temp6 > INGRESS_TEMP_RESID) & ((sig6 - sig_ref) < INGRESS_SIGNAL_DROP)
        for d in np.where(ingress)[0]:
            out.append(
                Finding(
                    hour=t,
                    type="water_ingress",
                    source="rule",
                    rule="R-INGRESS",
                    detail=f"temperature +{temp6[d]:.1f} C vs farm, signal {sig6[d] - sig_ref[d]:.1f} dB vs normal",
                    device_idx=int(d),
                    value=float(temp6[d]),
                    feature="temp_resid",
                )
            )

        # --- GPS drift: HDOP high and rising ----------------------------------------------------
        hdop24 = feats.r_hdop.mean(t - 24, t, min_count=6)
        hdop_ref = feats.r_hdop.mean(t - 168, t - 72, min_count=24)
        with np.errstate(invalid="ignore"):
            drift = (hdop24 > DRIFT_HDOP) & ((hdop24 - hdop_ref) > DRIFT_HDOP_RISE)
        for d in np.where(drift)[0]:
            out.append(
                Finding(
                    hour=t,
                    type="gps_drift",
                    source="rule",
                    rule="R-DRIFT",
                    detail=f"HDOP {hdop24[d]:.1f} vs {hdop_ref[d]:.1f} a few days ago",
                    device_idx=int(d),
                    value=float(hdop24[d]),
                    feature="hdop",
                )
            )

        out.extend(_firmware_cohorts(fleet, feats, t, last_change))
    return out


def _firmware_cohorts(fleet: Fleet, feats: FleetFeatures, t: int, last_change: np.ndarray) -> list[Finding]:
    """Paired before/after comparison for every firmware version that collars recently moved to."""
    out: list[Finding] = []
    cur = fleet.firmware[:, t - 1]
    upd = last_change[:, t - 1]
    for code in np.unique(cur):
        on_v = np.where(cur == code)[0]
        moved = on_v[(upd[on_v] >= 0) & (t - upd[on_v] >= FW_MIN_POST_HOURS)]
        if len(moved) < FW_MIN_DEVICES:
            continue
        u = upd[moved].astype(int)
        post0 = np.maximum(u, t - 72)
        tt = np.full_like(u, t)
        dd = feats.r_drain.mean_rows(moved, post0, tt, 8) - feats.r_drain.mean_rows(moved, u - 72, u, 8)
        df = feats.r_fix.mean_rows(moved, post0, tt, 12) - feats.r_fix.mean_rows(moved, u - 72, u, 12)
        d_drain, d_fix = dd[np.isfinite(dd)], df[np.isfinite(df)]
        if len(d_drain) < FW_MIN_DEVICES or len(d_fix) < FW_MIN_DEVICES:
            continue
        med_drain, med_fix = float(np.median(d_drain)), float(np.median(d_fix))
        worse_drain = float(np.mean(d_drain > FW_DRAIN_DELTA / 2))
        worse_fix = float(np.mean(d_fix < FW_FIX_DELTA / 2))
        bad_drain = med_drain > FW_DRAIN_DELTA and worse_drain >= FW_WORSE_SHARE
        bad_fix = med_fix < FW_FIX_DELTA and worse_fix >= FW_WORSE_SHARE
        if bad_drain or bad_fix:
            version = fleet.firmware_versions[int(code)]
            out.append(
                Finding(
                    hour=t,
                    type="firmware_bad",
                    source="cohort",
                    rule="R-FIRMWARE",
                    detail=(
                        f"{len(moved)} collars on {version}: night drain {med_drain:+.2f} %/h, "
                        f"GPS fix {med_fix * 100:+.0f} pts after update (median, paired)"
                    ),
                    device_idxs=[int(d) for d in on_v],
                    version=version,
                    value=med_drain,
                )
            )
    return out
