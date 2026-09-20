"""Filtres décisionnels : modèle générique indépendant (/api/modeles), fourchette
prix/marge sur les opportunités, recherche texte multilingue (« daytona » trouve
une デイトナ grâce à la famille normalisée en latin)."""
from fastapi.testclient import TestClient

from backend import api, config, db


def _conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    conn = db.connect()
    db.init_db(conn)
    return conn


def _seed(conn):
    """Deux opportunités : une Daytona chère, une Submariner abordable."""
    db.upsert_watch(conn, {"uid": "B:116500LN:u1", "boutique": "B",
                           "reference": "116500LN", "url": "u1", "marque": "Rolex",
                           "modele": "デイトナ", "famille": "Daytona",
                           "prix_detaxe_eur": 26000.0, "prix_ttc": 4_200_000})
    db.upsert_watch(conn, {"uid": "B:126610LN:u2", "boutique": "B",
                           "reference": "126610LN", "url": "u2", "marque": "Rolex",
                           "modele": "サブマリーナ", "famille": "Submariner",
                           "prix_detaxe_eur": 9000.0, "prix_ttc": 1_500_000})
    for ref, med in (("116500LN", 30000), ("126610LN", 12000)):
        db.upsert_ew_price(conn, ref, "", "",
                           {"ew_median_eur": med, "ew_p25_eur": med * 0.9,
                            "ew_p75_eur": med * 1.1, "ew_n_sales": 20,
                            "ew_sales_12m": 15, "ew_matched_by": "ref",
                            "ew_variant": ""})


def test_endpoint_modeles_independant_de_la_marque(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    _seed(conn)
    client = TestClient(api.app)
    assert client.get("/api/modeles").json() == ["Daytona", "Submariner"]
    # et filtrable par marque si fournie
    assert client.get("/api/modeles?marque=Rolex").json() == ["Daytona", "Submariner"]
    assert client.get("/api/modeles?marque=Omega").json() == []


def test_opportunites_filtre_famille(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    _seed(conn)
    opps = db.get_opportunities(conn, 700, 5, famille="Daytona")
    assert [o["reference"] for o in opps] == ["116500LN"]


def test_opportunites_filtre_prix_max_achat(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    _seed(conn)
    opps = db.get_opportunities(conn, 700, 5, prix_max=10000)
    assert [o["reference"] for o in opps] == ["126610LN"]   # la Daytona à 26k exclue


def test_opportunites_recherche_multilingue(tmp_path, monkeypatch):
    """« daytona » en latin doit trouver la montre dont le modèle est en katakana
    (via la famille normalisée) ; idem par référence."""
    conn = _conn(tmp_path, monkeypatch)
    _seed(conn)
    assert [o["reference"] for o in
            db.get_opportunities(conn, 700, 5, q="daytona")] == ["116500LN"]
    assert [o["reference"] for o in
            db.get_opportunities(conn, 700, 5, q="126610")] == ["126610LN"]
    assert db.get_opportunities(conn, 700, 5, q="nautilus") == []


def test_stock_recherche_multilingue(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    _seed(conn)
    client = TestClient(api.app)
    rows = client.get("/api/stock?q=daytona").json()
    assert [w["reference"] for w in rows] == ["116500LN"]
    # deux mots = ET (tous requis)
    assert client.get("/api/stock?q=rolex submariner").json()[0]["reference"] == "126610LN"
    assert client.get("/api/stock?q=patek").json() == []
