"""`ci-step`: the GitHub Actions steps a farm adds to its own pipeline (D15): publish the image, then `deploy
sha256:<digest>` over the site's forced key. Printed, never written into a repository."""

from __future__ import annotations

import re
from pathlib import Path

import hal2

SITE = re.compile(r"[a-z0-9-]+")
IMAGE = re.compile(r"[a-z0-9.-]+(:[0-9]+)?(/[a-z0-9._-]+)+")
PATH = re.compile(r"\.?[A-Za-z0-9_][A-Za-z0-9._/-]*|\.")
BUILD_ARG = re.compile(r"[A-Z][A-Z0-9_]*")
HOST = "hal9k.app"

TEMPLATE = """\
# The image's digest is the deploy's only argument; the forced key can do nothing else (design 4).
{key_note}
# Commit the server's pinned known_hosts as .github/hal9k_known_hosts (hal2: utils/deploy/hal9k/downloads/known_hosts).
# The job needs `permissions: packages: write` for the login below.
- name: Log in to the registry
  uses: docker/login-action@v3
  with:
    registry: {registry}
    username: ${{{{ github.actor }}}}
    password: ${{{{ secrets.GITHUB_TOKEN }}}}
- name: Publish the image
  id: push
  uses: docker/build-push-action@v6
  with:
    context: {context}
    file: {file}
    push: true
    tags: {image}:${{{{ github.sha }}}}
{build_args}- name: Deploy to the hal9k server
  env:
    {key_env}
    DIGEST: ${{{{ steps.push.outputs.digest }}}}
  run: |
    set -euo pipefail
    [[ "$DIGEST" =~ ^sha256:[0-9a-f]{{64}}$ ]]
{key_setup}
    # exit 0 deployed or unchanged; 1 kept the previous container, refused or failed; 3 no result in 10 minutes
    ssh -i "$key" -o StrictHostKeyChecking=yes -o UserKnownHostsFile=.github/hal9k_known_hosts \\
      hal9k-site-{site}@{host} "deploy $DIGEST"
"""


# A farm on the standard keeps one CI gpg key in GitHub and every other value in git secret (steueragenten plan 0760).
GIT_SECRET_NOTE = """\
# This farm is on the standard: the one GitHub secret is the CI gpg key HAL_CI_GPG_KEY; the private half of the key
# declared in the site's TOML is the git secret .secrets/HAL9K_DEPLOY_KEY_SEC. The job checks out the repository and has git-secret."""
GIT_SECRET_ENV = "HAL_CI_GPG_KEY: ${{ secrets.HAL_CI_GPG_KEY }}"
GIT_SECRET_SETUP = """\
    key=.secrets/HAL9K_DEPLOY_KEY_SEC; GNUPGHOME="$(mktemp -d)"; export GNUPGHOME
    trap 'rm -f "$key"; rm -rf "$GNUPGHOME"' EXIT
    printf '%s\\n' "$HAL_CI_GPG_KEY" | gpg --batch --import
    git secret reveal -f "$key"; chmod 600 "$key\""""
PLAIN_NOTE = """\
# OFF THE STANDARD: no .gitsecret/ and .secrets/ seen in this farm (pass --repo to look), so the deploy key is one more
# GitHub secret, HAL9K_DEPLOY_KEY: the private half of the key declared in the site's TOML. On the standard it is a git secret."""
PLAIN_ENV = "HAL9K_DEPLOY_KEY: ${{ secrets.HAL9K_DEPLOY_KEY }}"
PLAIN_SETUP = """\
    key="$(mktemp)"; trap 'rm -f "$key"' EXIT; chmod 600 "$key"; printf '%s\\n' "$HAL9K_DEPLOY_KEY" > "$key\""""


def on_git_secret(repo: Path | None) -> bool:
    """The standard's two folders; without a repository nothing is known, so the plain form says it did not look."""
    return repo is not None and (repo / ".gitsecret").is_dir() and (repo / ".secrets").is_dir()


def _check_image(image: str) -> None:
    """hal2's own rule when hal2 is here (`site_container.validate`); outside it only the shape this template needs."""
    if not IMAGE.fullmatch(image) or "@" in image:
        raise ValueError("the image is a lowercase repository with a registry host, no tag, no digest")
    try:
        root = hal2.find_root()
    except hal2.NoHal2:
        return
    _, site_container, shell = hal2.load_modules(root)
    try:
        site_container.validate("ci-step", {"image": image, "port": 3000, "health": "/", "memory": "1G"})
    except shell.Failed as err:
        raise ValueError(str(err)) from err


def render(site: str, image: str, context: str = ".", file: str = "Dockerfile", build_args: list[str] | None = None,
           repo: Path | None = None) -> str:
    if not SITE.fullmatch(site):
        raise ValueError("a site name is [a-z0-9-]+")
    _check_image(image)
    for path in (context, file):
        if not PATH.fullmatch(path):
            raise ValueError(f"{path!r} is not a plain relative path")
    names = build_args or []
    if not all(BUILD_ARG.fullmatch(n) for n in names):
        raise ValueError("a build argument is a name [A-Z][A-Z0-9_]*; CI reads its value from the repository's variables")
    lines = "".join(f"      {n}=${{{{ vars.{n} }}}}\n" for n in names)
    block = f"    build-args: |\n{lines}" if names else ""
    note, env, setup = (GIT_SECRET_NOTE, GIT_SECRET_ENV, GIT_SECRET_SETUP) if on_git_secret(repo) else (PLAIN_NOTE, PLAIN_ENV, PLAIN_SETUP)
    return TEMPLATE.format(site=site, image=image, host=HOST, registry=image.split("/")[0], context=context, file=file,
                           build_args=block, key_note=note, key_env=env, key_setup=setup)
