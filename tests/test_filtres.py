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


# --- Tranches de budget (< 1 k€, 1–5 k€, 5–10 k€, > 10 k€) -------------------
# Le front envoie une FOURCHETTE (prix_min/prix_max) sur le prix d'achat détaxé
# en euros ; le backend n'a pas à connaître les tranches, seulement les bornes.
def _seed_budget(conn):
    for i, prix in enumerate([800.0, 3000.0, 7000.0, 20000.0]):
        db.upsert_watch(conn, {"uid": f"B:R{i}:u{i}", "boutique": "B",
                               "reference": f"R{i}", "url": f"u{i}",
                               "marque": "Rolex", "prix_detaxe_eur": prix,
                               "status": "dispo"})


def test_stock_filtre_par_tranche_de_budget(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    _seed_budget(conn)
    client = TestClient(api.app)
    # < 1 000 € : borne haute EXCLUSIVE côté tranche suivante, donc 1000 n'est
    # jamais compté deux fois (on passe prix_max=1000 et prix_min=1000).
    assert [w["reference"] for w in
            client.get("/api/stock?prix_max=1000").json()] == ["R0"]
    assert [w["reference"] for w in
            client.get("/api/stock?prix_min=1000&prix_max=5000").json()] == ["R1"]
    assert [w["reference"] for w in
            client.get("/api/stock?prix_min=5000&prix_max=10000").json()] == ["R2"]
    assert [w["reference"] for w in
            client.get("/api/stock?prix_min=10000").json()] == ["R3"]


def test_stock_sans_tranche_renvoie_tout(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    _seed_budget(conn)
    client = TestClient(api.app)
    assert len(client.get("/api/stock").json()) == 4


def test_montre_sans_prix_exclue_des_tranches(tmp_path, monkeypatch):
    """Une fiche sans prix détaxé (scrape partiel) ne doit apparaître dans AUCUNE
    tranche — sinon elle remonterait dans toutes, prix inconnu = bruit."""
    conn = _conn(tmp_path, monkeypatch)
    _seed_budget(conn)
    db.upsert_watch(conn, {"uid": "B:SANSPRIX:u", "boutique": "B",
                           "reference": "SANSPRIX", "url": "u", "marque": "Rolex"})
    client = TestClient(api.app)
    refs = [w["reference"] for w in client.get("/api/stock?prix_min=10000").json()]
    assert refs == ["R3"]
    assert len(client.get("/api/stock").json()) == 5   # mais visible sans filtre


def test_opportunites_filtre_tranche_basse(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    _seed(conn)
    opps = db.get_opportunities(conn, 700, 5, prix_min=10000)
    assert [o["reference"] for o in opps] == ["116500LN"]   # 26k€, la 9k€ sort
