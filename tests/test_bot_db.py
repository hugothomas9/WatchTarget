"""Bot Telegram : état de conversation, méta (offset), et gestion des alertes."""
from backend import config, db


def _conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    conn = db.connect()
    db.init_db(conn)
    return conn


def test_etape_conversation_cycle_de_vie(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    assert db.get_bot_etape(conn, 111) is None
    db.set_bot_etape(conn, 111, "attente_mots_cles")
    assert db.get_bot_etape(conn, 111) == ("attente_mots_cles", {})
    # une nouvelle étape remplace la précédente (pas d'empilement)
    db.set_bot_etape(conn, 111, "attente_libelle", {"cible_id": 7})
    assert db.get_bot_etape(conn, 111) == ("attente_libelle", {"cible_id": 7})
    # les utilisateurs sont indépendants
    assert db.get_bot_etape(conn, 222) is None
    db.clear_bot_etape(conn, 111)
    assert db.get_bot_etape(conn, 111) is None


def test_meta_offset(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    assert db.get_bot_meta(conn, "offset") is None
    db.set_bot_meta(conn, "offset", "42")
    assert db.get_bot_meta(conn, "offset") == "42"
    db.set_bot_meta(conn, "offset", "43")        # upsert, pas d'insert en double
    assert db.get_bot_meta(conn, "offset") == "43"
