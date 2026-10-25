"""The one place a collector starts a program. Tests replace Runner with a fake that maps argv to canned output."""
import subprocess

NOT_FOUND = 127  # the program is not installed (also what a shell returns for a missing command)
TIMEOUT = 124


class Runner:
    """Runs argv (never a shell string) with a timeout; returns (rc, stdout, stderr)."""

    def run(self, argv: list, timeout: int = 120) -> tuple:
        try:
            p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
        except FileNotFoundError:
            return NOT_FOUND, "", f"{argv[0]}: not found"
        except subprocess.TimeoutExpired:
            return TIMEOUT, "", f"{argv[0]}: timed out after {timeout}s"
        except OSError as e:
            return 126, "", str(e)
        return p.returncode, p.stdout, p.stderr
