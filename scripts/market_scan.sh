#!/usr/bin/env bash
# Scan des prix marché (Chrono24/eBay) par réf. Usage : ./scripts/market_scan.sh [--limit N]
# Garde-fou anti-double-run.
set -e
cd "$(dirname "$0")/.."

if pgrep -f "backend.market_scan" | grep -v $$ | grep -qv grep 2>/dev/null; then
  echo "$(date '+%F %T') market_scan déjà en cours, on saute." >> data/logs_market.txt
  exit 0
fi

echo "$(date '+%F %T') market_scan $* démarré" >> data/logs_market.txt
PY="${SCRAP_PY:-/opt/anaconda3/bin/python3}"; [ -x "$PY" ] || PY=python3
"$PY" -m backend.market_scan "$@" >> data/logs_market.txt 2>&1
echo "$(date '+%F %T') market_scan terminé" >> data/logs_market.txt
