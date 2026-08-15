"""Worker des scrapers (cron de prod) : une passe quotidienne complète, séquentielle
(pas de contention). À planifier sur le PaaS (1×/jour ou 2×/jour).

  python -m backend.worker

Enchaîne : collecte incrémentale → tri des vendues → pricing EveryWatch des arrivages.
Les alertes Telegram partent automatiquement en fin de collecte (pipeline.run).
"""
import sys
import time


def _log(msg):
    print(f"[worker] {msg}", flush=True)


def main():
    from . import pipeline, verify_dispo, market_scan
    t0 = time.monotonic()

    _log("collecte incrémentale…")
    res = pipeline.run("incremental")     # + alertes Telegram des cibles en fin de run
    _log(f"collecte : {res['new']} nouvelles / {res['fetched']} vues")

    _log("tri des vendues (montres non revues depuis 1 j)…")
    v = verify_dispo.run(older_than_days=1)
    _log(f"tri : vendues={v['vendue']} retirées={v['retiree']}")

    _log("pricing EveryWatch des arrivages…")
    conn = market_scan.db.connect()
    n = market_scan.enrich_everywatch(conn, limit=80)
    _log(f"everywatch : {n} config(s) pricée(s)")

    _log(f"terminé en {round((time.monotonic() - t0) / 60, 1)} min")


if __name__ == "__main__":
    sys.exit(main())
