"""Group the findings of an enriched report into fix steps: ordering (KEV first, then severity) and the step texts."""
import re
from dataclasses import dataclass, field

from findings import OS_ECOSYSTEMS, SEVERITIES, Finding

ONLY = {"farm": "farms", "image": "images", "vm": "images", "os": "os", "server": "servers"}
CELL = 200
MAX_STEPS = 40


@dataclass
class Item:
    f: Finding
    kev: bool = False
    kev_added: str = ""


@dataclass
class Fix:
    kind: str
    target: str
    title: str
    items: list = field(default_factory=list)
    mode: str = "bump"  # bump | mitigate | os | group | rebuild

    @property
    def kev(self) -> bool:
        return any(i.kev for i in self.items)

    @property
    def ids(self) -> list:
        return sorted({i.f.id for i in self.items})

    @property
    def severity(self) -> str:
        return min((i.f.severity for i in self.items), key=sev_rank)

    def sort_key(self) -> tuple:
        return (0 if self.kev else 1, sev_rank(self.severity), self.target, self.title)


def sev_rank(s: str) -> int:
    return SEVERITIES.index(s) if s in SEVERITIES else len(SEVERITIES)


def items_of(report: dict) -> list:
    """Items from the report JSON; the KEV fields come from the Finding when it has them, else from the raw dict."""
    out = []
    for d in report.get("findings", []):
        f = Finding.from_dict(d)
        kev = getattr(f, "kev", None)
        kev = d.get("kev", False) if kev is None else kev
        out.append(Item(f, bool(kev), str(getattr(f, "kev_added", None) or d.get("kev_added") or "")))
    return out


def vkey(v: str) -> tuple:
    return tuple(int(n) for n in re.findall(r"\d+", str(v))) or (0,)


def short(ids: list, n: int = 3) -> str:
    return ", ".join(ids[:n]) + (f" +{len(ids) - n}" if len(ids) > n else "")


def clip(text: str, n: int = CELL) -> str:
    text = text.replace("|", "/").replace("\n", " ")
    return text if len(text) <= n else text[: n - 1] + "…"


def kev_word(fix: Fix) -> str:
    return "yes" if fix.kev else "no"


def is_rebuild(item: Item) -> bool:
    """An OS package CVE of an image or VM with no fixed version: only a newer base image helps."""
    f = item.f
    return f.target_kind in ("image", "vm") and f.ecosystem.lower() in OS_ECOSYSTEMS and not f.fixed_version


def make_fix(kind: str, target: str, package: str, hasfix, items: list, level: int) -> Fix:
    if kind == "rebuild":
        fix = Fix("image", target, "", items, "rebuild")
        fix.title = clip(f"Rebuild {target} on a newer base ({len(fix.ids)} OS package CVEs without a fix: "
                         f"{short(fix.ids)}, KEV: {kev_word(fix)})")
        return fix
    if kind == "os":
        fix = Fix(kind, target, "", items, "os")
        fix.title = f"Install pending security updates on {target} ({short(fix.ids)}, KEV: {kev_word(fix)})"
    elif level == 0 and hasfix:
        vers = "/".join(sorted({i.f.version for i in items if i.f.version}, key=vkey)) or "?"
        fixed = max((str(i.f.fixed_version) for i in items), key=vkey)
        fix = Fix(kind, target, "", items, "bump")
        fix.title = f"Bump {package} in {target} from {vers} to {fixed} ({short(fix.ids)}, KEV: {kev_word(fix)})"
    elif level == 0:
        fix = Fix(kind, target, "", items, "mitigate")
        fix.title = f"Mitigate or remove {package} in {target} ({short(fix.ids)}): no fix yet" + \
            (", KEV: yes" if any(i.kev for i in items) else "")
    else:
        pk = sorted({i.f.package for i in items})
        where = target if level == 1 else f"{kind} targets"
        fix = Fix(kind, target if level == 1 else kind, "", items, "group")
        fix.title = f"Fix {len(pk)} packages in {where}: {short(pk, 6)} ({short(fix.ids)}, KEV: {kev_word(fix)})"
    fix.title = clip(fix.title)
    return fix


def group_key(item: Item, level: int) -> tuple:
    f = item.f
    if f.target_kind == "os":
        return ("os", f.target, "", None)
    if level == 0:
        return (f.target_kind, f.target, f.package, bool(f.fixed_version))
    return (f.target_kind, f.target if level == 1 else "", "", None)


def build_fixes(items: list, max_steps: int = MAX_STEPS) -> list:
    """Per (kind, target, package); more than max_steps steps: per target, then per kind. KEV first, then severity."""
    fixes = []
    rebuild = {}
    for it in items:
        if is_rebuild(it):
            rebuild.setdefault(it.f.target, []).append(it)
    items = [it for it in items if not is_rebuild(it)]
    rebuilds = [make_fix("rebuild", t, "", None, v, 0) for t, v in rebuild.items()]
    for level in (0, 1, 2):
        groups = {}
        for it in items:
            groups.setdefault(group_key(it, level), []).append(it)
        fixes = [make_fix(k[0], k[1], k[2], k[3], v, level) for k, v in groups.items()]
        if len(fixes) <= max_steps:
            break
    return sorted(fixes + rebuilds, key=Fix.sort_key)


def done_when(fix: Fix) -> str:
    only = ONLY.get(fix.kind, fix.kind)
    return clip(f"rescan `collect.py --only {only} --json` + `report.py` shows none of {short(fix.ids, 2)} on {fix.target or fix.kind}")
