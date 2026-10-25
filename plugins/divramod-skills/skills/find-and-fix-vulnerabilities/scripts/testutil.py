"""Helpers of the tests: a fake Runner keyed by argv, and the fixtures of testdata/."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import collect_farms  # noqa: E402
import collect_images  # noqa: E402
import collect_os  # noqa: E402
import collect_servers  # noqa: E402


def data(name: str) -> str:
    return (HERE / "testdata" / name).read_text()


class FakeRunner:
    """Maps argv to (rc, stdout, stderr); a program it does not know is "not installed" (rc 127). Starts nothing."""

    def __init__(self, table: dict = None):
        self.table = {tuple(k): v for k, v in (table or {}).items()}
        self.calls = []

    def run(self, argv, timeout=120):
        self.calls.append(list(argv))
        return self.table.get(tuple(argv), (127, "", f"{argv[0]}: not found"))


def ok(out: str, rc: int = 0, err: str = "") -> tuple:
    return rc, out, err


def osv_argv(farm) -> tuple:
    return tuple(collect_farms.V2 + [str(farm)])


def osv_v1_argv(farm) -> tuple:
    return tuple(collect_farms.V1 + [str(farm)])


def ssh_argv(host: str, cmd: str) -> tuple:
    return tuple(collect_servers.SSH + [host, cmd])


def make_farm(root: Path, name: str, git_file: bool = False) -> Path:
    farm = root / name
    farm.mkdir(parents=True)
    if git_file:
        (farm / ".git").write_text("gitdir: elsewhere")
    else:
        (farm / ".git").mkdir()
    return farm


__all__ = ["FakeRunner", "ok", "data", "osv_argv", "osv_v1_argv", "ssh_argv", "make_farm", "collect_images", "collect_os"]
