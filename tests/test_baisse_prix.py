"""Alerte de BAISSE DE PRIX : une offre ANCIENNE (déjà en base, ≥ 2 points
d'historique) dont le prix boutique baisse redevient attractive → notification
Telegram au propriétaire de l'alerte qui matche, avec un TITRE DISTINCT (📉).

Une nouvelle montre n'alerte jamais ici (c'est le rôle de l'alerte d'arrivage) ;
la détection se fait sur prix_ttc (yen boutique) — insensible au taux de change.
"""
import backend.telegram as tg
from backend import config, db


def _conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    conn = db.connect()
    db.init_db(conn)
    return conn


def _setup(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "999")
    monkeypatch.setattr("backend.fx.get_rate", lambda: 0.0062)
    envoyes = []
    monkeypatch.setattr(tg, "envoyer",
                        lambda text, chat_id=None: envoyes.append((text, chat_id)) or True)
    return envoyes


def _w(prix):
    return {"uid": "B:116500LN:u1", "boutique": "B", "reference": "116500LN",
            "url": "https://ex.jp/w", "marque": "Rolex", "modele": "デイトナ",
            "prix_ttc": prix, "prix_detaxe_eur": prix * 0.0062, "raw": {}}


def _vieillir_premier_point(conn, uid):
    """Les deux upserts du test tombent dans la même seconde : on recule le
    1er point pour rendre l'ordre chronologique non ambigu (en prod, deux
    changements de prix sont séparés d'au moins un run de collecte)."""
    conn.execute("UPDATE price_history SET seen_at=? WHERE uid=? AND seen_at="
                 "(SELECT MIN(seen_at) FROM price_history WHERE uid=?)",
                 (db.iso_ago(2), uid, uid))
    conn.commit()


def test_baisse_sur_offre_ancienne_notifie_avec_titre_distinct(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    envoyes = _setup(monkeypatch)
    db.upsert_user(conn, 111, "Alice")
    db.add_cible(conn, "rolex daytona 116500LN", "Ma Daytona", telegram_id=111)
    db.upsert_watch(conn, _w(1_000_000))          # offre existante
    _vieillir_premier_point(conn, "B:116500LN:u1")
    depuis = db.iso_ago(1)
    db.upsert_watch(conn, _w(900_000))            # le prix BAISSE de 10 %
    n = tg.notifier_baisses(conn, depuis=depuis)
    assert n == 1
    texte, dest = envoyes[0]
    assert "Baisse de prix" in texte              # le TITRE distinct demandé
    assert "📉" in texte
    assert dest == 111                            # au propriétaire de l'alerte
    assert "Ma Daytona" in texte
    # règle « rendu sobre » : jamais de détaxé/EveryWatch/marge en public
    assert "détaxé" not in texte.lower() and "marge" not in texte.lower()
    # idempotent : re-run → rien
    assert tg.notifier_baisses(conn, depuis=depuis) == 0


def test_nouvelle_montre_ne_declenche_pas_de_baisse(tmp_path, monkeypatch):
    """Un seul point d'historique = nouvel arrivage → pas une « ancienne offre
    devenue attractive » : aucun message baisse (l'alerte d'arrivage s'en charge)."""
    conn = _conn(tmp_path, monkeypatch)
    envoyes = _setup(monkeypatch)
    db.add_cible(conn, "rolex daytona", "A", telegram_id=111)
    depuis = db.iso_ago(1)
    db.upsert_watch(conn, _w(1_000_000))
    assert tg.notifier_baisses(conn, depuis=depuis) == 0
    assert envoyes == []


def test_hausse_ou_variation_minime_ignorees(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    envoyes = _setup(monkeypatch)
    db.add_cible(conn, "rolex daytona", "A", telegram_id=111)
    db.upsert_watch(conn, _w(1_000_000))
    _vieillir_premier_point(conn, "B:116500LN:u1")
    depuis = db.iso_ago(1)
    db.upsert_watch(conn, _w(1_050_000))          # hausse
    assert tg.notifier_baisses(conn, depuis=depuis) == 0
    db.upsert_watch(conn, _w(1_048_000))          # −0,2 % : bruit, pas une affaire
    assert tg.notifier_baisses(conn, depuis=depuis) == 0
    assert envoyes == []


def test_baisse_sur_montre_vendue_ignoree(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    envoyes = _setup(monkeypatch)
    db.add_cible(conn, "rolex daytona", "A", telegram_id=111)
    db.upsert_watch(conn, _w(1_000_000))
    _vieillir_premier_point(conn, "B:116500LN:u1")
    depuis = db.iso_ago(1)
    baisse = _w(900_000)
    baisse["vendue"] = True                       # baisse… mais déjà vendue
    db.upsert_watch(conn, baisse)
    assert tg.notifier_baisses(conn, depuis=depuis) == 0
    assert envoyes == []
