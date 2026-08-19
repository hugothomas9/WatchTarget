"""Boucle du bot : offset persisté, actions exécutées — avec un transport factice."""
from backend import bot, config, db


def _conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    conn = db.connect()
    db.init_db(conn)
    return conn


class FauxTransport:
    """Remplace l'API Telegram : sert des updates scriptés, enregistre les envois."""
    def __init__(self, tours):
        self.tours = list(tours)      # une liste d'updates par tour
        self.offsets = []
        self.envoyes = []

    def get_updates(self, offset):
        self.offsets.append(offset)
        return self.tours.pop(0) if self.tours else []

    def envoyer(self, action):
        self.envoyes.append(action)
        return True


def _msg(update_id, texte, uid=111):
    return {"update_id": update_id,
            "message": {"message_id": 10, "chat": {"id": uid, "type": "private"},
                        "from": {"id": uid, "first_name": "Alice"}, "text": texte}}


def test_boucle_execute_et_persiste_l_offset(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    t = FauxTransport([[_msg(100, "/start")], [_msg(101, "/aide")]])
    n = bot.boucle(conn, lambda: 0.006, t, max_tours=2)
    assert n == 2                                  # 2 updates traités
    assert t.offsets == [None, 101]                # offset = dernier id + 1 au tour 2
    assert db.get_bot_meta(conn, "offset") == "102"
    assert any("WatchTarget" in str(a.get("text")) for a in t.envoyes)


def test_boucle_reprend_l_offset_persiste(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    db.set_bot_meta(conn, "offset", "500")
    t = FauxTransport([[]])
    bot.boucle(conn, lambda: 0.006, t, max_tours=1)
    assert t.offsets == [500]                      # pas de rejeu des anciens updates


def test_boucle_survit_a_un_update_qui_plante(tmp_path, monkeypatch, capsys):
    """Un update qui déclenche une VRAIE exception dans le code de production
    (ici via `db.upsert_user`, appelé par `traiter_update` pour tout update) ne
    doit pas tuer le bot ni bloquer l'offset ; il est journalisé et sauté."""
    conn = _conn(tmp_path, monkeypatch)

    orig_upsert = db.upsert_user

    def upsert_qui_plante(conn_, uid, first_name, username):
        if not first_name:          # notre update "casse" n'a pas de first_name
            raise RuntimeError("boom")
        return orig_upsert(conn_, uid, first_name, username)

    monkeypatch.setattr(bot.db, "upsert_user", upsert_qui_plante)

    casse = {"update_id": 200, "message": {"chat": {"id": 111, "type": "private"},
                                           "from": {"id": 111}, "text": "/start"}}
    t = FauxTransport([[casse, _msg(201, "/start")]])
    n = bot.boucle(conn, lambda: 0.006, t, max_tours=1)

    assert n == 1                                     # seul le 2e update est traité
    assert db.get_bot_meta(conn, "offset") == "202"    # l'offset avance quand même
    assert any("WatchTarget" in str(a.get("text")) for a in t.envoyes)
    sortie = capsys.readouterr().out
    assert "ignoré" in sortie and "200" in sortie      # journalisé


def test_boucle_persiste_l_offset_apres_chaque_update(tmp_path, monkeypatch):
    """L'offset doit être persisté APRÈS CHAQUE update, pas après tout le lot :
    si le process est tué au milieu d'un lot, seul l'update en cours doit être
    rejoué au redémarrage — pas tout le lot déjà consommé."""
    conn = _conn(tmp_path, monkeypatch)

    appels = []
    orig_set_bot_meta = db.set_bot_meta

    def espion(conn_, cle, valeur):
        if cle == "offset":
            appels.append(valeur)
        return orig_set_bot_meta(conn_, cle, valeur)

    monkeypatch.setattr(bot.db, "set_bot_meta", espion)

    class TransportQuiPlanteAuMilieu(FauxTransport):
        def envoyer(self, action):
            if action.get("chat_id") == 222:    # les actions du 2e update seulement
                raise RuntimeError("panne réseau simulée")
            return super().envoyer(action)

    lot = [_msg(300, "/start", uid=111), _msg(301, "/start", uid=222),
           _msg(302, "/start", uid=111)]
    t = TransportQuiPlanteAuMilieu([lot])
    bot.boucle(conn, lambda: 0.006, t, max_tours=1)

    # persisté après CHAQUE update (301, 302, 303) et non une seule fois (303)
    assert appels == ["301", "302", "303"]
    assert db.get_bot_meta(conn, "offset") == "303"


def test_boucle_rejoue_en_send_quand_un_edit_echoue(tmp_path, monkeypatch):
    """Telegram refuse d'éditer un message vieux de plus de 48 h (400). `executer`
    renvoie False mais personne ne le lisait : la navigation avait alors juste l'air
    cassée (le spinner s'éteint, rien ne s'affiche). `boucle` doit rejouer la même
    charge en `send` (nouveau message) quand un `edit` échoue — revue finale, point 2.
    """
    conn = _conn(tmp_path, monkeypatch)

    class TransportEditRefuse(FauxTransport):
        def envoyer(self, action):
            self.envoyes.append(action)
            return action.get("type") != "edit"     # tous les edit échouent

    # « list » depuis un vieux message → l'action produite est un edit
    cid = db.add_cible(conn, "rolex daytona", "Ma Daytona", telegram_id=111)
    cb = {"update_id": 400,
          "callback_query": {"id": "cb1", "data": "list",
                             "from": {"id": 111, "first_name": "Alice"},
                             "message": {"message_id": 10,
                                        "chat": {"id": 111, "type": "private"}}}}
    t = TransportEditRefuse([[cb]])
    bot.boucle(conn, lambda: 0.006, t, max_tours=1)

    edits = [a for a in t.envoyes if a["type"] == "edit"]
    sends_repli = [a for a in t.envoyes if a["type"] == "send"]
    assert len(edits) == 1
    assert len(sends_repli) == 1
    # même texte et même clavier, en nouveau message
    assert sends_repli[0]["text"] == edits[0]["text"]
    assert sends_repli[0]["keyboard"] == edits[0]["keyboard"]
    assert sends_repli[0]["chat_id"] == edits[0]["chat_id"]


def test_boucle_masque_le_token_dans_les_logs_reseau(tmp_path, monkeypatch, capsys):
    """Une exception réseau (ex. `requests.RequestException`) se stringifie
    généralement AVEC l'URL complète, donc avec le token en clair : il ne doit
    JAMAIS apparaître tel quel dans les logs."""
    conn = _conn(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "123:FAKETOKEN")
    monkeypatch.setattr(bot.time, "sleep", lambda s: None)   # pas d'attente réelle

    class TransportEnPanne:
        def get_updates(self, offset):
            raise RuntimeError(
                "Connection error to "
                "https://api.telegram.org/bot123:FAKETOKEN/getUpdates")

        def envoyer(self, action):
            raise AssertionError("ne doit pas être appelé")

    bot.boucle(conn, lambda: 0.006, TransportEnPanne(), max_tours=1)

    sortie = capsys.readouterr().out
    assert "123:FAKETOKEN" not in sortie
    assert "***" in sortie


def test_executer_construit_les_bons_appels(monkeypatch):
    """`executer` traduit chaque type d'action en méthode d'API Telegram."""
    appels = []

    def faux_post(url, data=None, timeout=None):
        appels.append((url.rsplit("/", 1)[-1], data))

        class R:
            ok = True
            status_code = 200

            @staticmethod
            def json():
                return {"ok": True}
        return R()

    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "123:TEST")
    monkeypatch.setattr(bot.requests, "post", faux_post)
    bot.executer({"type": "send", "chat_id": 1, "text": "hello", "keyboard": []})
    bot.executer({"type": "photo", "chat_id": 1, "photo": "u", "caption": "c",
                  "keyboard": []})
    bot.executer({"type": "edit", "chat_id": 1, "message_id": 2, "text": "t",
                  "keyboard": [[{"text": "b", "callback_data": "home"}]]})
    bot.executer({"type": "answer", "callback_id": "cb1", "text": ""})
    assert [a[0] for a in appels] == ["sendMessage", "sendPhoto", "editMessageText",
                                      "answerCallbackQuery"]
    # le clavier part en JSON sous reply_markup
    assert "callback_data" in appels[2][1]["reply_markup"]


def test_executer_reessaie_une_fois_apres_un_429(monkeypatch):
    """« Voir les montres » envoie 5 messages d'affilée sur un chat limité à ~1
    msg/s : en 429, `scripts/send_backlog_cible.py` lit `parameters.retry_after`,
    attend, et réessaie — `executer` doit suivre la MÊME convention plutôt que
    d'abandonner en laissant la page affichée à moitié (revue finale, point 4)."""
    appels = []
    attentes = []

    class R429:
        ok = False
        status_code = 429

        @staticmethod
        def json():
            return {"ok": False, "parameters": {"retry_after": 2}}

    class ROk:
        ok = True
        status_code = 200

        @staticmethod
        def json():
            return {"ok": True}

    def faux_post(url, data=None, timeout=None):
        appels.append(data)
        return R429() if len(appels) == 1 else ROk()

    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "123:TEST")
    monkeypatch.setattr(bot.requests, "post", faux_post)
    monkeypatch.setattr(bot.time, "sleep", lambda s: attentes.append(s))

    ok = bot.executer({"type": "send", "chat_id": 1, "text": "hello", "keyboard": []})

    assert ok is True
    assert len(appels) == 2                # un envoi raté, un réessai
    assert attentes and attentes[0] >= 2    # a bien attendu retry_after


def test_executer_journalise_l_echec_reseau_sans_fuite_de_token(monkeypatch, capsys):
    """Un envoi qui échoue ne doit pas être silencieux (service 24h/24 sans
    supervision) — et le message journalisé ne doit pas fuiter le token."""
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "123:FAKETOKEN")

    def post_en_panne(url, data=None, timeout=None):
        raise bot.requests.RequestException(f"boom sur {url}")

    monkeypatch.setattr(bot.requests, "post", post_en_panne)
    ok = bot.executer({"type": "send", "chat_id": 1, "text": "hello", "keyboard": []})
    assert ok is False

    sortie = capsys.readouterr().out
    assert "123:FAKETOKEN" not in sortie
    assert "***" in sortie
