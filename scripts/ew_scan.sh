#!/usr/bin/env bash
# Enrichissement EveryWatch (prix VENDUS réels) des opportunités + Rolex.
# REPRENABLE : chaque config est commitée en base dès qu'elle est pricée, et un
# re-run saute les configs déjà fraîches (TTL). Donc si la machine coupe en cours,
# le prochain lancement continue là où on s'est arrêté — rien à refaire à la main.
# Garde-fou anti-double-run (le run manuel OU un tir launchd précédent).
set -e
cd "$(dirname "$0")/.."

if pgrep -f "backend.market_scan --ew" >/dev/null 2>&1; then
  echo "$(date '+%F %T') ew_scan déjà en cours, on saute." >> data/logs_ew.txt
  exit 0
fi

echo "$(date '+%F %T') ew_scan démarré" >> data/logs_ew.txt
PY="${SCRAP_PY:-/opt/anaconda3/bin/python3}"; [ -x "$PY" ] || PY=python3
# lots BORNÉS (60/passage) : EveryWatch est lent/sensible sans proxy — 60 réfs/heure
# soutenables valent mieux que tout d'un coup (qui fait dégrader la session/rate-limit).
# La couverture se construit sur quelques heures ; le TTL évite de refaire l'acquis.
"$PY" -m backend.market_scan --ew --limit 60 >> data/logs_ew.txt 2>&1
echo "$(date '+%F %T') ew_scan terminé" >> data/logs_ew.txt
