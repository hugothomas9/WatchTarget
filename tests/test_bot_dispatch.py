"""Dispatch du bot Telegram : décision pure, aucun réseau."""
from backend import bot, config, db

RATE = 0.0060


def _conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    conn = db.connect()
    db.init_db(conn)
    return conn


def _msg(texte, uid=111, chat=111, chat_type="private"):
    return {"update_id": 1,
            "message": {"message_id": 10, "chat": {"id": chat, "type": chat_type},
                        "from": {"id": uid, "first_name": "Alice"}, "text": texte}}


def _cb(data, uid=111, chat=111, chat_type="private"):
    return {"update_id": 2,
            "callback_query": {"id": "cb1", "data": data,
                               "from": {"id": uid, "first_name": "Alice"},
                               "message": {"message_id": 10,
                                          "chat": {"id": chat, "type": chat_type}}}}


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


def test_callback_data_identifiant_hors_plage_int64_ne_leve_pas(tmp_path, monkeypatch):
    """Python autorise les entiers à précision arbitraire : int("999...999") réussit
    même pour un nombre bien plus grand qu'une clé primaire SQLite/PG (entier signé
    64 bits). Sans borne explicite, l'exception surgit plus loin, côté driver
    (OverflowError), au moment de la requête — même vecteur qu'un callback_data
    malformé, même point d'entrée public, doit être traité pareil : ignoré, sans
    action ni écriture, base intacte."""
    conn = _conn(tmp_path, monkeypatch)
    cid = db.add_cible(conn, "rolex daytona", "Ma Daytona", telegram_id=111)
    avant = dict(db.get_cible(conn, cid, telegram_id=111))
    hors_plage = (
        "99999999999999999999999999",         # 26 chiffres, largement hors plage
        "-1",                                  # négatif
        "0",                                   # zéro : pas un id valide (PK >= 1)
        "9223372036854775808",                 # INT64_MAX + 1, tout juste hors plage
    )
    for n in hors_plage:
        for data in (f"a:{n}", f"a:{n}:toggle", f"v:{n}:1", f"v:{cid}:{n}"):
            actions = bot.traiter_update(conn, _cb(data), RATE)
            assert all(a["type"] == "answer" for a in actions), (data, actions)
            apres = dict(db.get_cible(conn, cid, telegram_id=111))
            assert apres == avant, data


def test_callback_data_bien_forme_visant_l_alerte_d_autrui_reste_refuse(tmp_path, monkeypatch):
    """Non-régression : la borne ajoutée dans _int_ou_none ne doit pas relâcher
    l'isolation par utilisateur pour un identifiant parfaitement valide."""
    conn = _conn(tmp_path, monkeypatch)
    cid = db.add_cible(conn, "rolex daytona", "Ma Daytona", telegram_id=111)
    actions = bot.traiter_update(conn, _cb(f"a:{cid}", uid=222), RATE)
    assert bot.MSG_ACCES in _textes(actions)
    assert db.get_cible(conn, cid, telegram_id=111) is not None


def test_message_dans_un_groupe_est_ignore(tmp_path, monkeypatch):
    """Le bot est PUBLIC : ajouté à un groupe, un simple message (ex. /start, livré
    même en privacy mode) ne doit produire AUCUNE action ni toucher la base — sinon
    le menu s'affiche dans le groupe pour tout le monde (revue finale, point 1)."""
    conn = _conn(tmp_path, monkeypatch)
    actions = bot.traiter_update(conn, _msg("/start", chat_type="group"), RATE)
    assert actions == []
    assert db.get_user(conn, 111) is None


def test_callback_dans_un_groupe_est_ignore(tmp_path, monkeypatch):
    """Un callback_query venant d'un groupe (livré quel que soit le privacy mode)
    ne doit produire AUCUNE action : sinon le bot édite le message DANS le groupe
    avec les données privées de l'utilisateur qui a cliqué (alertes, stock…)."""
    conn = _conn(tmp_path, monkeypatch)
    cid = db.add_cible(conn, "rolex daytona", "Ma Daytona", telegram_id=111)
    actions = bot.traiter_update(conn, _cb("list", chat_type="group"), RATE)
    assert actions == []
    actions = bot.traiter_update(conn, _cb(f"a:{cid}", chat_type="supergroup"), RATE)
    assert actions == []


def test_compter_matches_une_seule_passe_selectivites_variees(tmp_path, monkeypatch):
    """`_compter_matches` doit compter, EN UNE SEULE passe sur `watches`, le nombre
    de montres par alerte — pour plusieurs alertes de sélectivité différente, dont
    une sans aucune correspondance (revue finale, point 3a)."""
    conn = _conn(tmp_path, monkeypatch)
    for i in range(3):
        db.upsert_watch(conn, {
            "uid": f"jackroad:126500LN:{i}", "boutique": "jackroad",
            "reference": "126500LN", "marque": "Rolex", "modele": "Daytona",
            "url": f"https://ex/{i}", "prix_ttc": 3210000, "etat": "中古A"})
    db.upsert_watch(conn, {
        "uid": "cywatch:311.30:z", "boutique": "cywatch",
        "reference": "311.30.42", "marque": "Omega", "modele": "Speedmaster",
        "url": "https://ex/z", "prix_ttc": 900000, "etat": "中古A"})
    large = db.add_cible(conn, "rolex", "Toutes les Rolex", telegram_id=111)
    precise = db.add_cible(conn, "rolex daytona 126500LN", "Daytona précise",
                           telegram_id=111)
    aucune = db.add_cible(conn, "patek nautilus", "Introuvable", telegram_id=111)

    cibles = db.list_cibles(conn, telegram_id=111)
    comptes = bot._compter_matches(conn, cibles)
    assert comptes[large] == 3
    assert comptes[precise] == 3
    assert comptes[aucune] == 0


def test_liste_alertes_affiche_les_bons_comptes(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    db.upsert_watch(conn, {
        "uid": "jackroad:126500LN:a", "boutique": "jackroad",
        "reference": "126500LN", "marque": "Rolex", "modele": "Daytona",
        "url": "https://ex/a", "prix_ttc": 3210000, "etat": "中古A"})
    cid = db.add_cible(conn, "rolex daytona", "Ma Daytona", telegram_id=111)
    vide = db.add_cible(conn, "patek nautilus", "Vide", telegram_id=111)
    actions = bot.traiter_update(conn, _cb("list"), RATE)
    dump = str(actions)
    assert "1 montres" in dump
    assert "0 montres" in dump


def test_creation_alerte_refusee_au_dela_du_plafond(tmp_path, monkeypatch):
    """Le bot est PUBLIC : sans plafond, un utilisateur peut créer 200 alertes puis
    ouvrir « Mes alertes » et bloquer le bot (mono-thread) pour tout le monde
    (revue finale, point 3b). Au-delà de `MAX_ALERTES_PAR_USER`, la création est
    refusée avec un message clair, pas d'exception ni de création silencieuse."""
    conn = _conn(tmp_path, monkeypatch)
    for i in range(bot.MAX_ALERTES_PAR_USER):
        db.add_cible(conn, f"mots {i}", f"Alerte {i}", telegram_id=111)
    assert len(db.list_cibles(conn, telegram_id=111)) == bot.MAX_ALERTES_PAR_USER

    bot.traiter_update(conn, _cb("new"), RATE)
    actions = bot.traiter_update(conn, _msg("rolex daytona"), RATE)

    assert len(db.list_cibles(conn, telegram_id=111)) == bot.MAX_ALERTES_PAR_USER
    assert str(bot.MAX_ALERTES_PAR_USER) in _textes(actions)
    assert db.get_bot_etape(conn, 111) is None      # conversation refermée, pas coincé


def test_message_dans_un_chat_prive_continue_de_fonctionner(tmp_path, monkeypatch):
    """Non-régression : le filtre groupe ne doit pas casser le cas normal."""
    conn = _conn(tmp_path, monkeypatch)
    actions = bot.traiter_update(conn, _msg("/start", chat_type="private"), RATE)
    assert "WatchTarget" in _textes(actions)
    assert db.get_user(conn, 111) is not None
