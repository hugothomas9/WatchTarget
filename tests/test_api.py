from fastapi.testclient import TestClient

from backend import api, config, db


def test_endpoints_de_base(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    conn = db.connect()
    db.init_db(conn)
    db.upsert_watch(conn, {"uid": "B:R:u", "boutique": "B", "reference": "R",
                           "url": "u", "benef_max": 100})
    client = TestClient(api.app)
    assert client.get("/api/stock").status_code == 200
    r = client.post("/api/favoris/B:R:u").json()
    assert r["favorite"] is True
    assert len(client.get("/api/favoris").json()) == 1


def test_cibles_mots_cles(tmp_path, monkeypatch):
    """Créer une alerte, une montre qui matche apparaît dans /api/cibles."""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    conn = db.connect()
    db.init_db(conn)
    client = TestClient(api.app)
    # aucune alerte → cibles vide
    assert client.get("/api/cibles").json() == []
    # créer une alerte
    cid = client.post("/api/alertes",
                      json={"mots_cles": "rolex daytona 116500LN",
                            "libelle": "Daytona"}).json()["id"]
    assert len(client.get("/api/alertes").json()) == 1
    # une montre qui matche (modèle en japonais → « daytona » via traduction)
    db.upsert_watch(conn, {"uid": "B:116500LN:u", "boutique": "B",
                           "reference": "116500LN", "url": "u",
                           "marque": "Rolex", "modele": "デイトナ 116500LN",
                           "prix_detaxe_eur": 26000.0})
    matches = client.get("/api/cibles").json()
    assert len(matches) == 1
    assert matches[0]["reference"] == "116500LN"
    assert "Daytona" in matches[0]["cibles_match"]
    # supprimer l'alerte → cibles vide
    client.delete(f"/api/alertes/{cid}")
    assert client.get("/api/cibles").json() == []
