#!/bin/sh
# Start colliecourier from this folder.
cd "$(dirname "$0")" && exec python3 -m colliecourier "$@"
