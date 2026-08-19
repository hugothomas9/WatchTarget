"""notifier_cibles : anti-doublon face à un destinataire qui bloque le bot."""
from backend import config, db, telegram


def _conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    conn = db.connect()
    db.init_db(conn)
    return conn


def _prep(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "123:TEST")
    # L'alerte doit exister AVANT la montre : `add_cible` seed anti-spam marque
    # déjà « notifié » tout le stock DÉJÀ présent qui matche au moment de la
    # création (comportement d'un autre chantier en cours) — on veut ici tester
    # une montre nouvellement arrivée, qui doit donc bien déclencher un envoi.
    cid = db.add_cible(conn, "rolex daytona", "Ma Daytona", telegram_id=222)
    db.upsert_watch(conn, {
        "uid": "jackroad:126500LN:a", "boutique": "jackroad",
        "reference": "126500LN", "marque": "Rolex", "modele": "Daytona",
        "url": "https://ex/a", "prix_ttc": 3210000, "etat": "中古A"})
    from backend import fx
    monkeypatch.setattr(fx, "get_rate", lambda: 0.0060)
    from backend import verify_dispo
    monkeypatch.setattr(verify_dispo, "check", lambda boutique, url: "dispo")
    return conn, cid


class _R403:
    ok = False
    status_code = 403

    @staticmethod
    def json():
        return {"ok": False, "description": "Forbidden: bot was blocked by the user"}


class _ROk:
    ok = True
    status_code = 200

    @staticmethod
    def json():
        return {"ok": True}


def test_envoyer_renvoie_bloque_sur_403(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "123:TEST")
    monkeypatch.setattr(telegram.requests, "post", lambda *a, **k: _R403())
    resultat = telegram.envoyer("salut", chat_id=222)
    assert resultat is telegram.BLOQUE
    assert resultat is not True
    assert bool(resultat) is True     # truthy : "ne pas retenter", pas "échec transitoire"


def test_notifier_cibles_marque_notifie_sans_retenter_si_bloque(tmp_path, monkeypatch):
    """Un utilisateur public qui bloque le bot (403) ne doit pas faire retenter la
    notification indéfiniment : sans ce marquage, chaque run du pipeline referait un
    verify_dispo.check HTTP puis un envoi voué à l'échec, pour toujours (revue
    finale, point 5)."""
    conn, cid = _prep(tmp_path, monkeypatch)
    appels = []

    def faux_post(url, data=None, timeout=None):
        appels.append(data)
        return _R403()

    monkeypatch.setattr(telegram.requests, "post", faux_post)

    n = telegram.notifier_cibles(conn)

    assert n == 0                                   # rien de RÉELLEMENT envoyé
    assert len(appels) == 1                          # un seul essai, pas de boucle infinie
    # la montre est marquée notifiée pour cette cible : un 2e run ne retente pas
    n2 = telegram.notifier_cibles(conn)
    assert n2 == 0
    assert len(appels) == 1                          # aucun appel HTTP supplémentaire


def test_notifier_cibles_compte_les_envois_reussis(tmp_path, monkeypatch):
    conn, cid = _prep(tmp_path, monkeypatch)
    monkeypatch.setattr(telegram.requests, "post", lambda *a, **k: _ROk())
    n = telegram.notifier_cibles(conn)
    assert n == 1
    n2 = telegram.notifier_cibles(conn)
    assert n2 == 0            # anti-doublon : pas re-notifié


def test_notifier_cibles_echec_transitoire_retentera(tmp_path, monkeypatch):
    """Un échec réseau/générique (pas 403) reste transitoire : la montre n'est PAS
    marquée notifiée, contrairement au cas bloqué — un run ultérieur doit réessayer."""
    conn, cid = _prep(tmp_path, monkeypatch)

    class _R500:
        ok = False
        status_code = 500

        @staticmethod
        def json():
            return {"ok": False}

    monkeypatch.setattr(telegram.requests, "post", lambda *a, **k: _R500())
    n = telegram.notifier_cibles(conn)
    assert n == 0
    from backend.notify import _deja_notifie
    assert _deja_notifie(conn, "jackroad:126500LN:a", f"cible:{cid}") is False
