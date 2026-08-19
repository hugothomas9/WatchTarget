"""Envoi cadencé des notifs Telegram pour TOUTES les montres dispo matchant une cible
donnée (démo du backlog). Respecte les limites Telegram (pause entre envois + gestion
du 429 retry_after). Usage : python -m scripts.send_backlog_cible "<mots_cles>" ["libellé"]
"""
import sys, time
import requests
from backend import db, config, cibles, fx
from backend.telegram import _message, _api

def run(mots, libelle):
    conn = db.connect()
    rate = fx.get_rate()   # une fois pour tout le backlog, pas un appel par message
    # 1) créer l'alerte réelle (persistée pour la prod)
    existing = [c for c in db.list_cibles(conn) if c["mots_cles"] == mots]
    cid = existing[0]["id"] if existing else db.add_cible(conn, mots, libelle)
    # 2) purger le seed anti-spam de CETTE cible → on veut envoyer le backlog maintenant
    conn.execute("DELETE FROM notified WHERE type=?", (f"cible:{cid}",)); conn.commit()
    # 3) collecter les montres matchées
    matches = [dict(w) for w in conn.execute("SELECT * FROM watches WHERE status='dispo'")
               if cibles.matche(mots, cibles.blob_recherche(dict(w)))]
    print(f"cible id={cid} '{mots}' — {len(matches)} montre(s) à notifier", flush=True)
    sent = 0
    for i, w in enumerate(matches, 1):
        txt = _message(w, [libelle or mots], rate=rate)
        for attempt in range(3):
            r = requests.post(_api("sendMessage"),
                              data={"chat_id": config.TELEGRAM_CHAT_ID, "text": txt,
                                    "parse_mode": "HTML"}, timeout=20)
            if r.status_code == 429:
                wait = r.json().get("parameters", {}).get("retry_after", 3)
                time.sleep(wait + 1); continue
            break
        if r.ok and r.json().get("ok"):
            conn.execute("INSERT INTO notified (uid, type, at) VALUES (?,?,?) "
                         "ON CONFLICT DO NOTHING", (w["uid"], f"cible:{cid}", db.now_iso()))
            conn.commit(); sent += 1
        if i % 20 == 0:
            print(f"  ... {i}/{len(matches)} (envoyées={sent})", flush=True)
        time.sleep(1.1)   # ~1 msg/sec : sous la limite Telegram par chat
    print(f"TERMINE — {sent}/{len(matches)} notifs envoyées", flush=True)

if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "")
