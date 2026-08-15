"""Étape 2 : alertes par utilisateur (isolation) + auth Telegram via l'API."""
import hashlib
import hmac
import time

from fastapi.testclient import TestClient

from backend import api, config, db


def _conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    conn = db.connect()
    db.init_db(conn)
    return conn


def test_isolation_alertes_par_utilisateur(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    db.upsert_user(conn, 111, "Alice")
    db.upsert_user(conn, 222, "Bob")
    db.add_cible(conn, "rolex daytona", "A-daytona", telegram_id=111)
    db.add_cible(conn, "omega speedmaster", "B-speed", telegram_id=222)
    # chacun ne voit que la sienne
    a = db.list_cibles(conn, telegram_id=111)
    b = db.list_cibles(conn, telegram_id=222)
    assert len(a) == 1 and a[0]["mots_cles"] == "rolex daytona"
    assert len(b) == 1 and b[0]["mots_cles"] == "omega speedmaster"
    # admin voit tout
    assert len(db.list_cibles(conn)) == 2
    # Bob ne peut pas supprimer l'alerte d'Alice
    db.delete_cible(conn, a[0]["id"], telegram_id=222)
    assert len(db.list_cibles(conn, telegram_id=111)) == 1  # toujours là


def test_matches_par_utilisateur(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    db.upsert_watch(conn, {"uid": "B:126500LN:u", "boutique": "B",
                           "reference": "126500LN", "url": "u", "marque": "Rolex",
                           "modele": "デイトナ", "prix_detaxe_eur": 26000.0})
    db.add_cible(conn, "rolex daytona 126500LN", "A", telegram_id=111)
    assert len(db.get_cibles_matches(conn, telegram_id=111)) == 1
    assert db.get_cibles_matches(conn, telegram_id=222) == []   # Bob : rien


def _signed(payload, token):
    data = {k: str(v) for k, v in payload.items() if k != "hash"}
    check = "\n".join(f"{k}={data[k]}" for k in sorted(data))
    secret = hashlib.sha256(token.encode()).digest()
    payload["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return payload


def test_auth_flow_api(tmp_path, monkeypatch):
    _conn(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "123:TESTTOKEN")
    client = TestClient(api.app)
    # non connecté
    assert client.get("/api/me").json() == {"user": None}
    # login widget valide
    payload = _signed({"id": 111, "first_name": "Alice",
                       "auth_date": int(time.time())}, "123:TESTTOKEN")
    r = client.post("/api/auth/telegram", json=payload)
    assert r.status_code == 200 and r.json()["telegram_id"] == 111
    # session posée → /api/me connecté, création d'alerte rattachée à 111
    assert client.get("/api/me").json()["user"]["telegram_id"] == 111
    client.post("/api/alertes", json={"mots_cles": "rolex daytona"})
    assert len(client.get("/api/alertes").json()) == 1
    # signature invalide → 401
    assert client.post("/api/auth/telegram",
                       json={"id": 9, "auth_date": int(time.time()),
                             "hash": "bad"}).status_code == 401
