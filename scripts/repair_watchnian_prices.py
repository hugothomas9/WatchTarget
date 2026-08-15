"""Réparation reprenable des prix watchnian (régression sélecteur corrigée).

Ne retraite que les lignes watchnian SANS prix → reprend là où on s'est arrêté.
Lancer depuis la racine du projet : python -m scripts.repair_watchnian_prices
"""
from backend.connectors.watchnian import WatchnianConnector, BASE
from backend import db, pipeline, fx
from backend.targets import load_targets


def main():
    conn = db.connect()
    rows = conn.execute(
        "SELECT uid, url FROM watches "
        "WHERE boutique='Watchnian' AND prix_ttc IS NULL").fetchall()
    wc = WatchnianConnector({"boutique": "Watchnian"})
    targets, rate = load_targets(), fx.get_rate()
    fixed = miss = 0
    for i, r in enumerate(rows):
        path = r["url"].replace(BASE, "")
        try:
            w = wc.build_detail({"vendue": False, "url": path})
        except Exception:
            miss += 1
            continue
        if w.get("prix_ttc") is None:
            miss += 1
            continue
        db.upsert_watch(conn, pipeline.enrich(w, targets, rate))
        fixed += 1
        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{len(rows)} traités", flush=True)
    print(f"RESULTAT prix réparés={fixed} restés_sans_prix={miss}")


if __name__ == "__main__":
    main()
