#!/usr/bin/env bash
# Re-vérification COMPLÈTE des statuts (dispo/vendue/retirée) sur toutes les boutiques.
# Lancé par launchd → indépendant du terminal. Journal : data/reverify.log
set -u
cd "$(dirname "$0")/.."
PY="${SCRAP_PY:-/opt/anaconda3/bin/python3}"; [ -x "$PY" ] || PY=python3
echo "$(date '+%F %T') === RE-VERIFY --all DÉMARRÉ ===" >> data/reverify.log
"$PY" -m backend.verify_dispo --all >> data/reverify.log 2>&1
echo "$(date '+%F %T') === RE-VERIFY TERMINÉ ===" >> data/reverify.log
