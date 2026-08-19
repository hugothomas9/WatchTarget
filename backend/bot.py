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
import json
import sys
import time

import requests

from . import bot_ui, config, db

MSG_ACCES = "Cette alerte n'existe pas ou n'est pas la tienne."
POLL_TIMEOUT = 25          # long polling : secondes d'attente côté Telegram
PAUSE_ERREUR = 5           # pause avant de réessayer après une erreur réseau
LONGUEUR_MAX_SAISIE = 200  # mots-clés/libellé : une saisie utilisateur (jusqu'à 4096
                           # caractères côté Telegram) est tronquée avant stockage,
                           # pour ne pas faire déborder les écrans qui l'affichent.
MAX_ALERTES_PAR_USER = 20  # bot PUBLIC, boucle mono-thread : sans plafond, un
                           # utilisateur peut créer des centaines d'alertes puis
                           # bloquer le bot pour tout le monde en ouvrant « Mes
                           # alertes » (voir _compter_matches). Même valeur que
                           # bot_ui.ALERTES_PAR_ECRAN pour rester cohérent.


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


def _compter_matches(conn, cibles) -> dict:
    """Nombre de montres DISPO par alerte, en UNE SEULE passe sur `watches`.

    NOTE (revue finale, point 3a) : la spec demandait cette fonction dans
    `backend/db.py` (aux côtés de `_watches_matchant`, qui fait déjà tout le
    travail de matching en une passe). Au moment de cette correction, `db.py`
    porte des modifications non commitées d'un autre chantier en cours — pour ne
    pas les toucher ni les mélanger aux miennes, cette fonction vit ici et
    s'appuie sur `db._watches_matchant` plutôt que d'être ajoutée à `db.py`.
    À rapatrier dans `db.py` une fois l'autre chantier committé.

    Avant : un appel à `db.matches_pour_cible` PAR alerte, chacun relisant tout
    `watches` et recalculant `blob_recherche` pour chaque montre — un utilisateur
    à 200 alertes bloquait le bot (mono-thread) ~45 s le temps d'ouvrir « Mes
    alertes ». Après : un seul balayage de `watches`, quel que soit le nombre
    d'alertes.
    """
    cibles = list(cibles)
    compte = {c["id"]: 0 for c in cibles}
    for _w, hits in db._watches_matchant(conn, cibles):
        for c in hits:
            compte[c["id"]] += 1
    return compte


def _liste_alertes(conn, uid, chat_id, message_id=None):
    cibles = db.list_cibles(conn, telegram_id=uid)
    comptes = _compter_matches(conn, cibles)
    alertes = []
    for c in cibles:
        d = dict(c)
        d["nb"] = comptes.get(d["id"], 0)
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
        if len(db.list_cibles(conn, telegram_id=uid)) >= MAX_ALERTES_PAR_USER:
            db.clear_bot_etape(conn, uid)
            return [_send(chat_id, bot_ui.ecran_max_alertes(MAX_ALERTES_PAR_USER))]
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
    chat = (cb.get("message", {}) if cb else msg).get("chat", {}) or {}
    chat_id = chat.get("id")
    if uid is None or chat_id is None:
        return []
    # RÈGLE DURE : le bot est PUBLIC. Un /start ou un callback_query en groupe est
    # livré au bot quel que soit le privacy mode ; sans ce filtre, le menu et les
    # écrans d'alerte (édités DANS le groupe) exposeraient les données privées de
    # qui appuie sur un bouton (uid du clic ≠ chat où éditer) à tout le groupe —
    # voir revue finale, point 1. On ignore silencieusement, sans toucher la base.
    if chat.get("type") != "private":
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


# --- exécution réseau -------------------------------------------------------
def _masquer(texte) -> str:
    """Masque le token Telegram dans un texte destiné aux logs. `telegram._api()`
    construit l'URL avec le token en clair (`.../bot<TOKEN>/<methode>`) ; les
    exceptions `requests` se stringifient généralement AVEC l'URL complète, donc
    logger une exception réseau brute ferait fuiter le token en production à
    chaque incident. À utiliser sur TOUT texte journalisé qui peut contenir
    une exception réseau ou une URL."""
    token = config.TELEGRAM_BOT_TOKEN
    texte = str(texte)
    if token:
        texte = texte.replace(token, "***")
    return texte


def _markup(keyboard):
    """Clavier inline → paramètre reply_markup (JSON)."""
    if not keyboard:
        return None
    return json.dumps({"inline_keyboard": keyboard})


def executer(action: dict) -> bool:
    """Exécute UNE action décidée par `traiter_update`. False si l'appel échoue."""
    from .telegram import _api
    typ = action.get("type")
    if typ == "send":
        methode, data = "sendMessage", {
            "chat_id": action["chat_id"], "text": action["text"],
            "parse_mode": "HTML", "disable_web_page_preview": "true"}
    elif typ == "photo":
        methode, data = "sendPhoto", {
            "chat_id": action["chat_id"], "photo": action["photo"],
            "caption": action["caption"], "parse_mode": "HTML"}
    elif typ == "edit":
        methode, data = "editMessageText", {
            "chat_id": action["chat_id"], "message_id": action["message_id"],
            "text": action["text"], "parse_mode": "HTML",
            "disable_web_page_preview": "true"}
    elif typ == "answer":
        methode, data = "answerCallbackQuery", {
            "callback_query_id": action["callback_id"],
            "text": action.get("text", "")}
    else:
        return False
    markup = _markup(action.get("keyboard"))
    if markup:
        data["reply_markup"] = markup
    try:
        r = requests.post(_api(methode), data=data, timeout=30)
        if r.status_code == 429:
            # Même convention que scripts/send_backlog_cible.py : Telegram limite
            # à ~1 message/s par chat, et « Voir les montres » en envoie 5
            # d'affilée. Sans repli, un 429 laissait la page affichée à moitié,
            # sans que l'utilisateur sache qu'il manque quelque chose (revue
            # finale, point 4). Un seul réessai : le bot est mono-thread, on ne
            # bloque pas tout le monde derrière un chat en particulier.
            wait = r.json().get("parameters", {}).get("retry_after", 3)
            time.sleep(wait + 1)
            r = requests.post(_api(methode), data=data, timeout=30)
        ok = bool(r.ok and r.json().get("ok"))
        if not ok:
            print(f"[bot] envoi KO ({typ}) : réponse non ok", flush=True)
        return ok
    except requests.RequestException as e:
        print(f"[bot] envoi KO ({typ}) : {_masquer(e)}", flush=True)
        return False


class Transport:
    """Accès réel à l'API Telegram (injectable pour les tests)."""

    def get_updates(self, offset):
        from .telegram import _api
        params = {"timeout": POLL_TIMEOUT}
        if offset is not None:
            params["offset"] = offset
        r = requests.get(_api("getUpdates"), params=params,
                         timeout=POLL_TIMEOUT + 10)
        r.raise_for_status()
        return r.json().get("result", []) or []

    def envoyer(self, action):
        return executer(action)


def boucle(conn, rate_getter, transport, max_tours=None) -> int:
    """Long polling : un tour = un getUpdates + exécution des actions décidées.

    `rate_getter` est appelé une fois par tour (un seul appel de change par lot).
    `max_tours=None` = tourner indéfiniment ; les tests passent un entier.
    Un update qui plante est journalisé et SAUTÉ : l'offset avance quand même,
    sinon le bot rejouerait éternellement le même update cassé.

    L'offset est persisté APRÈS CHAQUE update (pas une seule fois après tout le
    lot) : `getUpdates` peut renvoyer des dizaines d'updates par tour, et si le
    process est tué au milieu d'un lot, seul l'update en cours de traitement doit
    être rejoué au redémarrage — pas tout le lot déjà consommé (ce qui créerait
    des doublons, ex. `db.add_cible` n'a pas de clé d'idempotence).
    """
    tours, traites = 0, 0
    offset = db.get_bot_meta(conn, "offset")
    offset = int(offset) if offset else None
    while max_tours is None or tours < max_tours:
        tours += 1
        try:
            updates = transport.get_updates(offset)
        except Exception as e:                       # réseau : on réessaie
            print(f"[bot] getUpdates KO : {_masquer(e)}", flush=True)
            time.sleep(PAUSE_ERREUR)
            continue
        if not updates:
            continue
        rate = rate_getter()
        for up in updates:
            offset = max(offset or 0, up.get("update_id", 0) + 1)
            try:
                for action in traiter_update(conn, up, rate):
                    ok = transport.envoyer(action)
                    if not ok and action.get("type") == "edit":
                        # Telegram refuse d'éditer un message vieux de plus de 48 h
                        # (400) : sans repli, l'écran a juste l'air cassé (le
                        # spinner s'éteint, rien ne s'affiche) — on rejoue la même
                        # charge en nouveau message (revue finale, point 2).
                        transport.envoyer({"type": "send",
                                          "chat_id": action["chat_id"],
                                          "text": action["text"],
                                          "keyboard": action["keyboard"]})
                traites += 1
            except Exception as e:
                print(f"[bot] update {up.get('update_id')} ignoré : {_masquer(e)}",
                      flush=True)
            db.set_bot_meta(conn, "offset", str(offset))
    return traites


def main():
    if not config.TELEGRAM_BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN absent : rien à faire.")
        return 1
    from . import fx
    conn = db.connect()
    db.init_db(conn)
    print("[bot] démarré (long polling)", flush=True)
    try:
        boucle(conn, fx.get_rate, Transport())
    except KeyboardInterrupt:
        print("[bot] arrêt", flush=True)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
