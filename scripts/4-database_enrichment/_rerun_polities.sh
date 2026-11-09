#!/bin/zsh
# Rerun the life-stage polities after a change to the export, then remove the fictional individuals: export, ingest, 08, 10, 11.
set -e
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PY="$ROOT/.venv/bin/python"
log() { echo "$(date +%H:%M:%S)  enrichment       $1" | tee -a "$ROOT/task.log"; }
cd "$ROOT/scripts/4-database_enrichment"
run() { log "$1 started"; start=$(date +%s); (cd "$(dirname "$1")" && "$PY" "$(basename "$1")") > "$ROOT/_logs/rerun_$(basename "$1" .py).log" 2>&1 || { log "$1 FAILED"; exit 1; }; log "$1 done in $(( ($(date +%s) - start) / 60 )) min"; }
run 02_notebooks_polity/01_life_stage_polities_export.py
run 02_notebooks_polity/ingest_life_stage_polities.py
run 08_seshat_id.py
run 10_coarse_dates.py
run 11_remove_fictional_individuals.py
log "polity rerun chain done"
