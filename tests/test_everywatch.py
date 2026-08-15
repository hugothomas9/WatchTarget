"""EveryWatch : parsing des ventes réelles, logique de matching (pool cadran+matière,
outliers écartés), et re-pricing des opportunités (EW référence, Chrono24 secours)."""
import json

from backend import db, config
from backend.market_everywatch import EveryWatchSource

# deux ventes silver (dont la sous-variante -0009), une white, une « Missed EST »
# (enchère sous l'estimation) et une restée 572 jours (bradée) → outliers
_CARD = """
<a title="Rolex Lady-Datejust {rn} 28mm Stainless steel {dial}">
  <span data-prices="{{&quot;netPayableEur&quot;:{eur}}}"></span>
  <div>{rn} Sold / Removed Apr, 2026 {extra}</div>
</a>"""
_HTML = "".join([
    _CARD.format(rn="279384RBR-0009", dial="Silver", eur=19000, extra=""),
    _CARD.format(rn="279384RBR-0009", dial="Silver", eur=19500, extra=""),
    _CARD.format(rn="279384RBR-0011", dial="White", eur=22000, extra=""),
    _CARD.format(rn="279384RBR-0007", dial="Silver", eur=8000,
                 extra="Missed EST by 30%"),
    _CARD.format(rn="279384RBR-0003", dial="Silver", eur=9000,
                 extra="Listed For 572 Days"),
])


class _FakeResp:
    def __init__(self, text):
        self.text = text


def _src(monkeypatch, html=_HTML, variants=None):
    src = EveryWatchSource()
    monkeypatch.setattr(src, "_sess", lambda: type(
        "S", (), {"get": lambda self, url, **kw: _FakeResp(html)})())
    if variants is not None:
        monkeypatch.setattr(src, "search", lambda ref: variants)
    return src


def test_sold_cards_parse():
    src = _src(__import__("pytest").MonkeyPatch())
    cards = src.sold_cards(["x"])
    assert len(cards) == 5
    c = cards[0]
    assert c["eur"] == 19000 and c["dial"] == "silver" and c["material"] == "steel"
    assert c["variant"] == "279384RBR-0009"
    assert c["date"] == "Apr 2026"
    assert cards[3]["missed_est"] is True
    assert cards[4]["days"] == 572


def test_stats_filtre_cadran_et_outliers(monkeypatch):
    """silver+steel → seules les 2 ventes -0009 restent (Missed EST et 572j écartées,
    white ignorée) → une seule sous-variante → stats dessus, sans image."""
    src = _src(monkeypatch, variants=[{"ref_num": "279384RBR-0009", "id": "1",
                                       "image": ""}])
    monkeypatch.setattr("time.sleep", lambda s: None)
    s = src.stats("279384RBR", cadran="シルバー", matiere="ステンレス")
    assert s["ew_matched_by"] == "dial+material"
    assert s["ew_variant"] == "279384RBR-0009"
    assert s["ew_n_sales"] == 2
    assert 19000 <= s["ew_median_eur"] <= 19500
    # dernière vente = 1re carte du pool (les plus récentes d'abord chez EW)
    assert s["ew_last_eur"] == 19000
    assert s["ew_last_sale"] == "Apr 2026"
    assert "ew_sales_12m" in s and isinstance(s["ew_sales_12m"], int)


def test_months_ago_et_liquidite_12m():
    from backend.market_everywatch import _months_ago
    from datetime import datetime
    mois = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep",
            "Oct", "Nov", "Dec"]
    now = datetime.now()
    assert _months_ago(f"{mois[now.month]} {now.year}") == 0    # ce mois-ci
    assert _months_ago("Jan 2020") > 12                          # vieux (> 1 an)
    assert _months_ago("bidon") is None


def test_stats_sans_cadran_agregat_ref(monkeypatch):
    """cadran inconnu → agrégat réf (les 3 ventes saines, outliers toujours écartés)."""
    src = _src(monkeypatch, variants=[{"ref_num": "279384RBR-0009", "id": "1",
                                       "image": ""}])
    monkeypatch.setattr("time.sleep", lambda s: None)
    s = src.stats("279384RBR")
    assert s["ew_n_sales"] == 3          # 19000, 19500, 22000
    assert s["ew_matched_by"] in ("ref", "dial+material")


def _conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    conn = db.connect()
    db.init_db(conn)
    return conn


def test_opportunites_preferent_prix_vendu_reel(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    db.upsert_watch(conn, {
        "uid": "B:279384RBR:u1", "boutique": "B", "reference": "279384RBR",
        "url": "u1", "prix_ttc": 2000000, "prix_detaxe_eur": 12000.0,
        "raw": {"cadran": "シルバー", "matiere": "ステンレス"}})
    # Chrono24 (prix affichés, optimistes) : médiane 21000
    db.upsert_market_price(conn, "279384RBR",
                           {"median_eur": 21000, "p25_eur": 19000,
                            "p75_eur": 23000, "n_annonces": 50})
    # sans EW → spread sur Chrono24
    o = db.get_opportunities(conn, 700, 5)[0]
    assert o["prix_ref_source"] == "chrono24"
    assert o["spread_eur"] == 9000.0
    # avec EW (prix vendus réels, silver/steel) : médiane 19000 → spread resserré
    db.upsert_ew_price(conn, "279384RBR", "silver", "steel",
                       {"ew_median_eur": 19000, "ew_p25_eur": 18500,
                        "ew_p75_eur": 19600, "ew_n_sales": 12,
                        "ew_matched_by": "variant-image",
                        "ew_variant": "279384RBR-0009",
                        "ew_last_eur": 19456, "ew_last_sale": "Jun 2026"})
    o = db.get_opportunities(conn, 700, 5)[0]
    assert o["prix_ref_source"] == "everywatch"
    assert o["spread_eur"] == 7000.0                 # 19000 − 12000
    assert o["spread_p25_eur"] == 6500.0             # P25 EW
    assert o["ew_variant"] == "279384RBR-0009"
    assert o["ew_last_eur"] == 19456                 # dernière vente réelle
    assert o["ew_last_sale"] == "Jun 2026"
    assert o["median_eur"] == 21000                  # C24 reste dispo (tooltip)


def test_opportunite_everywatch_SANS_chrono24(tmp_path, monkeypatch):
    """Nouveau comportement : une montre avec prix vendu réel EveryWatch mais SANS
    Chrono24 doit APPARAÎTRE (avant, l'absence de Chrono24 la masquait)."""
    conn = _conn(tmp_path, monkeypatch)
    db.upsert_watch(conn, {
        "uid": "B:116710BLNR:u1", "boutique": "B", "reference": "116710BLNR",
        "url": "u1", "prix_ttc": 1800000, "prix_detaxe_eur": 12000.0,
        "raw": {"cadran": "ブラック", "matiere": "ステンレス"}})
    # AUCUN market_price Chrono24 — seulement EveryWatch
    db.upsert_ew_price(conn, "116710BLNR", "black", "steel",
                       {"ew_median_eur": 18000, "ew_p25_eur": 17000,
                        "ew_p75_eur": 19000, "ew_n_sales": 40, "ew_sales_12m": 30,
                        "ew_matched_by": "dial+material", "ew_variant": "",
                        "ew_last_eur": 18200, "ew_last_sale": "Jun 2026"})
    opps = db.get_opportunities(conn, 700, 5)
    assert len(opps) == 1
    o = opps[0]
    assert o["prix_ref_source"] == "everywatch"
    assert o["spread_eur"] == 6000.0                 # 18000 − 12000, sans Chrono24
    assert o["median_eur"] is None                   # pas de Chrono24 → None
    assert o["ew_sales_12m"] == 30 and o["ew_liquidity"] == 10   # liquidité EW


def test_opportunite_ew_illiquide_ecartee(tmp_path, monkeypatch):
    """EveryWatch avec trop peu de ventes réelles (< liq_min) et pas de Chrono24
    liquide → écartée (pas de marché de revente fiable)."""
    conn = _conn(tmp_path, monkeypatch)
    db.upsert_watch(conn, {
        "uid": "B:RARE:u1", "boutique": "B", "reference": "RARE1",
        "url": "u1", "prix_ttc": 1000000, "prix_detaxe_eur": 5000.0, "raw": {}})
    db.upsert_ew_price(conn, "RARE1", "", "",
                       {"ew_median_eur": 9000, "ew_p25_eur": 8000, "ew_p75_eur": 10000,
                        "ew_n_sales": 2, "ew_sales_12m": 1, "ew_matched_by": "ref",
                        "ew_variant": ""})
    assert db.get_opportunities(conn, 700, 5) == []   # 2 ventes < liq_min=5


def test_opportunites_config_differente_fallback_agregat(tmp_path, monkeypatch):
    """La ligne EW d'un AUTRE cadran ne doit PAS s'appliquer ; l'agrégat réf
    (dial='') sert de secours."""
    conn = _conn(tmp_path, monkeypatch)
    db.upsert_watch(conn, {
        "uid": "B:126000:u2", "boutique": "B", "reference": "126000",
        "url": "u2", "prix_ttc": 1500000, "prix_detaxe_eur": 9000.0,
        "raw": {"cadran": "ターコイズブルー", "matiere": "ステンレス"}})
    db.upsert_market_price(conn, "126000",
                           {"median_eur": 12000, "p25_eur": 11000,
                            "p75_eur": 13000, "n_annonces": 30})
    # EW pricé pour le cadran GREEN uniquement → ne s'applique pas à la turquoise
    db.upsert_ew_price(conn, "126000", "green", "steel",
                       {"ew_median_eur": 9800, "ew_p25_eur": 9300,
                        "ew_p75_eur": 10200, "ew_n_sales": 16,
                        "ew_matched_by": "dial+material", "ew_variant": ""})
    o = db.get_opportunities(conn, 700, 5)[0]
    assert o["prix_ref_source"] == "chrono24"
    # agrégat réf (dial='') → s'applique en secours
    db.upsert_ew_price(conn, "126000", "", "",
                       {"ew_median_eur": 11000, "ew_p25_eur": 10000,
                        "ew_p75_eur": 14000, "ew_n_sales": 40,
                        "ew_matched_by": "ref", "ew_variant": ""})
    o = db.get_opportunities(conn, 700, 5)[0]
    assert o["prix_ref_source"] == "everywatch"
    assert o["spread_eur"] == 2000.0


def test_fresh_ew_keys(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    db.upsert_ew_price(conn, "R1", "silver", "steel",
                       {"ew_median_eur": 1000, "ew_n_sales": 3})
    db.upsert_ew_price(conn, "R2", "", "", None, erreur="aucune vente")
    fresh = db.fresh_ew_keys(conn, 30)
    assert ("R1", "silver", "steel") in fresh
    assert ("R2", "", "") in fresh          # échec frais 2 jours quand même
    assert db.fresh_ew_keys(conn, 0) == {("R2", "", "")}
