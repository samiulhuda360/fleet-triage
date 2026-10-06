"""Detection evaluation against the planted ground truth.

Scored per (collar, failure) pair and per collar:

* **Recall** - share of failing collars that any incident (or baseline alert) covered after the failure began.
* **Typed** - share where the flag also named the right failure mode.
* **Time to detect** - median hours from the planted start to the first flag on that collar.
* **Precision** - share of flagged collars that really had a planted failure at the time of the flag.
* **False positives in the noisy group** - healthy collars on the hill farm with poor coverage that were flagged.
* **Alerts** - notifications that would reach a person: one per baseline alert, or one per incident opened or
  escalated.

Seed 7 is the development seed the thresholds were tuned on. Seed 2026 is held out and was never tuned on.
No model is called, so this runs in CI.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from ..detect.features import FleetFeatures
from ..detect.model import FAILURE_TYPES
from ..detect.pipeline import METHODS, DetectionResult, detect
from ..sim.fleet import Fleet
from ..sim.simulator import simulate

DEV_SEED = 7
HELDOUT_SEED = 2026
EARLY_TOLERANCE = 6  # a flag up to 6 h before the planted start still counts (window features overlap it)
LATE_TOLERANCE = 24


def score(fleet: Fleet, result: DetectionResult) -> dict:
    idx = fleet.device_index()
    flags = result.device_flags()
    for v in flags.values():
        v.sort()
    pairs: dict[str, list[tuple[int, int, int]]] = {t: [] for t in FAILURE_TYPES}
    windows: dict[int, list[tuple[int, int, str]]] = {}
    for e in fleet.events:
        if not e.is_failure:
            continue
        end = (e.end_hour if e.end_hour is not None else fleet.hours) + LATE_TOLERANCE
        for dev, s in zip(e.device_ids, e.device_start_hours, strict=True):
            d = idx[dev]
            pairs[e.type].append((d, s, end))
            windows.setdefault(d, []).append((s - EARLY_TOLERANCE, end, e.type))

    per_mode = {}
    for mode, items in pairs.items():
        detected, typed, ttd, typed_ttd = 0, 0, [], []
        for d, s, end in items:
            hits = [(h, t) for h, t in flags.get(d, []) if s - EARLY_TOLERANCE <= h <= end]
            if hits:
                detected += 1
                ttd.append(hits[0][0] - s)
            th = [h for h, t in hits if t == mode]
            if th:
                typed += 1
                typed_ttd.append(th[0] - s)
        n = len(items)
        per_mode[mode] = {
            "collars": n,
            "recall": round(detected / n, 3) if n else None,
            "typed_recall": round(typed / n, 3) if n else None,
            "missed": n - detected,
            "median_ttd_h": float(np.median(ttd)) if ttd else None,
            "median_typed_ttd_h": float(np.median(typed_ttd)) if typed_ttd else None,
        }

    noisy = {idx[d] for e in fleet.events if e.type == "noisy_healthy" for d in e.device_ids}
    tp_dev, fp_dev = set(), set()
    type_tp: dict[str, int] = {}
    type_all: dict[str, int] = {}
    for d, fl in flags.items():
        wins = windows.get(d, [])
        if any(lo <= h <= hi for h, _ in fl for lo, hi, _t in wins):
            tp_dev.add(d)
        else:
            fp_dev.add(d)
        for t in {t for _, t in fl}:
            type_all[t] = type_all.get(t, 0) + 1
            first = min(h for h, tt in fl if tt == t)
            if any(lo <= first <= hi and gt == t for lo, hi, gt in wins):
                type_tp[t] = type_tp.get(t, 0) + 1
    flagged = len(flags)
    for mode in FAILURE_TYPES:
        per_mode[mode]["precision"] = round(type_tp.get(mode, 0) / type_all[mode], 3) if type_all.get(mode) else None
    total_pairs = sum(len(v) for v in pairs.values())
    out = {
        "method": result.method,
        "seed": fleet.seed,
        "per_mode": per_mode,
        "collars_flagged": flagged,
        "precision": round(len(tp_dev) / flagged, 3) if flagged else None,
        "false_positive_collars": len(fp_dev),
        "noisy_group_flagged": len(fp_dev & noisy),
        "noisy_group_size": len(noisy),
        "recall_all": round(
            sum(per_mode[m]["collars"] - per_mode[m]["missed"] for m in FAILURE_TYPES) / total_pairs, 3
        ),
        "alerts": result.alerts,
        "incidents": len(result.incidents) if result.method != "threshold" else result.alerts,
    }
    out["tower_warnings"] = _tower_warnings(fleet, result)
    return out


def _tower_warnings(fleet: Fleet, result: DetectionResult) -> dict | None:
    """How often a 'tower power low' warning was followed by a real outage within 48 hours."""
    if result.method == "threshold":
        warned = {}
        for f in result.findings:
            if f.type == "tower_power_low" and f.tower_idx is not None:
                warned.setdefault(f.tower_idx, f.hour)
    else:
        warned = {}
        for inc in result.incidents:
            if any(e["rule"] == "R-TOWER-POWER" for e in inc.evidence):
                warned.setdefault(next(iter(inc.towers)), inc.opened_hour)
    outages = [
        (fleet.device_index() and next(t.idx for t in fleet.towers if t.id == e.tower_id), e.start_hour)
        for e in fleet.events
        if e.type == "tower_outage"
    ]
    came_true, lead = 0, []
    for j, h in warned.items():
        match = [s for tj, s in outages if tj == j and 0 <= s - h <= 48]
        if match:
            came_true += 1
            lead.append(match[0] - h)
    return {
        "towers_warned": len(warned),
        "followed_by_outage": came_true,
        "median_lead_h": float(np.median(lead)) if lead else None,
    }


def run(seeds: list[int], out_dir: Path | None) -> dict:
    report: dict = {"seeds": {}, "dev_seed": DEV_SEED, "heldout_seed": HELDOUT_SEED}
    for seed in seeds:
        fleet = simulate(seed)
        feats = FleetFeatures(fleet)
        report["seeds"][str(seed)] = {}
        for method in METHODS:
            t0 = time.perf_counter()
            res = detect(fleet, method, feats)
            s = score(fleet, res)
            s["runtime_s"] = round(time.perf_counter() - t0, 1)
            report["seeds"][str(seed)][method] = s
            print(
                f"seed {seed:>4} {method:<14} recall {s['recall_all']:.3f} precision {s['precision']:.3f} "
                f"FP collars {s['false_positive_collars']:>3} noisy FP {s['noisy_group_flagged']:>2} "
                f"alerts {s['alerts']:>5} ({s['runtime_s']} s)"
            )
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "detection.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        (out_dir / "detection.md").write_text(to_markdown(report), encoding="utf-8")
    return report


def _fmt(v, pct: bool = False) -> str:
    if v is None:
        return "-"
    return f"{v * 100:.1f}%" if pct else (f"{v:.0f}" if isinstance(v, float) else str(v))


def to_markdown(report: dict) -> str:
    lines = ["# Detection evaluation", ""]
    for seed, by_method in report["seeds"].items():
        role = "development seed (tuned on)" if int(seed) == report["dev_seed"] else "held-out seed (never tuned on)"
        lines += [f"## Seed {seed}: {role}", ""]
        lines += [
            "| Method | Recall | Precision | Collars flagged | False-positive collars | Noisy group flagged "
            "| Alerts to on-call |",
            "|---|---|---|---|---|---|---|",
        ]
        for m, s in by_method.items():
            lines.append(
                f"| {m} | {_fmt(s['recall_all'], True)} | {_fmt(s['precision'], True)} | {s['collars_flagged']} "
                f"| {s['false_positive_collars']} | {s['noisy_group_flagged']} of {s['noisy_group_size']} "
                f"| {s['alerts']} |"
            )
        lines += ["", "Per failure mode (recall / correctly typed / median hours to detect):", ""]
        lines += ["| Mode | Collars | " + " | ".join(by_method) + " |", "|---|---|" + "---|" * len(by_method)]
        for mode in FAILURE_TYPES:
            n = next(iter(by_method.values()))["per_mode"][mode]["collars"]
            cells = []
            for s in by_method.values():
                pm = s["per_mode"][mode]
                cells.append(
                    f"{_fmt(pm['recall'], True)} / {_fmt(pm['typed_recall'], True)} / {_fmt(pm['median_ttd_h'])} h"
                )
            lines.append(f"| {mode} | {n} | " + " | ".join(cells) + " |")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Score detection methods against planted failures")
    p.add_argument("--seeds", type=int, nargs="+", default=[DEV_SEED, HELDOUT_SEED])
    p.add_argument("--out", type=Path, default=Path("results"))
    p.add_argument("--no-write", action="store_true")
    a = p.parse_args(argv)
    run(a.seeds, None if a.no_write else a.out)


if __name__ == "__main__":
    main()
