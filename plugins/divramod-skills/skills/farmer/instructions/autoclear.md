# Woken for fix-autoclear (autoclear)

The tick continues stuck sessions with `clear-and-continue` and delegates one `/fix-autoclear <slot>` servant per
failure class itself; it wakes you for nothing of this duty today. A session whose autoclear the user switched
off (fix-autoclear's `autoclear_off`: a hand-written `gave_up` marker, a rearm no context reaches, an agent's
`autoclear_off`) is no failure: the tick never clears it or delegates it (plan 0011), and neither do you. Anything that does reach you: follow
[fix-autoclear](../../fix-autoclear/SKILL.md)'s section on the stuck session with its read-only evidence, and log
it (`python3 $S/mtm_scan.py record autoclear <slot> "<what>" --note "<why>"`).
