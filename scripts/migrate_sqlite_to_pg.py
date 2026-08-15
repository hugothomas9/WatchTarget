"""Migration des données SQLite → PostgreSQL (au déploiement).

Usage :
  DATABASE_URL=postgresql://user:pass@host:5432/scrapmontres \
    python -m scripts.migrate_sqlite_to_pg [chemin_sqlite]

Copie chaque table (watches, prix, favoris, cibles…) de la base SQLite locale vers
PostgreSQL. Idempotent (ON CONFLICT DO NOTHING) → relançable sans doublon. Recale la
séquence d'id de `cibles` après coup.
"""
import sqlite3
import sys

from backend import config, db

_TABLES = ["watches", "favorites", "seen", "cibles",
           "market_prices", "ew_prices", "notified"]


def _table_exists_sqlite(src, table) -> bool:
    return src.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,)).fetchone() is not None


def migrate(sqlite_path: str, pg_url: str) -> dict:
    src = sqlite3.connect(sqlite_path)
    src.row_factory = sqlite3.Row
    config.DATABASE_URL = pg_url
    dst = db.connect()
    db.init_db(dst)

    counts = {}
    for t in _TABLES:
        if not _table_exists_sqlite(src, t):
            continue
        rows = src.execute(f"SELECT * FROM {t}").fetchall()
        if not rows:
            counts[t] = 0
            continue
        cols = list(rows[0].keys())
        collist = ", ".join(cols)
        ph = ", ".join(["?"] * len(cols))
        sql = f"INSERT INTO {t} ({collist}) VALUES ({ph}) ON CONFLICT DO NOTHING"
        dst.executemany(sql, [tuple(r[c] for c in cols) for r in rows])
        dst.commit()
        counts[t] = len(rows)

    # recaler la séquence auto de cibles (les id ont été copiés en dur)
    if counts.get("cibles"):
        dst.execute("SELECT setval(pg_get_serial_sequence('cibles','id'), "
                    "COALESCE((SELECT MAX(id) FROM cibles),1))")
        dst.commit()
    src.close()
    return counts


def main():
    if not config.DATABASE_URL:
        print("Défini DATABASE_URL (PostgreSQL) d'abord."); sys.exit(1)
    sqlite_path = sys.argv[1] if len(sys.argv) > 1 else str(config.DB_PATH)
    print(f"Migration {sqlite_path} → {config.DATABASE_URL}")
    counts = migrate(sqlite_path, config.DATABASE_URL)
    for t, n in counts.items():
        print(f"  {t}: {n} ligne(s)")
    print("Migration terminée.")


if __name__ == "__main__":
    main()
