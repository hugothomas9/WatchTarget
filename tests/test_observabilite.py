"""Observabilité des connecteurs : sans elle, une boutique cassée (WAF, structure
changée) collecte 0 fiche EN SILENCE pendant des semaines. Chaque run enregistre
le rendement par boutique, et l'admin reçoit une alerte Telegram si une boutique
part en erreur ou tombe à zéro en mode full."""
from backend import config, db


def _conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    conn = db.connect()
    db.init_db(conn)
    return conn


def _fake_registry(monkeypatch, boutiques):
    from backend.connectors import registry
    monkeypatch.setattr(registry, "BOUTIQUES",
                        [{"boutique": n, "connector": n} for n, _ in boutiques])
    monkeypatch.setattr(registry, "CONNECTORS",
                        {n: cls for n, cls in boutiques})


class _Saine:
    def __init__(self, entry):
        self.nom = entry["boutique"]

    def collect(self, mode):
        yield {"uid": f"{self.nom}:R1:u1", "boutique": self.nom,
               "reference": "R1", "url": f"u-{self.nom}",
               "prix_ttc": 1_000_000, "raw": {}, "images": []}


class _Cassee:
    def __init__(self, entry):
        pass

    def collect(self, mode):
        raise ConnectionError("WAF 403")


def _setup(monkeypatch):
    monkeypatch.setattr("backend.fx.get_rate", lambda: 0.0062)
    monkeypatch.setattr(config, "DISCORD_WEBHOOK_URL", "")
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "999")
    envoyes = []
    import backend.telegram as tg
    monkeypatch.setattr(tg, "envoyer",
                        lambda text, chat_id=None: envoyes.append(text) or True)
    return envoyes


def test_stats_enregistrees_et_alerte_sur_erreur(tmp_path, monkeypatch):
    from backend import pipeline
    conn = _conn(tmp_path, monkeypatch)
    envoyes = _setup(monkeypatch)
    _fake_registry(monkeypatch, [("Bonne", _Saine), ("Cassée", _Cassee)])
    pipeline.run("full")
    rows = {r["boutique"]: r for r in conn.execute(
        "SELECT boutique, fetched, erreur FROM collecte_runs")}
    assert rows["Bonne"]["fetched"] == 1 and rows["Bonne"]["erreur"] is None
    assert "WAF 403" in rows["Cassée"]["erreur"]
    # l'admin est prévenu, avec le nom de la boutique en cause
    assert any("Cassée" in m for m in envoyes)


def test_alerte_chute_a_zero_en_full(tmp_path, monkeypatch):
    """Un connecteur qui ne LÈVE pas mais ne produit plus rien (structure HTML
    changée → 0 fiche « avec succès ») doit aussi alerter, par comparaison au
    run full précédent."""
    from backend import pipeline
    _conn(tmp_path, monkeypatch)
    envoyes = _setup(monkeypatch)

    class Vide:
        def __init__(self, entry):
            pass

        def collect(self, mode):
            return iter(())               # 0 fiche, sans erreur

    _fake_registry(monkeypatch, [("Boutique", _Saine)])
    pipeline.run("full")                  # run 1 : 1 fiche
    assert envoyes == []                  # tout va bien → pas d'alerte
    _fake_registry(monkeypatch, [("Boutique", Vide)])
    pipeline.run("full")                  # run 2 : chute à 0
    assert any("Boutique" in m and "0" in m for m in envoyes)


def test_incremental_zero_fiche_est_normal(tmp_path, monkeypatch):
    """En incrémental, 0 fiche = simplement pas de nouvel arrivage : AUCUNE
    alerte (sinon fausse alerte quotidienne sur chaque boutique calme)."""
    from backend import pipeline
    _conn(tmp_path, monkeypatch)
    envoyes = _setup(monkeypatch)

    class Calme:
        def __init__(self, entry):
            pass

        def collect(self, mode):
            return iter(())

    _fake_registry(monkeypatch, [("Calme", Calme)])
    pipeline.run("incremental")
    assert envoyes == []
