#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

duckdb -ui data/humans_clean.duckdb
