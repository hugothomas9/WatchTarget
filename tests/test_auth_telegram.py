"""Auth Telegram : vérification de signature (Login Widget) + session signée."""
import hashlib
import hmac
import time

from backend import auth_telegram as auth, config


def _signer(payload: dict, token: str) -> str:
    data = {k: str(v) for k, v in payload.items() if k != "hash"}
    check = "\n".join(f"{k}={data[k]}" for k in sorted(data))
    secret = hashlib.sha256(token.encode()).digest()
    return hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()


def test_widget_valide(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "123:TESTTOKEN")
    payload = {"id": 111111111, "first_name": "Hugo", "username": "hugo",
               "auth_date": int(time.time())}
    payload["hash"] = _signer(payload, "123:TESTTOKEN")
    u = auth.verifier_widget(payload)
    assert u == {"telegram_id": 111111111, "first_name": "Hugo", "username": "hugo"}


def test_widget_signature_falsifiee(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "123:TESTTOKEN")
    payload = {"id": 42, "first_name": "X", "auth_date": int(time.time()),
               "hash": "deadbeef"}
    assert auth.verifier_widget(payload) is None


def test_widget_perime(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "123:TESTTOKEN")
    payload = {"id": 42, "first_name": "X", "auth_date": int(time.time()) - 100000}
    payload["hash"] = _signer(payload, "123:TESTTOKEN")
    assert auth.verifier_widget(payload) is None


def test_session_aller_retour(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "123:TESTTOKEN")
    cookie = auth.creer_session(111111111)
    assert auth.lire_session(cookie) == 111111111
    # cookie trafiqué → rejeté
    assert auth.lire_session("111111111.mauvaise_signature") is None
    assert auth.lire_session(None) is None
