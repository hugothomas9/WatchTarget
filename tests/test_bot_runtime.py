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
            "message": {"message_id": 10, "chat": {"id": uid},
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


def test_boucle_survit_a_un_update_qui_plante(tmp_path, monkeypatch):
    """Un update malformé ne doit pas tuer le bot ni bloquer l'offset."""
    conn = _conn(tmp_path, monkeypatch)
    casse = {"update_id": 200, "message": {"chat": {"id": 111},
                                           "from": {"id": 111}, "text": None}}
    t = FauxTransport([[casse, _msg(201, "/start")]])
    bot.boucle(conn, lambda: 0.006, t, max_tours=1)
    assert db.get_bot_meta(conn, "offset") == "202"
    assert any("WatchTarget" in str(a.get("text")) for a in t.envoyes)


def test_executer_construit_les_bons_appels(monkeypatch):
    """`executer` traduit chaque type d'action en méthode d'API Telegram."""
    appels = []

    def faux_post(url, data=None, timeout=None):
        appels.append((url.rsplit("/", 1)[-1], data))

        class R:
            ok = True

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
