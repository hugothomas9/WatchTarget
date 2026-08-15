from backend import db, config


def make_conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    conn = db.connect()
    db.init_db(conn)
    return conn


W = {
    "uid": "Jackroad:126610LN:https://x.jp/1", "boutique": "Jackroad",
    "reference": "126610LN", "marque": "Rolex", "modele": "Submariner",
    "prix_ttc": 1100000, "prix_ht": None, "etat": "très bon", "annee": "2018",
    "date_ajout_site": "2026-06-20", "description": "", "url": "https://x.jp/1",
    "images": ["a.jpg"], "raw": {}, "prix_detaxe_jpy": 1000000.0,
    "prix_detaxe_eur": 6000.0, "benef_min": 3500.0, "benef_max": 5000.0,
    "target_id": "rolex-submariner-126610LN",
}


def test_upsert_nouvelle_puis_existante(tmp_path, monkeypatch):
    conn = make_conn(tmp_path, monkeypatch)
    assert db.upsert_watch(conn, W) is True
    assert db.upsert_watch(conn, W) is False
    assert len(db.get_watches(conn)) == 1


def test_get_watches_only_targets(tmp_path, monkeypatch):
    conn = make_conn(tmp_path, monkeypatch)
    db.upsert_watch(conn, W)
    db.upsert_watch(conn, {**W, "uid": "B:X:u2", "url": "u2", "reference": "X",
                           "target_id": None, "benef_min": None, "benef_max": None})
    assert len(db.get_watches(conn, only_targets=True)) == 1


def test_favorites_toggle(tmp_path, monkeypatch):
    conn = make_conn(tmp_path, monkeypatch)
    db.upsert_watch(conn, W)
    assert db.toggle_favorite(conn, W["uid"]) is True
    assert db.is_favorite(conn, W["uid"]) is True
    assert len(db.get_favorites(conn)) == 1
    assert db.toggle_favorite(conn, W["uid"]) is False
    assert db.get_favorites(conn) == []
