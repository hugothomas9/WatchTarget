"""Webhook Telegram (hébergement sans process always-on : Render free & co).

Le long polling exige un process allumé en permanence ; en webhook c'est Telegram
qui appelle l'API web à chaque update. Les deux modes partagent `bot.executer_update`
— seule la porte d'entrée change.
"""
from fastapi.testclient import TestClient

from backend import api, bot, config, db

SECRET = "s3cret-de-test"


def _client(tmp_path, monkeypatch, secret=SECRET):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "TELEGRAM_WEBHOOK_SECRET", secret)
    conn = db.connect()
    db.init_db(conn)
    return TestClient(api.app), conn


class FauxTransport:
    """Remplace l'API Telegram : enregistre les envois au lieu de les faire."""
    envoyes = []

    def envoyer(self, action):
        FauxTransport.envoyes.append(action)
        return True


def _sans_reseau(monkeypatch):
    FauxTransport.envoyes = []
    monkeypatch.setattr(bot, "Transport", FauxTransport)
    from backend import fx
    monkeypatch.setattr(fx, "get_rate", lambda: 0.006)
    return FauxTransport.envoyes


def _start(uid=111):
    return {"update_id": 1,
            "message": {"message_id": 10, "chat": {"id": uid, "type": "private"},
                        "from": {"id": uid, "first_name": "Alice"},
                        "text": "/start"}}


def test_webhook_traite_l_update_et_repond(tmp_path, monkeypatch):
    client, _conn = _client(tmp_path, monkeypatch)
    envoyes = _sans_reseau(monkeypatch)
    r = client.post("/api/telegram/webhook", json=_start(),
                    headers={"X-Telegram-Bot-Api-Secret-Token": SECRET})
    assert r.status_code == 200
    assert any("WatchTarget" in str(a.get("text")) for a in envoyes)


def test_webhook_refuse_un_mauvais_secret(tmp_path, monkeypatch):
    """L'URL du webhook peut fuiter (logs, historique) : sans vérification du
    secret, n'importe qui pourrait injecter de faux updates au nom d'autrui."""
    client, _conn = _client(tmp_path, monkeypatch)
    envoyes = _sans_reseau(monkeypatch)
    r = client.post("/api/telegram/webhook", json=_start(),
                    headers={"X-Telegram-Bot-Api-Secret-Token": "pas-le-bon"})
    assert r.status_code == 403
    assert envoyes == []
    assert client.post("/api/telegram/webhook", json=_start()).status_code == 403


def test_webhook_desactive_si_pas_de_secret(tmp_path, monkeypatch):
    """Sans TELEGRAM_WEBHOOK_SECRET (dev local en polling), l'endpoint n'existe
    pas : pas de porte ouverte par défaut."""
    client, _conn = _client(tmp_path, monkeypatch, secret="")
    _sans_reseau(monkeypatch)
    r = client.post("/api/telegram/webhook", json=_start(),
                    headers={"X-Telegram-Bot-Api-Secret-Token": ""})
    assert r.status_code == 404


def test_webhook_repond_200_meme_si_l_update_plante(tmp_path, monkeypatch):
    """Telegram REJOUE un update tant qu'il n'a pas de 200 : un update qui plante
    doit être journalisé et abandonné, sinon il bloque la file pour de bon."""
    client, _conn = _client(tmp_path, monkeypatch)
    _sans_reseau(monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("base injoignable")

    monkeypatch.setattr(bot, "traiter_update", boom)
    r = client.post("/api/telegram/webhook", json=_start(),
                    headers={"X-Telegram-Bot-Api-Secret-Token": SECRET})
    assert r.status_code == 200


def test_executer_update_replie_un_edit_rate_en_envoi(tmp_path, monkeypatch):
    """Partagé polling/webhook : un `edit` refusé (message > 48 h) est rejoué en
    nouveau message, sinon l'écran reste vide côté utilisateur."""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    conn = db.connect()
    db.init_db(conn)

    class RefuseLesEdits:
        def __init__(self):
            self.envoyes = []

        def envoyer(self, action):
            self.envoyes.append(action)
            return action["type"] != "edit"

    t = RefuseLesEdits()
    monkeypatch.setattr(bot, "traiter_update",
                        lambda *a, **k: [{"type": "edit", "chat_id": 1,
                                          "message_id": 2, "text": "x",
                                          "keyboard": None}])
    bot.executer_update(conn, {}, 0.006, t)
    assert [a["type"] for a in t.envoyes] == ["edit", "send"]
