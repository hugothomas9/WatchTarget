#!/usr/bin/env bash
# Enrichissement WatchCharts (liquidité = jours-pour-vendre + volatilité) des
# opportunités. Self-throttlé (cap 40/passe, délais DDG). REPRENABLE (TTL) : un
# re-run saute les réfs déjà fraîches. Garde-fou anti-double-run.
set -e
cd "$(dirname "$0")/.."

if pgrep -f "backend.market_scan --wc" >/dev/null 2>&1; then
  echo "$(date '+%F %T') wc_scan déjà en cours, on saute." >> data/logs_wc.txt
  exit 0
fi

PY="${SCRAP_PY:-/opt/anaconda3/bin/python3}"; [ -x "$PY" ] || PY=python3
echo "$(date '+%F %T') wc_scan démarré" >> data/logs_wc.txt
"$PY" -m backend.market_scan --wc >> data/logs_wc.txt 2>&1
echo "$(date '+%F %T') wc_scan terminé" >> data/logs_wc.txt
