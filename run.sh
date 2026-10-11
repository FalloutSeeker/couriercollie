#!/bin/sh
# Start couriercollie from this folder.
cd "$(dirname "$0")" && exec python3 -m couriercollie "$@"
