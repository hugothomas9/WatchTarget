"""Alertes Telegram : une montre nouvellement collectée qui matche une CIBLE
(mots-clés) déclenche un message au bot. Anti-doublon via la table `notified`
(clé type = « cible:<id> » → une alerte par montre et par cible).

Config .env : TELEGRAM_BOT_TOKEN (via @BotFather), TELEGRAM_CHAT_ID (via @userinfobot).
Sans token/chat_id → no-op silencieux. Tester : python -m backend.telegram --test
"""
import sys

import requests

from . import config, db
from .notify import _deja_notifie, _marquer, _SCHEMA


def _api(method: str) -> str:
    return f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/{method}"


BLOQUE = "bloque"   # sentinel renvoyé par `envoyer` sur un 403 (le destinataire a
                    # bloqué le bot) : échec DÉFINITIF, à distinguer de False (échec
                    # transitoire — réseau, 429, config absente — qu'il faut retenter
                    # au run suivant). BLOQUE est truthy comme True : les appelants
                    # existants qui font `if envoyer(...):` sans se soucier du cas
                    # bloqué continuent de fonctionner sans changement.


def envoyer(text: str, chat_id=None):
    """Envoie un message. `chat_id` = destinataire (défaut : chat admin configuré).
    Renvoie True si envoyé, False si échec transitoire (config manquante, réseau,
    erreur API hors 403), ou `BLOQUE` si Telegram répond 403 — le destinataire a
    bloqué le bot, un échec définitif qu'il ne faut jamais retenter (voir
    `notifier_cibles`, qui distingue les deux pour ne pas boucler indéfiniment sur
    un utilisateur public qui a bloqué le bot)."""
    chat_id = chat_id or config.TELEGRAM_CHAT_ID
    if not (config.TELEGRAM_BOT_TOKEN and chat_id):
        return False
    try:
        r = requests.post(_api("sendMessage"),
                          data={"chat_id": chat_id, "text": text,
                                "parse_mode": "HTML",
                                "disable_web_page_preview": "false"},
                          timeout=15)
        if r.status_code == 403:
            return BLOQUE
        return bool(r.ok and r.json().get("ok", False))
    except requests.RequestException:
        return False


def _message(w: dict, libelles: list[str], rate: float | None = None) -> str:
    """Message d'alerte, MÊME RENDU SOBRE que le bot : titre (marque modèle — réf),
    l'annonce, l'alerte déclenchée, le lien — quatre lignes distinctes (spec
    2026-08-17, §9 ; gabarit restauré en revue, round 1).

    Aucun prix détaxé, aucune donnée EveryWatch, aucune marge : les notifications
    partent à des utilisateurs publics.
    """
    from . import bot_ui
    if rate is None:
        from . import fx
        rate = fx.get_rate()
    m = bot_ui.preparer_montres([w], rate)[0]
    # bot_ui.titre_bloc() renvoie du texte NON échappé (l'échappement se fait au
    # point d'usage) ; le message part en parse_mode=HTML donc un < > ou & dans la
    # marque/le modèle casserait le message ou injecterait du balisage.
    # Ligne d'annonce SANS lien inline (URL neutralisée) : `bot_ui.ligne_annonce`
    # omet le « → <a>Voir</a> » quand `url` est vide — on ne touche pas à `bot_ui`,
    # le lien est ajouté ci-dessous en ligne nue, séparée (plus tappable/copiable).
    lignes = [f"🎯 <b>{bot_ui._esc(bot_ui.titre_bloc(m))}</b>",
              bot_ui.ligne_annonce({**m, "url": ""}).lstrip("• ")]
    if libelles:
        # `libelles` vient du texte libre saisi par l'utilisateur dans le bot
        # (`c["libelle"]`/`c["mots_cles"]`) : jamais échappé en amont, comme
        # partout ailleurs dans `bot_ui` où ce champ transite par `_esc`.
        lignes.append("Alerte : " + ", ".join(bot_ui._esc(l) for l in libelles))
    if m.get("url"):
        # Texte brut hors balise, mais le message part en parse_mode=HTML : Telegram
        # exige `<`, `>` et `&` échappés même hors balise (une query string avec `&`
        # ferait échouer sendMessage en silence — même défaut que sur le libellé).
        lignes.append(bot_ui._esc(m["url"]))
    return "\n".join(lignes)


def notifier_cibles(conn=None) -> int:
    """Pousse une alerte Telegram pour chaque montre matchant une cible et pas encore
    notifiée pour cette cible. Idempotent. Renvoie le nombre d'alertes envoyées."""
    close = conn is None
    conn = conn or db.connect()
    conn.executescript(_SCHEMA)
    from . import cibles as _cibles
    regles = db.list_cibles(conn, actives_only=True)
    n = 0
    if regles and config.TELEGRAM_BOT_TOKEN:
        from . import fx, verify_dispo
        rate = fx.get_rate()
        matches = db.get_cibles_matches(conn)
        for w in matches:
            blob = _cibles.blob_recherche(w)
            cibles_ok = [c for c in regles if _cibles.matche(c["mots_cles"], blob)
                         and not _deja_notifie(conn, w["uid"], f"cible:{c['id']}")]
            if not cibles_ok:
                continue
            # ANTI-LIEN-MORT : on confirme en direct que la montre est TOUJOURS dispo
            # avant d'alerter (elle a pu se vendre/être retirée depuis la collecte).
            st = verify_dispo.check(w["boutique"], w["url"])
            if st and st != "dispo":
                conn.execute("UPDATE watches SET status=?, last_seen=? WHERE uid=?",
                             (st, db.now_iso(), w["uid"]))
                conn.commit()
                continue                         # vendue/retirée → pas d'alerte
            for c in cibles_ok:
                typ = f"cible:{c['id']}"
                dest = c["telegram_id"] if "telegram_id" in c.keys() else None
                resultat = envoyer(
                    _message(w, [c["libelle"] or c["mots_cles"]], rate=rate),
                    chat_id=dest)
                if resultat:
                    # BLOQUE (403, définitif) est aussi marqué « notifié » pour ne
                    # pas retenter indéfiniment — mais pas compté comme un VRAI
                    # envoi (revue finale, point 5).
                    _marquer(conn, w["uid"], typ)
                    if resultat is True:
                        n += 1
    if close:
        conn.close()
    return n


def _message_baisse(w: dict, libelles: list[str], ancien_ttc: float,
                    nouveau_ttc: float, rate: float | None = None) -> str:
    """Message de BAISSE DE PRIX — TITRE DISTINCT (📉) pour le différencier d'une
    alerte d'arrivage. Même règle « rendu sobre » que _message : le prix BOUTIQUE
    (donnée publique de l'annonce) uniquement — jamais détaxé/EveryWatch/marge."""
    from . import bot_ui
    if rate is None:
        from . import fx
        rate = fx.get_rate()
    m = bot_ui.preparer_montres([w], rate)[0]
    pct = round(100 * (ancien_ttc - nouveau_ttc) / ancien_ttc)
    def fmt(v):
        return "¥" + f"{v:,.0f}".replace(",", " ")
    lignes = [f"📉 <b>Baisse de prix — {bot_ui._esc(bot_ui.titre_bloc(m))}</b>",
              f"{fmt(ancien_ttc)} → <b>{fmt(nouveau_ttc)}</b> (−{pct} %)"]
    if libelles:
        lignes.append("Alerte : " + ", ".join(bot_ui._esc(l) for l in libelles))
    if m.get("url"):
        lignes.append(bot_ui._esc(m["url"]))
    return "\n".join(lignes)


SEUIL_BAISSE = 0.01   # −1 % minimum : en deçà c'est un ajustement, pas une affaire


def notifier_baisses(conn=None, depuis: str = "") -> int:
    """Notifie les BAISSES DE PRIX : une montre DÉJÀ CONNUE (≥ 2 points
    d'historique) dont le prix boutique vient de baisser d'au moins 1 % — une
    ancienne offre redevenue attractive. Destinataires : propriétaires des
    alertes mots-clés qui matchent. Anti-doublon PAR PALIER de prix (une
    nouvelle baisse re-notifie ; le même palier, jamais deux fois). Détection
    sur prix_ttc (yen boutique) : insensible aux mouvements du change."""
    close = conn is None
    conn = conn or db.connect()
    conn.executescript(_SCHEMA)
    from . import cibles as _cibles
    regles = db.list_cibles(conn, actives_only=True)
    n = 0
    if regles and config.TELEGRAM_BOT_TOKEN and depuis:
        from . import fx
        rate = fx.get_rate()
        recents = [r[0] for r in conn.execute(
            "SELECT DISTINCT uid FROM price_history WHERE seen_at >= ?",
            (depuis,))]
        for uid in recents:
            pts = conn.execute(
                "SELECT prix_ttc FROM price_history WHERE uid=? "
                "ORDER BY seen_at DESC LIMIT 2", (uid,)).fetchall()
            if len(pts) < 2 or not pts[0]["prix_ttc"] or not pts[1]["prix_ttc"]:
                continue          # < 2 points = nouvel arrivage, pas une baisse
            nouveau, ancien = pts[0]["prix_ttc"], pts[1]["prix_ttc"]
            if nouveau >= ancien * (1 - SEUIL_BAISSE):
                continue          # hausse, ou variation sous le seuil
            w = conn.execute(
                "SELECT * FROM watches WHERE uid=? AND status='dispo'",
                (uid,)).fetchone()
            if not w:
                continue          # vendue/retirée entre-temps
            w = dict(w)
            blob = _cibles.blob_recherche(w)
            for c in regles:
                if not _cibles.matche(c["mots_cles"], blob):
                    continue
                typ = f"baisse:{c['id']}:{int(nouveau)}"
                if _deja_notifie(conn, uid, typ):
                    continue
                dest = c["telegram_id"] if "telegram_id" in c.keys() else None
                resultat = envoyer(
                    _message_baisse(w, [c["libelle"] or c["mots_cles"]],
                                    ancien, nouveau, rate=rate), chat_id=dest)
                if resultat:
                    _marquer(conn, uid, typ)
                    if resultat is True:
                        n += 1
    if close:
        conn.close()
    return n


def main():
    if "--test" in sys.argv:
        ok = envoyer("✅ Test WatchTarget — les alertes de cibles fonctionnent.")
        print("Envoyé." if ok else "Échec (TELEGRAM_BOT_TOKEN/CHAT_ID absent ou API KO).")
        return
    print("Alertes envoyées :", notifier_cibles())


if __name__ == "__main__":
    main()
