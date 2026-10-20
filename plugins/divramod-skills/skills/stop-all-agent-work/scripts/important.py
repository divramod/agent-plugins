"""Work that breaks or leaves something half done when frozen or killed mid-way: quiet.py's apply asks first
(--yes)."""
import re

IMPORTANT = [
    (r"\b(rsync|ditto|scp)\b|\b(cp|mv)\b.*(/Volumes/|/media/)", "copies or moves data"),
    (r"\bgit\b.*\b(push|merge|rebase|commit)\b|merge-to-main|\bland\b", "git write or landing"),
    (r"\b(deploy|terraform|ansible-playbook|pulumi|kubectl (apply|delete)|helm (install|upgrade))\b",
     "deploys"),
    (r"\b(migrate|migration|psql|pg_dump|pg_restore|mysqldump|sqlite3)\b", "touches a database"),
    (r"\b(brew (install|upgrade|reinstall)|softwareupdate|installer|pkgutil|xcodes install)\b", "installs software"),
    (r"\b(notarytool|altool|docker push|tart push|twine upload|npm publish|cargo publish)\b", "uploads or publishes"),
    (r"\b(diskutil|hdiutil|asr|tmutil)\b", "disk or backup operation"),
]


def important(cmd: str) -> str:
    """Why stopping this process mid-way is risky, or ''."""
    for pattern, why in IMPORTANT:
        if re.search(pattern, cmd):
            return why
    return ""
