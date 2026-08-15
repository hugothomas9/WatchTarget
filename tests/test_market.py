from backend import market, db, config


def test_parse_prices_formats_francais():
    # formats réels Chrono24 : espace fine (U+202F), nbsp, point de milliers
    txt = "2\u202f747\xa0\u20ac | 3 390 \u20ac | 2.506 \u20ac | 3\u202f500,00 \u20ac"
    prices = market.parse_prices_eur(txt)
    assert 2747.0 in prices
    assert 3390.0 in prices
    assert 2506.0 in prices
    assert 3500.0 in prices


def test_parse_prices_ignore_bruit():
    # montants hors bande raisonnable (le scoping fin = rôle des sélecteurs CSS)
    assert market.parse_prices_eur("999999999 \u20ac") == []
    assert market.parse_prices_eur("50 \u20ac") == []


def test_stats_median_p25_p75():
    s = market.stats_from_prices([2500, 2700, 2900, 3100, 3300])
    assert s["median_eur"] == 2900
    assert s["p25_eur"] <= 2700
    assert s["p75_eur"] >= 3100
    assert s["n_annonces"] == 5


def test_stats_none_si_trop_peu():
    assert market.stats_from_prices([3000]) is None
    assert market.stats_from_prices([]) is None


def test_stats_coupe_les_extremes():
    prices = [2800] * 10 + [99000]   # une annonce fantaisiste
    s = market.stats_from_prices(prices)
    assert s["median_eur"] == 2800
    assert s["p75_eur"] < 10000


def make_conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    conn = db.connect()
    db.init_db(conn)
    return conn


def test_opportunites_jointure_et_seuil(tmp_path, monkeypatch):
    conn = make_conn(tmp_path, monkeypatch)
    w = {"uid": "B:32630405001001:u1", "boutique": "B",
         "reference": "326.30.40.50.01.001", "url": "u1",
         "prix_ttc": 550000, "prix_detaxe_eur": 2700.0}
    db.upsert_watch(conn, w)
    db.upsert_watch(conn, {**w, "uid": "B:X:u2", "url": "u2",
                           "reference": "999.88.77", "prix_detaxe_eur": 2700.0})
    # marché : la 326… vaut 3600 € médian avec 20 annonces → spread 900
    db.upsert_market_price(conn, "32630405001001",
                           {"median_eur": 3600, "p25_eur": 3300,
                            "p75_eur": 3900, "n_annonces": 20})
    opps = db.get_opportunities(conn, spread_min=700, liq_min=5)
    assert len(opps) == 1
    assert opps[0]["reference"] == "326.30.40.50.01.001"
    assert opps[0]["spread_eur"] == 900.0
    # filtre marque (la montre W a marque="Rolex" par défaut ? sinon on la fixe)
    conn.execute("UPDATE watches SET marque='Rolex' WHERE uid=?", (w["uid"],))
    assert len(db.get_opportunities(conn, 700, 5, marque="Rolex")) == 1
    assert db.get_opportunities(conn, 700, 5, marque="Omega") == []
    # seuil plus haut → rien
    assert db.get_opportunities(conn, spread_min=1000, liq_min=5) == []
    # liquidité insuffisante → rien
    db.upsert_market_price(conn, "32630405001001",
                           {"median_eur": 3600, "p25_eur": 3300,
                            "p75_eur": 3900, "n_annonces": 2})
    assert db.get_opportunities(conn, spread_min=700, liq_min=5) == []


def test_fresh_market_refs(tmp_path, monkeypatch):
    conn = make_conn(tmp_path, monkeypatch)
    db.upsert_market_price(conn, "REF1", {"median_eur": 1000, "n_annonces": 5})
    assert "REF1" in db.fresh_market_refs(conn, 30)
    assert "REF1" not in db.fresh_market_refs(conn, 0)
