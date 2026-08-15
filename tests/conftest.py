"""Permet de faire tourner TOUTE la suite contre PostgreSQL (vérif de parité) :

    TEST_DATABASE_URL=postgresql://user@host:5432/db pytest

Sans cette variable, les tests utilisent SQLite comme d'habitude (isolation par
fichier tmp). Avec, chaque test repart d'un schéma propre sur la base PG partagée.
"""
import os

import pytest

from backend import config, db

_TABLES = ["watches", "favorites", "seen", "cibles",
           "market_prices", "ew_prices", "notified"]


@pytest.fixture(autouse=True)
def _db_backend(monkeypatch):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        yield                      # SQLite : comportement historique
        return
    monkeypatch.setattr(config, "DATABASE_URL", url)   # connect() → PostgreSQL
    from backend import dbengine
    conn = db.connect()
    for t in _TABLES:
        conn.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    conn.commit()
    conn.close()
    yield
    # les tests ne ferment pas toujours leurs connexions (sans effet sur SQLite NullPool,
    # mais épuise le pool PG) → on dispose les pools après chaque test.
    dbengine.dispose_all()
