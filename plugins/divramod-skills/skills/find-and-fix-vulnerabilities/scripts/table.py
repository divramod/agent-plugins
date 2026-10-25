"""The Markdown table of ranked rows: CVE | where | package | version | fixed | KEV | severity."""

HEAD = "| CVE | where | package | version | fixed | KEV | severity |"


def cell(text) -> str:
    return str(text if text not in (None, "") else "-").replace("|", "\\|").replace("\n", " ")


def where(targets: list, limit: int = 3) -> str:
    shown = ", ".join(targets[:limit])
    return shown + (f" +{len(targets) - limit}" if len(targets) > limit else "")


def kev_cell(row: dict) -> str:
    if not row["kev"]:
        return "-"
    return "KEV ransomware" if row["kev_ransomware"] else "KEV"


def counts(rows: list, hidden: int = 0) -> str:
    n = lambda pred: sum(1 for r in rows if pred(r))  # noqa: E731
    line = (f"{len(rows)} vulnerabilities, {n(lambda r: r['kev'])} KEV, "
            f"{n(lambda r: r['severity'] == 'CRITICAL')} critical, {n(lambda r: r['severity'] == 'HIGH')} high")
    return line + (f", {hidden} outdated packages hidden (--all)" if hidden else "")


def render(rows: list, errors: list = (), skipped: list = (), hidden: int = 0) -> str:
    out = [counts(rows, hidden), "", HEAD, "|---|---|---|---|---|---|---|"]
    for r in rows:
        out.append("| " + " | ".join(cell(x) for x in (r["id"], where(r["where"]), r["package"], r["version"],
                                                       r["fixed_version"], kev_cell(r), r["severity"])) + " |")
    if errors:
        out += ["", f"Errors ({len(errors)}):"] + [f"- {e['target']}: {e['message']}" for e in errors]
    if skipped:
        out += ["", f"Skipped ({len(skipped)}):"] + [f"- {s['target']}: {s['why']}" for s in skipped]
    return "\n".join(out)
