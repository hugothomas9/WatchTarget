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


def test_get_cible_respecte_le_proprietaire(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    cid = db.add_cible(conn, "rolex daytona", "Ma Daytona", telegram_id=111)
    assert db.get_cible(conn, cid, telegram_id=111)["libelle"] == "Ma Daytona"
    assert db.get_cible(conn, cid, telegram_id=222) is None      # pas la sienne
    assert db.get_cible(conn, 9999, telegram_id=111) is None     # inexistante


def test_pause_et_reactivation(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    cid = db.add_cible(conn, "rolex daytona", "Ma Daytona", telegram_id=111)
    assert db.get_cible(conn, cid, telegram_id=111)["actif"] == 1
    db.set_cible_actif(conn, cid, False, telegram_id=111)
    assert db.get_cible(conn, cid, telegram_id=111)["actif"] == 0
    # une alerte en pause disparaît des alertes actives (donc des notifications)
    assert db.list_cibles(conn, actives_only=True, telegram_id=111) == []
    db.set_cible_actif(conn, cid, True, telegram_id=111)
    assert len(db.list_cibles(conn, actives_only=True, telegram_id=111)) == 1


def test_update_cible_champs_independants_et_isolation(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    cid = db.add_cible(conn, "rolex daytona", "Ma Daytona", telegram_id=111)
    db.update_cible(conn, cid, libelle="Daytona acier", telegram_id=111)
    row = db.get_cible(conn, cid, telegram_id=111)
    assert row["libelle"] == "Daytona acier"
    assert row["mots_cles"] == "rolex daytona"      # inchangé
    db.update_cible(conn, cid, mots_cles="rolex daytona 126500LN", telegram_id=111)
    row = db.get_cible(conn, cid, telegram_id=111)
    assert row["mots_cles"] == "rolex daytona 126500LN"
    assert row["libelle"] == "Daytona acier"        # inchangé
    # un autre utilisateur ne peut rien modifier
    db.update_cible(conn, cid, libelle="pirate", telegram_id=222)
    db.set_cible_actif(conn, cid, False, telegram_id=222)
    row = db.get_cible(conn, cid, telegram_id=111)
    assert row["libelle"] == "Daytona acier" and row["actif"] == 1
