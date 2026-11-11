"""What `inspect` reads about a repository's Docker build: per Dockerfile the ports, the final stage's user and what it
copies, the CI build contexts whose COPY sources are missing, and the images its compose files and CI name."""

from __future__ import annotations

import re
from pathlib import Path

EXPOSE = re.compile(r"^\s*EXPOSE\s+(\d+)", re.M | re.I)
STAGE = re.compile(r"^\s*FROM\s", re.M | re.I)
USER = re.compile(r"^\s*USER\s+(\S+)", re.M | re.I)
COPY = re.compile(r"^\s*COPY\s+(.+)$", re.M | re.I)
COMPOSE_IMAGE = re.compile(r"^\s*image:\s*[\"']?([^\s\"']+)", re.M)
BUILD_STEP = re.compile(r"build-push-action@\S+(.*?)(?=^\s*-\s+(?:name|uses):|\Z)", re.S | re.M)
CONTEXT, FILE = re.compile(r"^\s*context:\s*(\S+)", re.M), re.compile(r"^\s*file:\s*(\S+)", re.M)


def final_stage(text: str) -> str:
    """The part of a Dockerfile after its last FROM: what the image that runs is made of."""
    starts = [m.start() for m in STAGE.finditer(text)]
    return text[starts[-1]:] if starts else text


def _copies(stage: str) -> list[str]:
    return COPY.findall(stage)


def dockerfile_facts(text: str) -> dict:
    stage = final_stage(text)
    users = USER.findall(stage)
    return {"ports": [int(p) for p in EXPOSE.findall(text)], "user": users[-1] if users else None,
            "copies_node_modules": any("node_modules" in c for c in _copies(stage))}


def _local_sources(text: str) -> list[str]:
    """COPY sources read from the build context: no `--from` stage, no glob, no `.`."""
    sources: list[str] = []
    for line in COPY.findall(text):
        words = line.split()
        if any(w.startswith("--from") for w in words) or line.lstrip().startswith("["):
            continue
        words = [w for w in words if not w.startswith("--")]
        sources += [w for w in words[:-1] if w not in {".", "./"} and not any(c in w for c in "*?$")]
    return sources


def build_contexts(root: Path, workflows: list[str], read) -> list[dict]:
    """Each CI build-push step that names its context and Dockerfile, with the COPY sources missing from that context."""
    out = []
    for workflow in workflows:
        for step in BUILD_STEP.findall(read(root / workflow)):
            context, file = CONTEXT.search(step), FILE.search(step)
            if not context or not file or "$" in context[1] + file[1]:
                continue
            folder = (root / context[1]).resolve()
            missing = sorted(s for s in _local_sources(read(root / file[1]))
                             if not (folder / s.lstrip("/")).exists())
            out.append({"workflow": workflow, "context": context[1], "file": file[1], "missing": missing})
    return out


def image_refs(files: list[Path], root: Path, read) -> list[dict]:
    """Every `image:` of the repository's compose files, as written."""
    refs = []
    for f in files:
        if f.suffix in {".yml", ".yaml"} and "compose" in f.name:
            refs += [{"file": str(f.relative_to(root)), "image": i} for i in COMPOSE_IMAGE.findall(read(f))]
    return refs
