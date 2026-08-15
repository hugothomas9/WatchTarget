#!/usr/bin/env bash
# Chaîne de nuit : enchaîne les étapes UNE PAR UNE (jamais deux écritures SQLite en
# même temps → pas de « database is locked »). À lancer sous caffeinate pour que le
# Mac ne dorme pas. Chaque étape est indépendante : si l'une échoue, les suivantes
# tournent quand même. Journal unique : data/overnight.log
set -u
cd "$(dirname "$0")/.."
PY="${SCRAP_PY:-/opt/anaconda3/bin/python3}"; [ -x "$PY" ] || PY=python3
LOG=data/overnight.log
say() { echo "$(date '+%F %T') === $* ===" >> "$LOG"; }

say "CHAINE DE NUIT DEMARREE"

# 1) attendre la fin de la collecte full déjà en cours (le cas échéant)
if pgrep -f "backend.run --full" >/dev/null 2>&1; then
  say "attente fin de la collecte full en cours…"
  while pgrep -f "backend.run --full" >/dev/null 2>&1; do sleep 20; done
fi
say "collecte en cours terminée"

# 2) TRI DES VENDUES sur toute la base (statuts à jour au réveil)
say "TRI DES VENDUES (verify_dispo --all)"
"$PY" -m backend.verify_dispo --all >> "$LOG" 2>&1
say "tri des vendues terminé"

# 3) NOUVEAUX SITES : collecte MakeShop (King's Road + 7HOURS)
say "COLLECTE NOUVEAUX SITES (makeshop)"
"$PY" -m backend.run --full --only makeshop >> "$LOG" 2>&1
say "collecte makeshop terminée"

# 4) PRICING EVERYWATCH des arrivages (opportunités + marques 3-5k), en 3 passes
say "PRICING EVERYWATCH (arrivages)"
"$PY" -m backend.market_scan --ew --limit 60 >> "$LOG" 2>&1
for i in 1 2; do
  "$PY" -m backend.market_scan --ew --limit 80 --brands-only >> "$LOG" 2>&1
done
say "pricing everywatch terminé"

say "CHAINE DE NUIT TERMINEE — tout est prêt"
