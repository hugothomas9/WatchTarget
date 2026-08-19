"""Dispatch du bot Telegram : décision pure, aucun réseau."""
from backend import bot, config, db

RATE = 0.0060


def _conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    conn = db.connect()
    db.init_db(conn)
    return conn


def _msg(texte, uid=111, chat=111):
    return {"update_id": 1,
            "message": {"message_id": 10, "chat": {"id": chat},
                        "from": {"id": uid, "first_name": "Alice"}, "text": texte}}


def _cb(data, uid=111, chat=111):
    return {"update_id": 2,
            "callback_query": {"id": "cb1", "data": data,
                               "from": {"id": uid, "first_name": "Alice"},
                               "message": {"message_id": 10, "chat": {"id": chat}}}}


def _types(actions):
    return [a["type"] for a in actions]


def _textes(actions):
    return " ".join(str(a.get("text", "")) + str(a.get("caption", ""))
                    for a in actions)


def test_start_affiche_accueil_et_enregistre_l_utilisateur(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    actions = bot.traiter_update(conn, _msg("/start"), RATE)
    assert _types(actions) == ["send"]
    assert "WatchTarget" in actions[0]["text"]
    assert actions[0]["chat_id"] == 111
    assert db.get_user(conn, 111) is not None      # inscrit à la 1re interaction


def test_creation_alerte_en_deux_temps(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    # clic « Créer une alerte » → question + étape mémorisée
    actions = bot.traiter_update(conn, _cb("new"), RATE)
    assert "answer" in _types(actions) and "edit" in _types(actions)
    assert db.get_bot_etape(conn, 111)[0] == "attente_mots_cles"
    # le message texte suivant crée l'alerte
    actions = bot.traiter_update(conn, _msg("rolex daytona"), RATE)
    alertes = db.list_cibles(conn, telegram_id=111)
    assert len(alertes) == 1 and alertes[0]["mots_cles"] == "rolex daytona"
    assert db.get_bot_etape(conn, 111) is None      # conversation refermée
    assert "rolex daytona" in _textes(actions)


def test_texte_hors_conversation_renvoie_l_accueil(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    actions = bot.traiter_update(conn, _msg("bonjour"), RATE)
    assert "WatchTarget" in _textes(actions)
    assert db.list_cibles(conn, telegram_id=111) == []   # rien créé par accident


def test_mots_cles_vides_redemandent(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    bot.traiter_update(conn, _cb("new"), RATE)
    actions = bot.traiter_update(conn, _msg("   "), RATE)
    assert db.list_cibles(conn, telegram_id=111) == []
    assert db.get_bot_etape(conn, 111)[0] == "attente_mots_cles"   # toujours en cours
    assert "mots-clés" in _textes(actions)


def test_liste_puis_fiche_alerte(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    cid = db.add_cible(conn, "rolex daytona", "Ma Daytona", telegram_id=111)
    actions = bot.traiter_update(conn, _cb("list"), RATE)
    assert "Ma Daytona" in str(actions)
    actions = bot.traiter_update(conn, _cb(f"a:{cid}"), RATE)
    assert "Mots-clés" in _textes(actions)


def test_pause_et_reprise_depuis_le_bot(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    cid = db.add_cible(conn, "rolex daytona", "Ma Daytona", telegram_id=111)
    bot.traiter_update(conn, _cb(f"a:{cid}:toggle"), RATE)
    assert db.get_cible(conn, cid, telegram_id=111)["actif"] == 0
    bot.traiter_update(conn, _cb(f"a:{cid}:toggle"), RATE)
    assert db.get_cible(conn, cid, telegram_id=111)["actif"] == 1


def test_suppression_demande_confirmation(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    cid = db.add_cible(conn, "rolex daytona", "Ma Daytona", telegram_id=111)
    actions = bot.traiter_update(conn, _cb(f"a:{cid}:del"), RATE)
    assert "définitive" in _textes(actions)
    assert db.get_cible(conn, cid, telegram_id=111) is not None   # pas encore supprimée
    bot.traiter_update(conn, _cb(f"a:{cid}:del!"), RATE)
    assert db.get_cible(conn, cid, telegram_id=111) is None


def test_renommer_et_changer_les_mots_cles(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    cid = db.add_cible(conn, "rolex daytona", "Ma Daytona", telegram_id=111)
    bot.traiter_update(conn, _cb(f"a:{cid}:ren"), RATE)
    assert db.get_bot_etape(conn, 111) == ("attente_libelle", {"cible_id": cid})
    bot.traiter_update(conn, _msg("Daytona acier"), RATE)
    assert db.get_cible(conn, cid, telegram_id=111)["libelle"] == "Daytona acier"
    bot.traiter_update(conn, _cb(f"a:{cid}:kw"), RATE)
    bot.traiter_update(conn, _msg("rolex daytona 126500LN"), RATE)
    assert db.get_cible(conn, cid, telegram_id=111)["mots_cles"] == \
        "rolex daytona 126500LN"


def test_voir_les_montres_envoie_entete_puis_photos(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    for i in range(2):
        db.upsert_watch(conn, {
            "uid": f"jackroad:126500LN:{i}", "boutique": "jackroad",
            "reference": "126500LN", "marque": "Rolex", "modele": "Daytona",
            "url": f"https://ex/{i}", "prix_ttc": 3210000 + i, "etat": "中古A",
            "images": ["https://img/1.jpg"]})
    cid = db.add_cible(conn, "rolex daytona", "Ma Daytona", telegram_id=111)
    actions = bot.traiter_update(conn, _cb(f"v:{cid}:1"), RATE)
    assert _types(actions) == ["answer", "send", "photo", "send"]
    assert "Ma Daytona" in actions[1]["text"]        # en-tête
    assert actions[2]["photo"] == "https://img/1.jpg"
    assert "19 260 €" in actions[2]["caption"]       # prix boutique converti
    assert actions[-1]["keyboard"]                   # navigation


def test_voir_les_montres_alerte_vide(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    cid = db.add_cible(conn, "rolex introuvable", "Vide", telegram_id=111)
    actions = bot.traiter_update(conn, _cb(f"v:{cid}:1"), RATE)
    assert "Aucune montre" in _textes(actions)
    assert "photo" not in _types(actions)


def test_impossible_d_ouvrir_ou_supprimer_l_alerte_d_un_autre(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    cid = db.add_cible(conn, "rolex daytona", "Ma Daytona", telegram_id=111)
    for data in (f"a:{cid}", f"v:{cid}:1", f"a:{cid}:del!", f"a:{cid}:toggle",
                 f"a:{cid}:ren"):
        actions = bot.traiter_update(conn, _cb(data, uid=222), RATE)
        assert bot.MSG_ACCES in _textes(actions), data
    assert db.get_cible(conn, cid, telegram_id=111)["actif"] == 1   # intacte
    assert db.get_cible(conn, cid, telegram_id=111) is not None


def test_aucune_donnee_everywatch_dans_les_actions(tmp_path, monkeypatch):
    """Même avec un prix EveryWatch en base, rien n'en sort côté bot."""
    conn = _conn(tmp_path, monkeypatch)
    db.upsert_watch(conn, {
        "uid": "jackroad:126500LN:a", "boutique": "jackroad",
        "reference": "126500LN", "marque": "Rolex", "modele": "Daytona",
        "url": "https://ex/a", "prix_ttc": 3210000, "prix_detaxe_eur": 26000.0,
        "etat": "中古A", "images": ["https://img/1.jpg"]})
    db.upsert_ew_price(conn, "126500LN", "", "",
                       {"ew_median_eur": 27400, "ew_p25_eur": 26000,
                        "ew_p75_eur": 29000, "ew_n_sales": 57,
                        "ew_matched_by": "agregat", "ew_variant": ""})
    cid = db.add_cible(conn, "rolex daytona", "Ma Daytona", telegram_id=111)
    dump = str(bot.traiter_update(conn, _cb(f"v:{cid}:1"), RATE))
    for interdit in ("27 400", "26 000", "EveryWatch", "marge", "détaxé"):
        assert interdit not in dump


def test_update_inconnu_ne_casse_rien(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    assert bot.traiter_update(conn, {"update_id": 5}, RATE) == []
    assert bot.traiter_update(conn, _cb("nawak"), RATE)[0]["type"] == "answer"


def test_saisie_tres_longue_est_tronquee_a_la_creation(tmp_path, monkeypatch):
    """Une saisie de 4096 caractères (max Telegram) ne doit jamais être stockée
    telle quelle : elle ferait déborder les écrans qui l'affichent ensuite."""
    conn = _conn(tmp_path, monkeypatch)
    bot.traiter_update(conn, _cb("new"), RATE)
    saisie = "rolex daytona " + ("x" * 4096)
    bot.traiter_update(conn, _msg(saisie), RATE)
    alertes = db.list_cibles(conn, telegram_id=111)
    assert len(alertes) == 1
    assert len(alertes[0]["mots_cles"]) <= bot.LONGUEUR_MAX_SAISIE


def test_saisie_tres_longue_est_tronquee_au_renommage_et_aux_mots_cles(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    cid = db.add_cible(conn, "rolex daytona", "Ma Daytona", telegram_id=111)
    bot.traiter_update(conn, _cb(f"a:{cid}:ren"), RATE)
    bot.traiter_update(conn, _msg("y" * 4096), RATE)
    libelle = db.get_cible(conn, cid, telegram_id=111)["libelle"]
    assert len(libelle) <= bot.LONGUEUR_MAX_SAISIE

    bot.traiter_update(conn, _cb(f"a:{cid}:kw"), RATE)
    bot.traiter_update(conn, _msg("z" * 4096), RATE)
    mots_cles = db.get_cible(conn, cid, telegram_id=111)["mots_cles"]
    assert len(mots_cles) <= bot.LONGUEUR_MAX_SAISIE


def test_callback_data_malforme_ne_leve_pas_et_ne_touche_pas_la_base(tmp_path, monkeypatch):
    """Un callback_data est une donnée entièrement contrôlée par le client (bot
    PUBLIC) : un fragment forgé ou tronqué ne doit jamais lever d'exception, et
    l'alerte existante doit rester strictement intacte."""
    conn = _conn(tmp_path, monkeypatch)
    cid = db.add_cible(conn, "rolex daytona", "Ma Daytona", telegram_id=111)
    avant = dict(db.get_cible(conn, cid, telegram_id=111))
    for data in ("a:xyz", "v:5:abc", "v:abc:1", "a:", "v:",
                 f"a:{cid}:action_inconnue"):
        actions = bot.traiter_update(conn, _cb(data), RATE)
        # au plus un "answer" (accusé de réception du callback), jamais plus
        assert all(a["type"] == "answer" for a in actions), (data, actions)
        apres = dict(db.get_cible(conn, cid, telegram_id=111))
        assert apres == avant, data


def test_alerte_supprimee_pendant_conversation_puis_message_texte(tmp_path, monkeypatch):
    """L'alerte est supprimée PENDANT que l'utilisateur est en conversation
    (attente_libelle) : le message texte suivant ne doit ni lever, ni recréer
    l'alerte, et doit refermer la conversation plutôt que de laisser
    l'utilisateur coincé en attente."""
    conn = _conn(tmp_path, monkeypatch)
    cid = db.add_cible(conn, "rolex daytona", "Ma Daytona", telegram_id=111)
    bot.traiter_update(conn, _cb(f"a:{cid}:ren"), RATE)
    assert db.get_bot_etape(conn, 111)[0] == "attente_libelle"
    db.delete_cible(conn, cid, telegram_id=111)
    actions = bot.traiter_update(conn, _msg("Nouveau nom"), RATE)
    assert bot.MSG_ACCES in _textes(actions)
    assert db.get_bot_etape(conn, 111) is None      # pas coincé en attente
    assert db.get_cible(conn, cid, telegram_id=111) is None   # pas recréée


def test_alerte_reattribuee_a_un_autre_pendant_conversation_puis_message_texte(tmp_path, monkeypatch):
    """L'alerte n'est pas supprimée mais a changé de propriétaire pendant la
    conversation (ex. transfert admin) : le propriétaire d'origine ne doit plus
    pouvoir la modifier via son message texte en attente."""
    conn = _conn(tmp_path, monkeypatch)
    cid = db.add_cible(conn, "rolex daytona", "Ma Daytona", telegram_id=111)
    bot.traiter_update(conn, _cb(f"a:{cid}:kw"), RATE)
    assert db.get_bot_etape(conn, 111)[0] == "attente_kw"
    conn.execute("UPDATE cibles SET telegram_id=? WHERE id=?", (222, cid))
    conn.commit()
    actions = bot.traiter_update(conn, _msg("nouveaux mots-clés"), RATE)
    assert bot.MSG_ACCES in _textes(actions)
    assert db.get_bot_etape(conn, 111) is None      # pas coincé en attente
    assert db.get_cible(conn, cid, telegram_id=222)["mots_cles"] == "rolex daytona"
