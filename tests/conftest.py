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
    import gc
    from backend import dbengine
    conn = db.connect()
    for t in _TABLES:
        conn.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    conn.commit()
    conn.close()
    yield
    # Les tests ne ferment pas toujours leurs connexions. Sur SQLite (NullPool)
    # c'est sans effet, mais sur PG une connexion fuitée reste « idle in
    # transaction » et bloquerait les DROP TABLE du test suivant (deadlock de
    # suite). gc.collect() finalise les connexions orphelines (rollback + retour
    # au pool), puis dispose_all() ferme les pools proprement.
    gc.collect()
    dbengine.dispose_all()
