"""table.py: a plan's step table as text: the header line with its columns, and each row's cells. plan.py and
masterplan.py read and write the table through it. A cell holds a literal `|` written `\\|`: a row with an
unescaped one has more cells than its header, and no cell of it is written by column number (`misfit`)."""
import re

REQUIRED = ("#", "step", "status")


def split_row(line: str) -> list[str]:
    """A table row's cells; `\\|` inside a cell is a literal `|`, not a column border."""
    cells = re.split(r"(?<!\\)\|", line.strip())
    if cells and not cells[0].strip():
        cells = cells[1:]
    if cells and not cells[-1].strip():
        cells = cells[:-1]
    return [cell.strip().replace("\\|", "|") for cell in cells]


def join_row(cells: list[str]) -> str:
    return "| " + " | ".join(cell.replace("|", "\\|") for cell in cells) + " |"


def header(lines: list[str]) -> tuple[int, dict[str, int]] | None:
    """Index of the step table's header line (the first table line with `#`, `Step` and `Status`) and its column
    positions by lower-case name; None without such a table."""
    for i, line in enumerate(lines):
        if line.lstrip().startswith("|"):
            cells = [c.lower() for c in split_row(line)]
            if all(name in cells for name in REQUIRED):
                return i, {name: cells.index(name) for name in cells}
    return None


def rows(lines: list[str], at: int) -> list[tuple[int, list[str]]]:
    """The rows below the header line `at` and its separator, as (line index, cells), up to the table's end."""
    found = []
    for i in range(at + 2, len(lines)):
        if not lines[i].lstrip().startswith("|"):
            break
        found.append((i, split_row(lines[i])))
    return found


def width(lines: list[str], at: int) -> int:
    """The cell count of the header line `at`, which every row written by column number must have."""
    return len(split_row(lines[at]))


def misfit(cells: list[str], width: int) -> str:
    """Why no cell of the row `cells` is written by column number under a header of `width` cells; "" when the row
    fits. An unescaped `|` (in a code span of the Step cell, say) shifts the cells: the write would land in another
    column."""
    if len(cells) == width:
        return ""
    return f"has {len(cells)} cells, its header {width}: write a `|` inside a cell as `\\|`"


def eol(line: str) -> str:
    """The `\\r` a line of a CRLF file keeps after `split("\\n")`: a rewritten or added line takes it over."""
    return "\r" if line.endswith("\r") else ""
