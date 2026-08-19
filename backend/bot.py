"""Bot Telegram interactif — menu, création et gestion des alertes.

Deux couches :
  * `traiter_update(conn, update, rate)` DÉCIDE : il lit la base et renvoie une liste
    d'actions, sans jamais appeler le réseau → testable intégralement (tests/test_bot_dispatch.py).
  * la boucle `run()` EXÉCUTE : long polling getUpdates puis envoi des actions.

Ce découpage rend un passage en webhook possible sans réécriture : un endpoint FastAPI
n'aurait qu'à appeler `traiter_update` puis `executer`.

RÈGLE DURE : le bot est PUBLIC. Aucun prix détaxé, aucune donnée EveryWatch, aucune
marge (voir docs/specs/2026-08-17-bot-telegram-interactif.md).

Lancer :  python -m backend.bot
"""
import sys
import time

from . import bot_ui, config, db

MSG_ACCES = "Cette alerte n'existe pas ou n'est pas la tienne."
POLL_TIMEOUT = 25          # long polling : secondes d'attente côté Telegram
PAUSE_ERREUR = 5           # pause avant de réessayer après une erreur réseau
LONGUEUR_MAX_SAISIE = 200  # mots-clés/libellé : une saisie utilisateur (jusqu'à 4096
                           # caractères côté Telegram) est tronquée avant stockage,
                           # pour ne pas faire déborder les écrans qui l'affichent.


def _tronquer(texte: str) -> str:
    return texte[:LONGUEUR_MAX_SAISIE]


INT64_MAX = 9223372036854775807   # borne haute d'un entier signé 64 bits (SQLite/PG)


def _int_ou_none(s):
    """int(s) sûr et BORNÉ : None si `s` n'est pas un entier, ou si c'est un entier
    hors de la plage plausible pour un identifiant (clé primaire auto-incrémentée)
    ou un numéro de page — strictement positif, tenant dans un entier signé 64 bits.
    Un `callback_data` est une donnée entièrement contrôlée par le client (bot
    PUBLIC) : Python autorise les entiers à précision arbitraire, donc `int(s)` seul
    ne suffit pas — un « a:99999999999999999999999999 » réussirait le parsing puis
    ferait lever un OverflowError côté driver SQLite au moment de la requête. La
    validation de plage doit donc vivre ICI, en un seul endroit, plutôt que dispersée
    en try/except autour de chaque appel base."""
    try:
        n = int(s)
    except (TypeError, ValueError):
        return None
    if n <= 0 or n > INT64_MAX:
        return None
    return n


# --- actions (structures inertes ; l'exécution réseau est plus bas) ---
def _send(chat_id, ecran) -> dict:
    return {"type": "send", "chat_id": chat_id, "text": ecran["text"],
            "keyboard": ecran["keyboard"]}


def _edit(chat_id, message_id, ecran) -> dict:
    return {"type": "edit", "chat_id": chat_id, "message_id": message_id,
            "text": ecran["text"], "keyboard": ecran["keyboard"]}


def _answer(callback_id, text="") -> dict:
    return {"type": "answer", "callback_id": callback_id, "text": text}


# --- écrans qui ont besoin de la base ---
def _accueil(conn, uid, chat_id, message_id=None):
    nb = len(db.list_cibles(conn, telegram_id=uid))
    ecran = bot_ui.ecran_accueil(nb)
    return [_edit(chat_id, message_id, ecran) if message_id
            else _send(chat_id, ecran)]


def _liste_alertes(conn, uid, chat_id, message_id=None):
    alertes = []
    for c in db.list_cibles(conn, telegram_id=uid):
        d = dict(c)
        d["nb"] = len(db.matches_pour_cible(conn, d["id"]))
        alertes.append(d)
    ecran = bot_ui.ecran_alertes(alertes)
    return [_edit(chat_id, message_id, ecran) if message_id
            else _send(chat_id, ecran)]


def _fiche_alerte(conn, uid, chat_id, cible_id, message_id=None):
    cible = db.get_cible(conn, cible_id, telegram_id=uid)
    if not cible:
        return [_send(chat_id, {"text": MSG_ACCES, "keyboard": []})]
    montres = bot_ui.preparer_montres(db.matches_pour_cible(conn, cible_id), 1.0)
    nb_refs = len(bot_ui.grouper_par_reference(montres))
    ecran = bot_ui.ecran_alerte(dict(cible), len(montres), nb_refs)
    return [_edit(chat_id, message_id, ecran) if message_id
            else _send(chat_id, ecran)]


def _voir_montres(conn, uid, chat_id, cible_id, page, rate):
    cible = db.get_cible(conn, cible_id, telegram_id=uid)
    if not cible:
        return [_send(chat_id, {"text": MSG_ACCES, "keyboard": []})]
    montres = bot_ui.preparer_montres(db.matches_pour_cible(conn, cible_id), rate)
    if not montres:
        return [_send(chat_id, bot_ui.ecran_alerte_vide(dict(cible)))]
    p = bot_ui.page_montres(dict(cible), montres, page)
    actions = [{"type": "send", "chat_id": chat_id, "text": p["entete"],
                "keyboard": []}]
    for bloc in p["blocs"]:
        if bloc["photo"]:
            actions.append({"type": "photo", "chat_id": chat_id,
                            "photo": bloc["photo"], "caption": bloc["caption"],
                            "keyboard": []})
        else:      # pas d'image en base → on envoie le bloc en texte
            actions.append({"type": "send", "chat_id": chat_id,
                            "text": bloc["caption"], "keyboard": []})
    actions.append({"type": "send", "chat_id": chat_id,
                    "text": f"Page {p['page']}/{p['pages']}",
                    "keyboard": p["keyboard"]})
    return actions


# --- dispatch ---
def _traiter_texte(conn, uid, chat_id, texte):
    """Message texte : réponse à une question en cours, sinon retour à l'accueil."""
    etat = db.get_bot_etape(conn, uid)
    if not etat:
        return _accueil(conn, uid, chat_id)
    etape, data = etat
    valeur = (texte or "").strip()

    if etape == "attente_mots_cles":
        if not valeur:
            return [_send(chat_id, bot_ui.ecran_demande_mots_cles())]
        cid = db.add_cible(conn, _tronquer(valeur), "", telegram_id=uid)
        db.clear_bot_etape(conn, uid)
        return _fiche_alerte(conn, uid, chat_id, cid)

    cible_id = data.get("cible_id")
    cible = db.get_cible(conn, cible_id, telegram_id=uid) if cible_id else None
    if not cible:
        db.clear_bot_etape(conn, uid)
        return [_send(chat_id, {"text": MSG_ACCES, "keyboard": []})]

    if etape == "attente_libelle":
        if not valeur:
            return [_send(chat_id, bot_ui.ecran_demande_libelle(dict(cible)))]
        db.update_cible(conn, cible_id, libelle=_tronquer(valeur), telegram_id=uid)
    elif etape == "attente_kw":
        if not valeur:
            return [_send(chat_id, bot_ui.ecran_demande_kw(dict(cible)))]
        db.update_cible(conn, cible_id, mots_cles=_tronquer(valeur), telegram_id=uid)
    db.clear_bot_etape(conn, uid)
    return _fiche_alerte(conn, uid, chat_id, cible_id)


def _traiter_callback(conn, uid, chat_id, message_id, data, rate):
    if data == "home":
        return _accueil(conn, uid, chat_id, message_id)
    if data == "list":
        return _liste_alertes(conn, uid, chat_id, message_id)
    if data == "help":
        return [_edit(chat_id, message_id, bot_ui.ecran_aide())]
    if data == "new":
        db.set_bot_etape(conn, uid, "attente_mots_cles")
        return [_edit(chat_id, message_id, bot_ui.ecran_demande_mots_cles())]

    bouts = data.split(":")
    if bouts[0] == "v" and len(bouts) == 3:
        cible_id, page = _int_ou_none(bouts[1]), _int_ou_none(bouts[2])
        if cible_id is None or page is None:
            return []
        return _voir_montres(conn, uid, chat_id, cible_id, page, rate)

    if bouts[0] == "a" and len(bouts) >= 2:
        cible_id = _int_ou_none(bouts[1])
        if cible_id is None:
            return []
        action = bouts[2] if len(bouts) > 2 else ""
        cible = db.get_cible(conn, cible_id, telegram_id=uid)
        if not cible:
            return [_send(chat_id, {"text": MSG_ACCES, "keyboard": []})]
        if action == "":
            return _fiche_alerte(conn, uid, chat_id, cible_id, message_id)
        if action == "toggle":
            db.set_cible_actif(conn, cible_id, not cible["actif"], telegram_id=uid)
            return _fiche_alerte(conn, uid, chat_id, cible_id, message_id)
        if action == "del":
            return [_edit(chat_id, message_id,
                          bot_ui.ecran_confirm_suppression(dict(cible)))]
        if action == "del!":
            db.delete_cible(conn, cible_id, telegram_id=uid)
            return _liste_alertes(conn, uid, chat_id, message_id)
        if action == "ren":
            db.set_bot_etape(conn, uid, "attente_libelle", {"cible_id": cible_id})
            return [_edit(chat_id, message_id,
                          bot_ui.ecran_demande_libelle(dict(cible)))]
        if action == "kw":
            db.set_bot_etape(conn, uid, "attente_kw", {"cible_id": cible_id})
            return [_edit(chat_id, message_id, bot_ui.ecran_demande_kw(dict(cible)))]
    return []


def traiter_update(conn, update: dict, rate: float) -> list[dict]:
    """DÉCIDE quoi répondre à un update Telegram. Ne fait AUCUN envoi.
    Renvoie une liste d'actions (voir `executer`)."""
    cb = update.get("callback_query")
    msg = update.get("message")
    src = cb or msg
    if not src:
        return []
    expediteur = src.get("from") or {}
    uid = expediteur.get("id")
    chat_id = ((cb.get("message", {}) if cb else msg).get("chat", {}) or {}).get("id")
    if uid is None or chat_id is None:
        return []
    db.upsert_user(conn, uid, expediteur.get("first_name", "") or "",
                   expediteur.get("username", "") or "")

    if cb:
        actions = _traiter_callback(conn, uid, chat_id,
                                   cb.get("message", {}).get("message_id"),
                                   cb.get("data", "") or "", rate)
        return [_answer(cb.get("id"))] + actions

    texte = (msg.get("text") or "").strip()
    if texte.startswith("/aide") or texte.startswith("/help"):
        return [_send(chat_id, bot_ui.ecran_aide())]
    if texte.startswith("/start") or texte.startswith("/menu"):
        db.clear_bot_etape(conn, uid)
        return _accueil(conn, uid, chat_id)
    return _traiter_texte(conn, uid, chat_id, texte)
