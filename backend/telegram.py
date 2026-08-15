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


def envoyer(text: str, chat_id=None) -> bool:
    """Envoie un message. `chat_id` = destinataire (défaut : chat admin configuré).
    False si non configuré ou échec."""
    chat_id = chat_id or config.TELEGRAM_CHAT_ID
    if not (config.TELEGRAM_BOT_TOKEN and chat_id):
        return False
    try:
        r = requests.post(_api("sendMessage"),
                          data={"chat_id": chat_id, "text": text,
                                "parse_mode": "HTML",
                                "disable_web_page_preview": "false"},
                          timeout=15)
        return r.ok and r.json().get("ok", False)
    except requests.RequestException:
        return False


def _message(w: dict, libelles: list[str]) -> str:
    """Message d'alerte : montre + prix vendu EW + marge + lien."""
    marque = w.get("marque", "") or ""
    modele = (w.get("modele", "") or "")[:60]
    ref = w.get("reference", "") or ""
    prix_jp = w.get("prix_detaxe_eur")
    ew = w.get("ew_median_eur")
    spread = w.get("spread_eur")
    lignes = [f"🎯 <b>{marque} {modele}</b>",
              f"Réf {ref} · {w.get('boutique','')}"]
    if prix_jp:
        lignes.append(f"Prix détaxé JP : <b>{round(prix_jp):,} €</b>".replace(",", " "))
    if ew:
        s = f" · marge +{round(spread):,} €".replace(",", " ") if spread else ""
        lignes.append(f"Vendu réel EW : {round(ew):,} €".replace(",", " ") + s)
    if libelles:
        lignes.append("Cible : " + ", ".join(libelles))
    if w.get("url"):
        lignes.append(w["url"])
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
        from . import verify_dispo
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
                if envoyer(_message(w, [c["libelle"] or c["mots_cles"]]), chat_id=dest):
                    _marquer(conn, w["uid"], typ)
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
