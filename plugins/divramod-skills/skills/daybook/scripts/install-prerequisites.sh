#!/usr/bin/env bash
# Install what check-prerequisites.sh found missing (python3, git) with Homebrew or apt-get.
set -e
for tool in python3 git; do
  command -v "$tool" >/dev/null 2>&1 && continue
  pkg=$tool; [ "$tool" = python3 ] && pkg=python
  if command -v brew >/dev/null 2>&1; then brew install "$pkg"
  elif command -v apt-get >/dev/null 2>&1; then sudo apt-get install -y "$tool"
  else echo "install $tool by hand"; exit 1; fi
done
