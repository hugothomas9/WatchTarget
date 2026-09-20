"""Déclare (ou retire) le webhook Telegram du bot.

Mode WEBHOOK (prod sur hébergement qui s'endort, ex. Render free) :

    TELEGRAM_BOT_TOKEN=... TELEGRAM_WEBHOOK_SECRET=... \
        python -m scripts.set_webhook https://mon-service.onrender.com

Retour au mode LONG POLLING (dev local, `python -m backend.bot`) :

    python -m scripts.set_webhook --delete

⚠️ Un seul mode à la fois : tant qu'un webhook est déclaré, `getUpdates` renvoie
une erreur 409. `--delete` est donc le préalable à tout retour au polling.
"""
import sys

import requests

from backend import config
from backend.telegram import _api

CHEMIN = "/api/telegram/webhook"


def _post(methode, data=None):
    r = requests.post(_api(methode), data=data or {}, timeout=30)
    rep = r.json()
    if not rep.get("ok"):
        # description Telegram : jamais le token (construit dans l'URL, pas ici)
        print(f"ÉCHEC {methode} : {rep.get('description')}")
        return False
    return True


def main(argv):
    if not config.TELEGRAM_BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN absent.")
        return 1
    if "--delete" in argv:
        # drop_pending_updates=false : les updates en attente seront servis au
        # prochain getUpdates, on ne perd pas les messages reçus entre-temps.
        ok = _post("deleteWebhook")
        print("webhook retiré (retour possible au long polling)" if ok else "")
        return 0 if ok else 1

    if not argv:
        print(__doc__)
        return 1
    base = argv[0].rstrip("/")
    if not base.startswith("https://"):
        # Telegram REFUSE un webhook en http : le token de session et les données
        # des updates passeraient en clair.
        print("L'URL doit être en https:// (exigence Telegram).")
        return 1
    secret = config.TELEGRAM_WEBHOOK_SECRET
    if not secret:
        print("TELEGRAM_WEBHOOK_SECRET absent : l'endpoint serait désactivé côté "
              "serveur (404). Génère-le avec `openssl rand -hex 32` et mets la "
              "MÊME valeur ici et dans les variables du service web.")
        return 1
    ok = _post("setWebhook", {
        "url": base + CHEMIN,
        "secret_token": secret,
        # on ne reçoit que ce dont le bot a besoin (pas les edited_message, etc.)
        "allowed_updates": '["message","callback_query"]',
        # updates accumulés pendant que le bot était éteint : on repart propre,
        # sinon le bot répond d'un coup à des messages vieux de plusieurs jours.
        "drop_pending_updates": "true",
    })
    if ok:
        print(f"webhook déclaré : {base}{CHEMIN}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
