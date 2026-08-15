"""Alertes Discord (webhook) : nouvelles CIBLES matchées et nouvelles
OPPORTUNITÉS ≥ seuil. Anti-doublon via la table `notified` (une alerte par uid
et par type). Sans DISCORD_WEBHOOK_URL dans .env → no-op silencieux.

Configurer : Discord → ton serveur → Modifier le salon → Intégrations →
Webhooks → copier l'URL → `DISCORD_WEBHOOK_URL=...` dans scrap-montres/.env
Tester :   python -m backend.notify --test
"""
import sys

import requests

from . import config, db

_SCHEMA = """
CREATE TABLE IF NOT EXISTS notified (
    uid   TEXT NOT NULL,
    type  TEXT NOT NULL,        -- 'cible' | 'opportunite'
    at    TEXT,
    PRIMARY KEY (uid, type)
);
"""


def _send(content: str, embeds: list | None = None) -> bool:
    if not config.DISCORD_WEBHOOK_URL:
        return False
    try:
        resp = requests.post(config.DISCORD_WEBHOOK_URL,
                             json={"content": content, "embeds": embeds or []},
                             timeout=15)
        return resp.status_code in (200, 204)
    except requests.RequestException:
        return False


def _embed(w: dict, titre: str, couleur: int, lignes: list[str]) -> dict:
    e = {
        "title": f"{titre} — {w.get('marque','')} {w.get('modele','')}"[:250],
        "url": w.get("url", ""),
        "color": couleur,
        "description": "\n".join(lignes),
    }
    imgs = w.get("images")
    if isinstance(imgs, list) and imgs:
        e["thumbnail"] = {"url": imgs[0]}
    return e


def _deja_notifie(conn, uid: str, typ: str) -> bool:
    conn.executescript(_SCHEMA)
    return conn.execute("SELECT 1 FROM notified WHERE uid=? AND type=?",
                        (uid, typ)).fetchone() is not None


def _marquer(conn, uid: str, typ: str):
    conn.execute("INSERT INTO notified (uid, type, at) VALUES (?,?,?) ON CONFLICT DO NOTHING",
                 (uid, typ, db.now_iso()))
    conn.commit()


def notifier_nouvelles_cibles(conn) -> int:
    """Alerte pour chaque montre cible (targets.json) dispo jamais notifiée."""
    if not config.DISCORD_WEBHOOK_URL:
        return 0
    conn.executescript(_SCHEMA)
    n = 0
    rows = conn.execute(
        "SELECT * FROM watches WHERE target_id IS NOT NULL AND status='dispo'")
    for w in ({**dict(r)} for r in rows):
        if _deja_notifie(conn, w["uid"], "cible"):
            continue
        lignes = [
            f"Réf **{w.get('reference','')}** · {w.get('boutique','')}",
            f"Prix Japon : ¥{int(w['prix_ttc']):,}" if w.get("prix_ttc") else "",
            f"Détaxé : **{w['prix_detaxe_eur']:.0f} €**" if w.get("prix_detaxe_eur") else "",
            f"Bénéf vs ta réf : **{w['benef_min']:+.0f} €**" if w.get("benef_min") is not None else "",
        ]
        if _send("🎯 **Nouvelle CIBLE en stock !**",
                 [_embed(w, "Cible", 0x2ecc71, [x for x in lignes if x])]):
            _marquer(conn, w["uid"], "cible")
            n += 1
    return n


def notifier_nouvelles_opportunites(conn) -> int:
    """Alerte pour chaque opportunité ≥ seuil jamais notifiée."""
    if not config.DISCORD_WEBHOOK_URL:
        return 0
    conn.executescript(_SCHEMA)
    n = 0
    for w in db.get_opportunities(conn, config.SPREAD_MIN_EUR,
                                  config.LIQUIDITY_MIN_LISTINGS):
        if _deja_notifie(conn, w["uid"], "opportunite"):
            continue
        lignes = [
            f"Réf **{w.get('reference','')}** · {w.get('boutique','')}",
            f"Détaxé JP : **{w['prix_detaxe_eur']:.0f} €** → Marché EU : "
            f"**{w['median_eur']:.0f} €** ({w['n_annonces']} annonces)",
            f"Spread brut : **+{w['spread_eur']:.0f} €** · "
            f"Marge nette import : **{w['marge_nette_eur']:+.0f} €**",
            f"Vente rapide (P25) : {w['spread_p25_eur']:+.0f} €"
            if w.get("spread_p25_eur") is not None else "",
        ]
        if _send("💰 **Nouvelle OPPORTUNITÉ !**",
                 [_embed(w, "Opportunité", 0xf1c40f, [x for x in lignes if x])]):
            _marquer(conn, w["uid"], "opportunite")
            n += 1
    return n


def notifier_tout() -> dict:
    """Point d'entrée appelé après collecte et après scan marché."""
    if not config.DISCORD_WEBHOOK_URL:
        return {"cibles": 0, "opportunites": 0}
    conn = db.connect()
    db.init_db(conn)
    res = {"cibles": notifier_nouvelles_cibles(conn),
           "opportunites": notifier_nouvelles_opportunites(conn)}
    conn.close()
    return res


def main():
    if "--test" in sys.argv:
        ok = _send("✅ Test : les alertes montres JP fonctionnent !")
        print("envoyé" if ok else
              "ÉCHEC — DISCORD_WEBHOOK_URL manquant dans .env ou webhook invalide")
        return
    print("RESULTAT notify", notifier_tout())


if __name__ == "__main__":
    main()
