#!/bin/sh
# Start RepoProject from this folder.
cd "$(dirname "$0")" && exec python3 -m repoproject "$@"
