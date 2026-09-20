#!/usr/bin/env bash
# herdr plugin build step: put herdr-acp in this plugin's own venv, check the Buzz binaries.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv
# --force-reinstall: pip treats an unchanged version from a git URL as already satisfied and keeps the old commit.
.venv/bin/pip install -q --force-reinstall "git+https://github.com/frankjoshua/herdr-acp" \
  || .venv/bin/pip install -q --force-reinstall "git+ssh://git@github.com/frankjoshua/herdr-acp"
.venv/bin/herdr-acp --help >/dev/null && echo "herdr-acp: ok (.venv)"
for b in buzz buzz-acp; do
  command -v "$b" >/dev/null && echo "$b: $(command -v "$b")" \
    || echo "$b: NOT FOUND — install Buzz Desktop (the .deb/.dmg ships buzz and buzz-acp) or set BUZZ_ACP"
done
echo "next: herdr plugin pane open --plugin herdr-buzz --entrypoint setup"
