"""Pure ranking of the workqueue's numbers: a window against the window before it, and the bench's compare result."""

TOLERANCE = 0.25  # a mean wall/CPU per run, or a peak, past +25% is a finding
MIN_RUNS = 3  # a group with fewer runs in either window is too thin to compare
FLOOR_MS = 200  # and the mean must also rise by this much
FLOOR_BYTES = 64 * 1024 * 1024


def minus(total: dict, part: dict) -> dict:
    """The additive numbers of (since 2W) minus (since W): the window before."""
    return {k: max(0, total.get(k, 0) - part.get(k, 0))
            for k in ("runs", "not_ok", "wall_ms_total", "cpu_ms_total")}


def _mean(group: dict, key: str) -> float:
    return group[key] / group["runs"] if group.get("runs") else 0.0


def _by_key(groups: list) -> dict:
    return {g["key"]: g for g in groups}


def compare_groups(label: str, now: list, wide: list, tolerance: float = TOLERANCE) -> tuple[list, list]:
    """Findings (rose) and notes (skipped) for groups keyed by class or head; `wide` covers 2 windows."""
    findings, notes = [], []
    wide_by = _by_key(wide)
    for g in now:
        w = wide_by.get(g["key"])
        if w is None:
            continue
        before = minus(w, g)
        if g["runs"] < MIN_RUNS or before["runs"] < MIN_RUNS:
            continue
        for key, name in (("wall_ms_total", "wall"), ("cpu_ms_total", "CPU")):
            was, is_ = _mean(before, key), _mean(g, key)
            if was > 0 and is_ > was * (1 + tolerance) and is_ - was >= FLOOR_MS:
                findings.append({
                    "kind": "rose", "what": f"{label} {g['key']}: mean {name} per run", "was": round(was),
                    "is": round(is_), "unit": "ms", "pct": round((is_ / was - 1) * 100),
                    "runs": g["runs"], "weight": (is_ - was) * g["runs"]})
        peak_now, peak_wide = g.get("peak_bytes_max"), w.get("peak_bytes_max")
        if peak_now and peak_wide and peak_wide > peak_now:  # the earlier window held the wide maximum
            continue  # the window got smaller: nothing rose
        if peak_now and peak_wide == peak_now:
            notes.append(f"{label} {g['key']}: peak memory not comparable (the maximum of both windows is the same)")
    return findings, notes


def marks_findings(now: dict, wide: dict) -> list:
    out = []
    for key in ("hung", "orphan", "docker_stuck"):
        was = max(0, wide.get(key, 0) - now.get(key, 0))
        if now.get(key, 0) > was:
            out.append({"kind": "marks", "what": f"{key} runs", "was": was, "is": now.get(key, 0), "unit": "count",
                        "weight": (now.get(key, 0) - was) * 1e6})
    return out


def bench_findings(result: dict) -> list:
    """From `workqueue-bench compare --json`: every entry that is slower."""
    out = []
    for row in result.get("benchmarks", result.get("results", [])) or []:
        if row.get("slower") or row.get("status") == "slower":
            out.append({"kind": "bench", "what": f"benchmark {row.get('name', '?')}", "detail": row,
                        "weight": 5e5})
    return out


def rank(findings: list) -> list:
    return sorted(findings, key=lambda f: -f.get("weight", 0))
