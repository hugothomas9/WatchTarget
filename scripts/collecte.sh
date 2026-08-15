#!/usr/bin/env bash
# Lance une collecte. Usage : ./scripts/collecte.sh [--full|--incremental] [--only site1,site2]
# Garde-fou : refuse de tourner si une collecte est déjà en cours (cron + manuel).
set -e
cd "$(dirname "$0")/.."

if pgrep -f "backend.run|pipeline.run" >/dev/null 2>&1; then
  echo "$(date '+%F %T') collecte déjà en cours, on saute." >> data/logs_cron.txt
  exit 0
fi

mkdir -p data data/backups
# backup quotidien de la base (garde 7 jours) — assurance avant toute écriture
BK="data/backups/montres-$(date '+%F').db"
[ -f "$BK" ] || sqlite3 data/montres.db ".backup '$BK'" 2>/dev/null || true
ls -t data/backups/montres-*.db 2>/dev/null | tail -n +8 | xargs rm -f 2>/dev/null || true

echo "$(date '+%F %T') collecte $* démarrée" >> data/logs_cron.txt
PY="${SCRAP_PY:-/opt/anaconda3/bin/python3}"; [ -x "$PY" ] || PY=python3
"$PY" -m backend.run "$@" >> data/logs_cron.txt 2>&1
echo "$(date '+%F %T') collecte terminée" >> data/logs_cron.txt
