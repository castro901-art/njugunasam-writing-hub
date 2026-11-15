#!/usr/bin/env bash
set -euo pipefail
root="$(git rev-parse --show-toplevel)"
cd "$root"
git config core.hooksPath .githooks
printf 'Installed writing-hub hooks for this clone. New or edited research/ and notes/ pages will receive SEO metadata and social cards at commit time.\n'
