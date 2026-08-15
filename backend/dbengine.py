"""Couche d'accès portable SQLite ⇄ PostgreSQL.

But : garder l'interface DBAPI historique (placeholders « ? », lignes accessibles par
nom `row["col"]` ET par index `row[0]`, méthodes execute/executemany/executescript/
commit/close) tout en marchant sur les deux moteurs via SQLAlchemy.

- SQLite : placeholders « ? » natifs (qmark).
- PostgreSQL (psycopg3) : on traduit « ? » → « %s » (format), les « % » littéraux sont
  doublés au passage (aucun dans notre SQL, mais robuste).
Le SQL métier reste identique ; seules les rares spécificités (PRAGMA, AUTOINCREMENT,
introspection des colonnes) sont traitées à part dans db.py selon `conn.dialect`.
"""
from sqlalchemy import create_engine, event
from sqlalchemy.pool import NullPool

_engines: dict = {}


def _normalise_url(url: str) -> str:
    # SQLAlchemy → psycopg3 : forcer le driver psycopg (psycopg2 n'est pas installé)
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def _engine(url: str):
    url = _normalise_url(url)
    eng = _engines.get(url)
    if eng is not None:
        return eng
    if url.startswith("sqlite"):
        # NullPool : une vraie connexion par connect()/close() (comportement historique,
        # sûr vis-à-vis des threads uvicorn). PRAGMA posés à chaque ouverture.
        eng = create_engine(url, poolclass=NullPool, future=True,
                            connect_args={"check_same_thread": False})

        @event.listens_for(eng, "connect")
        def _pragmas(dbapi_conn, _rec):   # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=15000")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()
    else:
        # PostgreSQL : pooling par défaut (bon pour le multi-requêtes), MVCC → pas
        # de « database is locked ». pool_pre_ping recycle les connexions mortes.
        eng = create_engine(url, future=True, pool_pre_ping=True, pool_size=10,
                            max_overflow=20)
    _engines[url] = eng
    return eng


class _Row(dict):
    """dict accessible aussi par index entier (compat sqlite3.Row : r[0], r[1]…)."""
    def __init__(self, mapping):
        super().__init__(mapping)
        self._vals = list(mapping.values())

    def __getitem__(self, k):
        if isinstance(k, int):
            return self._vals[k]
        return super().__getitem__(k)


class _Result:
    def __init__(self, cursor_result):
        if cursor_result.returns_rows:
            self._rows = [_Row(dict(m)) for m in cursor_result.mappings()]
            self.lastrowid = None
            self.rowcount = len(self._rows)
        else:
            self._rows = []
            self.lastrowid = getattr(cursor_result, "lastrowid", None)
            self.rowcount = cursor_result.rowcount

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows

    def __iter__(self):
        return iter(self._rows)


class Conn:
    """Connexion portable. Interface volontairement proche de sqlite3.Connection."""
    def __init__(self, url: str):
        self._engine = _engine(url)
        self.dialect = self._engine.dialect.name        # 'sqlite' | 'postgresql'
        self._c = self._engine.connect()
        self.row_factory = None                          # compat (no-op)

    def _prep(self, sql: str) -> str:
        if self.dialect == "postgresql":
            return sql.replace("%", "%%").replace("?", "%s")
        return sql

    def execute(self, sql: str, params=None):
        sql = self._prep(sql)
        r = (self._c.exec_driver_sql(sql, tuple(params)) if params
             else self._c.exec_driver_sql(sql))
        return _Result(r)

    def executemany(self, sql: str, seq):
        seq = [tuple(p) for p in seq]
        if not seq:
            return
        self._c.exec_driver_sql(self._prep(sql), seq)

    def executescript(self, sql: str):
        for stmt in sql.split(";"):
            if stmt.strip():
                self._c.exec_driver_sql(stmt)

    def commit(self):
        self._c.commit()

    def rollback(self):
        self._c.rollback()

    def close(self):
        self._c.close()

    # certains appels font `with db.connect() as conn:` (sémantique sqlite3 : commit
    # en sortie normale, rollback sur exception ; la connexion N'est PAS fermée)
    def __enter__(self):
        return self

    def __exit__(self, exc_type, *_):
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        return False


def make_conn(url: str) -> Conn:
    return Conn(url)


def dispose_all():
    """Ferme tous les pools de connexions (utile entre tests PG pour éviter que le
    pool ne s'épuise à cause de connexions de test non fermées)."""
    for eng in _engines.values():
        eng.dispose()
    _engines.clear()
