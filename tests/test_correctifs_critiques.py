"""Correctifs critiques post-revue (2026-08) — un bloc de tests par correctif.

1. Portabilité SQL : les TTL de fraîcheur (fresh_*) et le filtre d'âge de
   verify_dispo.run doivent marcher sur SQLite ET PostgreSQL (datetime('now',?)
   n'existe pas en PG). Ces tests s'exécutent sur les deux via TEST_DATABASE_URL.
2. Auth : en prod (LOCAL_ADMIN=False), un anonyme ne voit/crée/supprime AUCUNE
   alerte et ne déclenche pas de collecte. En local (LOCAL_ADMIN=True), l'usage
   mono-utilisateur historique est préservé.
3. verify GMT : la vérification passe par le transport curl_cffi (comme le
   connecteur) au lieu de requests (403 WAF) ; un résultat INCONNU met à jour
   last_seen pour ne pas re-fetch la même fiche à chaque run.
4. pipeline.run : une boutique en panne n'empêche pas la collecte des autres.
"""
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


# ---------------------------------------------------------------- 1. TTL portables
def test_fresh_market_refs_succes_et_echec_recents(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    db.upsert_market_price(conn, "R1", {"median_eur": 1000, "p25_eur": 900,
                                        "p75_eur": 1100, "n_annonces": 5})
    db.upsert_market_price(conn, "R2", None, erreur="timeout")
    fresh = db.fresh_market_refs(conn, 30)
    assert "R1" in fresh          # succès frais → dans le TTL plein
    assert "R2" in fresh          # échec frais → gelé 2 jours quand même
    # TTL 0 : le succès n'est plus « frais », l'échec garde son gel fixe de 2 j
    assert db.fresh_market_refs(conn, 0) == {"R2"}


def test_fresh_wc_refs_ttl(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    db.upsert_market_price(conn, "R1", {"median_eur": 1000, "p25_eur": 900,
                                        "p75_eur": 1100, "n_annonces": 5})
    db.upsert_wc(conn, "R1", 12.0, 4.2, "https://wc/x")
    assert "R1" in db.fresh_wc_refs(conn, 30)
    assert db.fresh_wc_refs(conn, 0) == set()


def test_fresh_ew_keys_ttl_portable(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    db.upsert_ew_price(conn, "R1", "silver", "steel",
                       {"ew_median_eur": 1000, "ew_n_sales": 3})
    db.upsert_ew_price(conn, "R2", "", "", None, erreur="aucune vente")
    fresh = db.fresh_ew_keys(conn, 30)
    assert ("R1", "silver", "steel") in fresh
    assert ("R2", "", "") in fresh
    assert db.fresh_ew_keys(conn, 0) == {("R2", "", "")}


def test_verify_run_filtre_age_portable(tmp_path, monkeypatch):
    """Le filtre older_than_days doit sélectionner les fiches ANCIENNES et sauter
    les fraîches — sur les deux moteurs. Aucun réseau : check est monkeypatché."""
    from backend import verify_dispo
    conn = _conn(tmp_path, monkeypatch)
    db.upsert_watch(conn, {"uid": "B:R1:u1", "boutique": "B", "reference": "R1",
                           "url": "u1", "prix_ttc": 100})
    db.upsert_watch(conn, {"uid": "B:R2:u2", "boutique": "B", "reference": "R2",
                           "url": "u2", "prix_ttc": 100})
    # R2 devient « ancienne » (10 jours), R1 reste fraîche (last_seen = now)
    conn.execute("UPDATE watches SET last_seen=? WHERE uid=?",
                 (db.iso_ago(10), "B:R2:u2"))
    conn.commit()
    checked = []

    def fake_check(boutique, url):
        checked.append(url)
        return "vendue"

    monkeypatch.setattr(verify_dispo, "check", fake_check)
    counts = verify_dispo.run(older_than_days=7)
    assert checked == ["u2"]              # seule l'ancienne est revérifiée
    assert counts["vendue"] == 1


# ---------------------------------------------------------------- 2. Auth alertes
def _signed(payload: dict, token: str) -> dict:
    data = {k: str(v) for k, v in payload.items() if k != "hash"}
    check = "\n".join(f"{k}={data[k]}" for k in sorted(data))
    secret = hashlib.sha256(token.encode()).digest()
    payload["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return payload


def _login(client, monkeypatch, uid: int):
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "123:TESTTOKEN")
    payload = _signed({"id": uid, "first_name": f"U{uid}",
                       "auth_date": int(time.time())}, "123:TESTTOKEN")
    r = client.post("/api/auth/telegram", json=payload)
    assert r.status_code == 200


def test_prod_anonyme_sans_acces_aux_alertes(tmp_path, monkeypatch):
    """En prod, un visiteur SANS session ne liste pas, ne crée pas, ne supprime
    pas d'alertes — et ne voit pas les cibles des autres."""
    conn = _conn(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "LOCAL_ADMIN", False, raising=False)
    db.upsert_user(conn, 111, "Alice")
    cid = db.add_cible(conn, "rolex daytona", "A-daytona", telegram_id=111)
    db.upsert_watch(conn, {"uid": "B:116500LN:u", "boutique": "B",
                           "reference": "116500LN", "url": "u", "marque": "Rolex",
                           "modele": "デイトナ", "prix_detaxe_eur": 26000.0})
    client = TestClient(api.app, base_url="https://testserver")
    assert client.get("/api/alertes").json() == []            # ne voit rien
    assert client.get("/api/cibles").json() == []             # pas de matches
    assert client.post("/api/alertes",
                       json={"mots_cles": "omega"}).status_code == 401
    assert client.delete(f"/api/alertes/{cid}").status_code == 401
    # l'alerte d'Alice est intacte
    assert len(db.list_cibles(conn, telegram_id=111)) == 1


def test_prod_connecte_gere_uniquement_ses_alertes(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "LOCAL_ADMIN", False, raising=False)
    db.upsert_user(conn, 222, "Bob")
    autre = db.add_cible(conn, "patek nautilus", "B-patek", telegram_id=222)
    client = TestClient(api.app, base_url="https://testserver")
    _login(client, monkeypatch, 111)
    cid = client.post("/api/alertes",
                      json={"mots_cles": "rolex daytona"}).json()["id"]
    assert [a["id"] for a in client.get("/api/alertes").json()] == [cid]
    # supprimer l'alerte d'un AUTRE → sans effet
    client.delete(f"/api/alertes/{autre}")
    assert len(db.list_cibles(conn, telegram_id=222)) == 1
    # supprimer la sienne → OK
    client.delete(f"/api/alertes/{cid}")
    assert client.get("/api/alertes").json() == []


def test_local_admin_conserve_lacces_historique(tmp_path, monkeypatch):
    """En local mono-utilisateur (SQLite, pas de login possible), l'accès sans
    session garde les droits admin — le flux historique d'Hugo ne casse pas."""
    conn = _conn(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "LOCAL_ADMIN", True, raising=False)
    db.add_cible(conn, "rolex daytona", "locale")
    client = TestClient(api.app, base_url="https://testserver")
    assert len(client.get("/api/alertes").json()) == 1
    assert client.post("/api/alertes",
                       json={"mots_cles": "omega"}).status_code == 200


def test_prod_collecte_reservee_admin(tmp_path, monkeypatch):
    _conn(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "LOCAL_ADMIN", False, raising=False)
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "111")
    lances = []
    monkeypatch.setattr(api.pipeline, "run",
                        lambda mode: lances.append(mode) or {"fetched": 0, "new": 0})
    client = TestClient(api.app, base_url="https://testserver")
    # anonyme → refusé, pipeline jamais lancé
    assert client.post("/api/collecte").status_code == 401
    # utilisateur lambda connecté → refusé aussi (réservé admin)
    _login(client, monkeypatch, 222)
    assert client.post("/api/collecte").status_code == 403
    assert lances == []
    # admin (chat_id configuré) → autorisé
    client2 = TestClient(api.app, base_url="https://testserver")
    _login(client2, monkeypatch, 111)
    assert client2.post("/api/collecte").status_code == 200
    assert lances == ["incremental"]


# ---------------------------------------------------------------- 3. verify GMT
class _FakeResp:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


def test_check_gmt_passe_par_le_transport_impersonate(monkeypatch):
    """GMT est derrière un WAF qui bloque requests : check() doit utiliser le
    même transport curl_cffi que le connecteur (via _imp_get)."""
    from backend import verify_dispo, http_client

    def requests_interdit(*a, **kw):
        raise AssertionError("verify GMT ne doit PAS passer par http_client")

    monkeypatch.setattr(http_client, "get_text", requests_interdit)
    html = '<script type="application/ld+json">{"availability":"https://schema.org/InStock"}</script>'
    monkeypatch.setattr(verify_dispo, "_imp_get",
                        lambda url: _FakeResp(200, html), raising=False)
    assert verify_dispo.check("GMT", "https://www.gmt-j.com/item/x") == "dispo"
    monkeypatch.setattr(verify_dispo, "_imp_get",
                        lambda url: _FakeResp(404), raising=False)
    assert verify_dispo.check("GMT", "https://www.gmt-j.com/item/y") == "retiree"


def test_verify_inconnu_met_a_jour_last_seen(tmp_path, monkeypatch):
    """Une fiche au statut INCONNU doit voir son last_seen avancer : sinon elle
    est re-sélectionnée et re-téléchargée à CHAQUE passe, pour toujours."""
    from backend import verify_dispo
    conn = _conn(tmp_path, monkeypatch)
    db.upsert_watch(conn, {"uid": "B:R1:u1", "boutique": "B", "reference": "R1",
                           "url": "u1", "prix_ttc": 100})
    vieux = db.iso_ago(30)
    conn.execute("UPDATE watches SET last_seen=? WHERE uid=?", (vieux, "B:R1:u1"))
    conn.commit()
    monkeypatch.setattr(verify_dispo, "check", lambda b, u: None)   # indéterminé
    verify_dispo.run(older_than_days=None)
    row = conn.execute("SELECT status, last_seen FROM watches WHERE uid=?",
                       ("B:R1:u1",)).fetchone()
    assert row["status"] == "dispo"          # le statut n'est PAS dégradé
    assert row["last_seen"] > vieux          # mais la fiche ne sera pas re-fetchée


# ---------------------------------------------------------------- 4. pipeline isolé
def test_pipeline_boutique_en_panne_nisole_pas_les_autres(tmp_path, monkeypatch):
    """Un connecteur qui explose (403 WAF, site down) ne doit pas empêcher la
    collecte des boutiques suivantes."""
    from backend import pipeline
    from backend.connectors import registry
    _conn(tmp_path, monkeypatch)
    monkeypatch.setattr("backend.fx.get_rate", lambda: 0.0062)
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(config, "DISCORD_WEBHOOK_URL", "")

    class Cassee:
        def __init__(self, entry):
            pass

        def collect(self, mode):
            raise ConnectionError("site down dès brands_to_scan")

    class Saine:
        def __init__(self, entry):
            pass

        def collect(self, mode):
            yield {"uid": "Saine:R1:u1", "boutique": "Saine", "reference": "R1",
                   "url": "u1", "prix_ttc": 1_000_000, "raw": {}, "images": []}

    monkeypatch.setattr(registry, "BOUTIQUES", [
        {"boutique": "Cassée", "connector": "cassee"},
        {"boutique": "Saine", "connector": "saine"},
    ])
    monkeypatch.setattr(registry, "CONNECTORS",
                        {"cassee": Cassee, "saine": Saine})
    res = pipeline.run("full")
    assert res == {"fetched": 1, "new": 1}    # la boutique saine a bien collecté


# ------------------------------------------- 5. durcissements issus de la relecture
def test_pipeline_transaction_empoisonnee_rollback(tmp_path, monkeypatch):
    """Une erreur DB au milieu d'une boutique (deadlock, requête invalide…)
    empoisonne la transaction PostgreSQL : sans rollback, TOUTES les boutiques
    suivantes échouent en InFailedSqlTransaction. Le handler doit rollback."""
    from backend import pipeline
    from backend.connectors import registry
    _conn(tmp_path, monkeypatch)
    monkeypatch.setattr("backend.fx.get_rate", lambda: 0.0062)
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(config, "DISCORD_WEBHOOK_URL", "")

    class Boutique:
        def __init__(self, entry):
            self.nom = entry["boutique"]

        def collect(self, mode):
            yield {"uid": f"{self.nom}:R1:u1", "boutique": self.nom,
                   "reference": "R1", "url": f"u-{self.nom}",
                   "prix_ttc": 1_000_000, "raw": {}, "images": []}

    reel = db.upsert_watch
    etat = {"explose": True}

    def upsert_explosif(conn, w):
        if etat.pop("explose", False):     # 1er upsert : erreur SQL serveur
            conn.execute("SELECT fonction_inexistante()")
        return reel(conn, w)

    monkeypatch.setattr(pipeline.db, "upsert_watch", upsert_explosif)
    monkeypatch.setattr(registry, "BOUTIQUES", [
        {"boutique": "Sabotée", "connector": "b"},
        {"boutique": "Après", "connector": "b"},
    ])
    monkeypatch.setattr(registry, "CONNECTORS", {"b": Boutique})
    res = pipeline.run("full")
    assert res["new"] == 1                 # la boutique APRÈS l'erreur a collecté


def test_session_refusee_sans_token_configure(monkeypatch):
    """Token bot absent/vide → AUCUN cookie ne doit être accepté (sinon la clé
    HMAC vide est calculable par n'importe qui → forge de session admin)."""
    from backend import auth_telegram as auth
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "123:TESTTOKEN")
    cookie = auth.creer_session(111)
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "")
    import hashlib as _h, hmac as _hm
    forge = "111." + _hm.new(b"", b"111", _h.sha256).hexdigest()
    assert auth.lire_session(forge) is None
    assert auth.lire_session(cookie) is None


def test_prod_favori_reserve_aux_connectes(tmp_path, monkeypatch):
    """En prod, toggler un favori déclenche du scraping (analyze) : un anonyme
    ne doit pas pouvoir marteler cet endpoint (mêmes raisons que /api/collecte)."""
    conn = _conn(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "LOCAL_ADMIN", False, raising=False)
    db.upsert_watch(conn, {"uid": "B:R1:u1", "boutique": "B", "reference": "R1",
                           "url": "u1", "prix_ttc": 100})
    client = TestClient(api.app, base_url="https://testserver")
    assert client.post("/api/favoris/B:R1:u1").status_code == 401
    _login(client, monkeypatch, 111)
    monkeypatch.setattr(api, "_analyze_favori_bg", lambda uid: None)
    assert client.post("/api/favoris/B:R1:u1").status_code == 200


def test_suppression_alerte_inexistante_renvoie_404(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "LOCAL_ADMIN", False, raising=False)
    db.upsert_user(conn, 222, "Bob")
    autre = db.add_cible(conn, "patek", "B", telegram_id=222)
    client = TestClient(api.app, base_url="https://testserver")
    _login(client, monkeypatch, 111)
    assert client.delete("/api/alertes/99999").status_code == 404
    assert client.delete(f"/api/alertes/{autre}").status_code == 404   # pas à lui


def test_cibles_orphelines_adoptees_par_ladmin(tmp_path, monkeypatch):
    """Les alertes créées en local AVANT la migration (telegram_id NULL) doivent
    être rattachées à l'admin au démarrage : sinon en prod elles deviennent
    invisibles et insupprimables (fantômes qui notifient à vie)."""
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "555")
    conn = _conn(tmp_path, monkeypatch)
    conn.execute("INSERT INTO cibles (mots_cles, libelle, actif, cree_le) "
                 "VALUES ('rolex daytona', 'orpheline', 1, ?)", (db.now_iso(),))
    conn.commit()
    db.init_db(conn)                       # ré-init = adoption
    rows = db.list_cibles(conn, telegram_id=555)
    assert [c["libelle"] for c in rows] == ["orpheline"]
