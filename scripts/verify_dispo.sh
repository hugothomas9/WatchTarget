#!/usr/bin/env bash
# Vérifie la disponibilité réelle des montres 'dispo'. Usage : [--all|--older-than-days N]
set -e
cd "$(dirname "$0")/.."

if pgrep -f "backend.verify_dispo" | grep -v $$ | grep -qv grep 2>/dev/null; then
  echo "$(date '+%F %T') verify_dispo déjà en cours, on saute." >> data/logs_verify.txt
  exit 0
fi

echo "$(date '+%F %T') verify_dispo $* démarré" >> data/logs_verify.txt
PY="${SCRAP_PY:-/opt/anaconda3/bin/python3}"; [ -x "$PY" ] || PY=python3
"$PY" -m backend.verify_dispo "$@" >> data/logs_verify.txt 2>&1
echo "$(date '+%F %T') verify_dispo terminé" >> data/logs_verify.txt
