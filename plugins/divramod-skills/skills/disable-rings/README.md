# disable-rings

Skill for plan 0606 (decision D12): `/disable-rings` sets the ring switch through `hal2-cli-ring mode --json`.

- `scripts/disable_rings.py`: the call table, the CLI call (`mode <ring|silent|off> [--for <d>] --from disable-rings --json`; `status` is `mode --json`), the one-line output.
- `scripts/test_disable_rings.py`: tests with a fake `hal2-cli-ring` on PATH; run `python3 -m unittest` in `scripts/`.
- `scripts/check-prerequisites.sh`, `install-prerequisites.sh`: python3 and `hal2-cli-ring`.

The switch itself (state file, expiry, the `ring` behaviour) belongs to `hal2-cli-ring`; see `hal2-cli-ring help mode`.
