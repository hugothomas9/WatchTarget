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


def _watch(uid, ref, prix_ttc, modele="デイトナ", marque="Rolex"):
    return {"uid": uid, "boutique": uid.split(":")[0], "reference": ref,
            "marque": marque, "modele": modele, "url": "https://ex/" + uid,
            "prix_ttc": prix_ttc, "prix_detaxe_eur": 26000.0, "etat": "中古A"}


def test_matches_pour_cible_ne_renvoie_que_cette_alerte(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    db.upsert_watch(conn, _watch("jackroad:126500LN:a", "126500LN", 3210000))
    db.upsert_watch(conn, _watch("cywatch:311.30:b", "311.30.42", 900000,
                                 modele="スピードマスター", marque="Omega"))
    daytona = db.add_cible(conn, "rolex daytona", "Ma Daytona", telegram_id=111)
    speed = db.add_cible(conn, "omega speedmaster", "Speed", telegram_id=111)

    res = db.matches_pour_cible(conn, daytona)
    assert [w["reference"] for w in res] == ["126500LN"]
    assert [w["reference"] for w in db.matches_pour_cible(conn, speed)] == ["311.30.42"]


def test_matches_pour_cible_sans_enrichissement(tmp_path, monkeypatch):
    """Le bot ne doit JAMAIS voir de donnée EveryWatch : elle n'est même pas chargée."""
    conn = _conn(tmp_path, monkeypatch)
    db.upsert_watch(conn, _watch("jackroad:126500LN:a", "126500LN", 3210000))
    db.upsert_ew_price(conn, "126500LN", "", "",
                       {"ew_median_eur": 27400, "ew_p25_eur": 26000,
                        "ew_p75_eur": 29000, "ew_n_sales": 57,
                        "ew_matched_by": "agregat", "ew_variant": ""})
    cid = db.add_cible(conn, "rolex daytona", "Ma Daytona", telegram_id=111)
    w = db.matches_pour_cible(conn, cid)[0]
    for interdit in ("ew_median_eur", "ew_n_sales", "spread_eur", "marge_nette_eur"):
        assert interdit not in w
    # le champ brut prix_ttc, lui, est bien là (c'est le prix affiché)
    assert w["prix_ttc"] == 3210000


def test_matches_pour_cible_ignore_les_vendues(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    w = _watch("jackroad:126500LN:a", "126500LN", 3210000)
    w["vendue"] = True
    db.upsert_watch(conn, w)
    cid = db.add_cible(conn, "rolex daytona", "Ma Daytona", telegram_id=111)
    assert db.matches_pour_cible(conn, cid) == []


def test_matches_pour_cible_alerte_inconnue(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    assert db.matches_pour_cible(conn, 4242) == []
