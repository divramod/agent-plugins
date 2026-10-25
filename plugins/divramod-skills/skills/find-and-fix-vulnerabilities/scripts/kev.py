"""CISA's Known Exploited Vulnerabilities feed: fetched, cached (12 h) and indexed by CVE id."""
import cache

URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"


def index(feed: dict) -> dict:
    """cveID -> {added, ransomware}."""
    out = {}
    for v in feed.get("vulnerabilities", []):
        cve = str(v.get("cveID", "")).upper()
        if cve:
            out[cve] = {"added": v.get("dateAdded"), "ransomware": v.get("knownRansomwareCampaignUse") == "Known"}
    return out


def load(offline=False, fetch=cache.http_get, directory=None, now=None) -> dict:
    path = (directory or cache.cache_dir()) / "kev.json"
    return index(cache.load(URL, path, offline=offline, fetch=fetch, now=now))


def lookup(idx: dict, finding):
    """The KEV entry of a finding: by its id, else by any CVE among its aliases."""
    for i in [finding.id, *finding.aliases]:
        hit = idx.get(str(i).upper())
        if hit:
            return hit
    return None
