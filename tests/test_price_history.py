"""Historique de prix : un point par CHANGEMENT de prix (pas un par passage de
collecte) — la matière première des tendances, sparklines et alertes de baisse."""
from fastapi.testclient import TestClient

from backend import api, config, db


def _conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    conn = db.connect()
    db.init_db(conn)
    return conn


def _w(prix_ttc, prix_detaxe_eur):
    return {"uid": "B:R1:u1", "boutique": "B", "reference": "R1", "url": "u1",
            "prix_ttc": prix_ttc, "prix_detaxe_eur": prix_detaxe_eur, "raw": {}}


def test_un_point_par_changement_de_prix(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    db.upsert_watch(conn, _w(1_000_000, 6000.0))       # arrivée → 1er point
    assert [p["prix_ttc"] for p in db.get_price_history(conn, "B:R1:u1")] == [1_000_000]
    db.upsert_watch(conn, _w(1_000_000, 6000.0))       # même prix → pas de bruit
    assert len(db.get_price_history(conn, "B:R1:u1")) == 1
    db.upsert_watch(conn, _w(900_000, 5400.0))         # baisse → 2e point
    pts = db.get_price_history(conn, "B:R1:u1")
    assert [p["prix_ttc"] for p in pts] == [1_000_000, 900_000]
    assert pts[-1]["prix_detaxe_eur"] == 5400.0


def test_scrape_sans_prix_najoute_pas_de_point(tmp_path, monkeypatch):
    """Un passage sans prix (sélecteur cassé, anti-bot) ne doit PAS polluer
    l'historique — même règle que l'upsert qui n'écrase jamais un prix par NULL."""
    conn = _conn(tmp_path, monkeypatch)
    db.upsert_watch(conn, _w(1_000_000, 6000.0))
    sans_prix = {"uid": "B:R1:u1", "boutique": "B", "reference": "R1", "url": "u1",
                 "raw": {}}
    db.upsert_watch(conn, sans_prix)
    assert len(db.get_price_history(conn, "B:R1:u1")) == 1


def test_endpoint_historique(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    db.upsert_watch(conn, _w(1_000_000, 6000.0))
    db.upsert_watch(conn, _w(950_000, 5700.0))
    client = TestClient(api.app)
    pts = client.get("/api/historique/B:R1:u1").json()
    assert [p["prix_detaxe_eur"] for p in pts] == [6000.0, 5700.0]
    assert all("seen_at" in p for p in pts)
