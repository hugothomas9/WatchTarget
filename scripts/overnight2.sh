#!/usr/bin/env bash
# Étapes restantes de la nuit (le tri des vendues est déjà fait) :
#   MakeShop (King's Road + 7HOURS) → pricing EveryWatch des arrivages.
# Lancé par launchd (agent com.hugo.scrapmontres.overnight) → indépendant du terminal.
set -u
cd "$(dirname "$0")/.."
PY="${SCRAP_PY:-/opt/anaconda3/bin/python3}"; [ -x "$PY" ] || PY=python3
LOG=data/overnight.log
say() { echo "$(date '+%F %T') === $* ===" >> "$LOG"; }

say "AGENT LAUNCHD DEMARRE (makeshop + everywatch)"

# garde-fou : ne pas doubler si une collecte tourne déjà
while pgrep -f "backend.run" >/dev/null 2>&1; do sleep 20; done

say "COLLECTE NOUVEAUX SITES (makeshop)"
"$PY" -m backend.run --full --only makeshop >> "$LOG" 2>&1
say "collecte makeshop terminee"

say "PRICING EVERYWATCH (arrivages)"
"$PY" -m backend.market_scan --ew --limit 60 >> "$LOG" 2>&1
for i in 1 2; do
  "$PY" -m backend.market_scan --ew --limit 80 --brands-only >> "$LOG" 2>&1
done
say "pricing everywatch termine"

say "CHAINE DE NUIT TERMINEE — tout est pret"
