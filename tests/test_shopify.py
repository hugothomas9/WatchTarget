"""Le connecteur Shopify générique doit lire la réf/marque/accessoires dans les
trois structures rencontrées : <dl><dt> (brand-yukichi), <td><strong> (moon-phase)
et la prose « Ref./付属品は… » (timeseek)."""
from backend.connectors.shopify import ShopifyConnector
from backend.filters import is_full_set

# 1) moon-phase : table, marque dans <strong>ブランド</strong>, réf = 品番, prose absente
_MOON = {
    "handle": "0100200m", "title": "デイトジャスト 箱・保証書付き 中古品",
    "created_at": "2026-07-05T10:00:00+09:00", "product_type": "", "vendor": "",
    "tags": [], "images": [{"src": "https://x/1.jpg"}],
    "variants": [{"price": "2880000", "available": True}],
    "body_html": (
        "<table><tr class='list'><td><strong>ブランド<br></strong>ロレックス</td></tr>"
        "<tr class='list'><td><strong>シリーズ<br></strong>デイトジャスト</td></tr>"
        "<tr class='list'><td><strong>品番<br></strong>116263</td></tr>"
        "<tr class='list'><td><strong>状態<br></strong><span>中古品</span></td></tr>"
        "<tr class='list'><td><strong>付属品<br></strong>外箱、内箱、保証書(2011年6月)</td></tr>"
        "</table>"),
}
# 2) brand-yukichi : listes <dl>, réf = 型番
_YUKICHI = {
    "handle": "24004084-01", "title": "【ROLEX】ロレックス オイスターパーペチュアル",
    "created_at": "2026-07-04T10:00:00+09:00", "product_type": "", "vendor": "brand-yukichi",
    "tags": ["NEW"], "images": [{"src": "https://x/2.jpg"}],
    "variants": [{"price": "2805000", "available": True}],
    "body_html": (
        "<dl><dt>型番</dt><dd>124300</dd></dl>"
        "<dl><dt>モデル</dt><dd>オイスターパーペチュアル41</dd></dl>"
        "<dl><dt>付属品</dt><dd>箱、ギャランティカード、説明書</dd></dl>"),
}
# 3) timeseek : prose, réf = Ref.xxx, accessoires en phrase, marque dans le titre
_TIMESEEK = {
    "handle": "rolex-gmt-126720vtnr-0015", "title": "ロレックス GMTマスターⅡ 126720VTNR 黒文字盤",
    "created_at": "2026-01-31T10:00:00+09:00", "product_type": "", "vendor": "Timeseek",
    "tags": ["126720VTNR", "rolex"], "images": [{"src": "https://x/3.jpg"}],
    "variants": [{"price": "2710000", "available": True, "sku": "rlx-gmt2-126720vtnr"}],
    "body_html": (
        "<p>Ref.126720VTNR の入荷です。付属品は純正ボックスおよび2025年10月付"
        "ギャランティーが揃った安心の内容。</p>"
        "<p>状態 新品同様 箱 あり ギャランティー 2025.10</p>"),
}
# 4) sans box (négation) → pas full-set
_NOBOX = {
    "handle": "x", "title": "オメガ スピードマスター 310.30",
    "created_at": "2026-07-01T10:00:00+09:00", "product_type": "used", "vendor": "",
    "tags": [], "images": [], "variants": [{"price": "600000", "available": False}],
    "body_html": "<dl><dt>型番</dt><dd>310.30.42</dd></dl><dl><dt>付属品</dt><dd>無し</dd></dl>",
}


def _fake_json(products):
    calls = {"n": 0}

    def get_json(url, **kw):
        calls["n"] += 1
        return {"products": products if calls["n"] == 1 else []}
    return get_json


def _one(monkeypatch, product, entry=None):
    from backend import http_client
    monkeypatch.setattr(http_client, "get_json", _fake_json([product]))
    c = ShopifyConnector(entry or {"boutique": "T", "base_url": "https://x", "all_brands": True})
    items = list(c.iter_listing(None))
    return c.build_detail(items[0])


def test_moonphase_table_strong(monkeypatch):
    w = _one(monkeypatch, _MOON)
    assert w["reference"] == "116263"
    assert w["marque"] == "Rolex"                 # via <strong>ブランド</strong>
    assert w["modele"] == "デイトジャスト"
    assert w["prix_ttc"] == 2880000.0
    assert w["date_ajout_site"] == "2026-07-05"
    assert is_full_set(w["raw"]["accessoires"])   # 外箱 + 保証書


def test_yukichi_dl_dt(monkeypatch):
    w = _one(monkeypatch, _YUKICHI)
    assert w["reference"] == "124300"
    assert w["marque"] == "Rolex"                 # via le titre
    assert is_full_set(w["raw"]["accessoires"])   # 箱 + ギャランティカード


def test_timeseek_prose(monkeypatch):
    w = _one(monkeypatch, _TIMESEEK)
    assert w["reference"] == "126720VTNR"         # « Ref.126720VTNR » en prose
    assert w["marque"] == "Rolex"
    assert w["prix_ttc"] == 2710000.0
    # accessoires reconstruits depuis la prose → full set (ボックス + ギャランティー)
    assert is_full_set(w["raw"]["accessoires"])


def test_negation_pas_full_set(monkeypatch):
    w = _one(monkeypatch, _NOBOX)
    assert w["reference"] == "310.30.42"
    assert w["marque"] == "Omega"
    assert w["vendue"] is True
    assert not is_full_set(w["raw"]["accessoires"])   # 付属品 無し


def test_collection_marque(monkeypatch):
    """Quand la collection EST une marque (brand-yukichi /collections/rolex)."""
    prod = dict(_YUKICHI, title="オイスターパーペチュアル")   # titre sans marque
    from backend import http_client
    monkeypatch.setattr(http_client, "get_json", _fake_json([prod]))
    c = ShopifyConnector({"boutique": "T", "base_url": "https://x",
                          "collections": ["rolex"]})
    items = list(c.iter_listing("rolex"))
    w = c.build_detail(items[0])
    assert w["marque"] == "Rolex"


def test_trust_available_false_feed_vaut_en_vente(monkeypatch):
    """Boutique sans checkout en ligne (available toujours false) : trust_available
    False → présence dans le feed = en vente (pas vendue)."""
    from backend import http_client
    sold_variant = dict(_TIMESEEK, variants=[{"price": "2710000", "available": False}])
    monkeypatch.setattr(http_client, "get_json", _fake_json([sold_variant]))
    # sans le flag : available=false → vendue
    c1 = ShopifyConnector({"boutique": "T", "base_url": "https://x", "all_brands": True})
    assert list(c1.iter_listing(None))[0]["vendue"] is True
    # avec trust_available=False : feed = en vente (nouveau faux, le précédent est épuisé)
    monkeypatch.setattr(http_client, "get_json", _fake_json([sold_variant]))
    c2 = ShopifyConnector({"boutique": "T", "base_url": "https://x",
                           "all_brands": True, "trust_available": False})
    assert list(c2.iter_listing(None))[0]["vendue"] is False


def test_item_uid_coherent_avec_build(monkeypatch):
    """L'uid calculé depuis le listing doit être identique à celui de la fiche
    (sinon la déduplication instant-resume casse)."""
    w = _one(monkeypatch, _TIMESEEK)
    from backend import http_client
    monkeypatch.setattr(http_client, "get_json", _fake_json([_TIMESEEK]))
    c = ShopifyConnector({"boutique": "T", "base_url": "https://x", "all_brands": True})
    item = list(c.iter_listing(None))[0]
    assert c.item_uid(item) == w["uid"]
