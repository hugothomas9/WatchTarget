"""Connecteur EC-CUBE générique : lecture prix/dispo via JSON-LD OU bouton d'achat,
réf + 付属品 dans la description, marque via JSON-LD brand / nom / <title>."""
from backend.connectors.eccube import EccubeConnector
from backend.filters import is_full_set

# fiche avec JSON-LD (the capital) : dispo, réf dans le nom, 付属品 suivi de RECOMMEND
_CAPITAL = """<html><head><title>ロレックス | THE CAPITAL WATCHES</title>
<script type="application/ld+json">{"@type":"Product","name":"ロレックス デイトジャスト 126234【中古】",
"brand":{"@type":"Brand","name":"ロレックス"},"image":"https://x/a.jpg",
"offers":{"@type":"Offer","price":"2255000","availability":"https://schema.org/InStock"}}</script>
</head><body><button class="ec-blockBtn--action">カートに入れる</button>
<div>型番 126234 素材 ステンレス</div>
<div>付属品 純正ボックス、国際保証書（Z番）、取扱説明書 RECOMMEND NEW ロレックス</div>
<div>ランク・状態 新品同様</div></body></html>"""

# fiche vendue via JSON-LD OutOfStock
_CAPITAL_SOLD = _CAPITAL.replace("InStock", "OutOfStock").replace(
    "カートに入れる", "SOLD OUT")

# fiche SANS JSON-LD (ginzalinks) : prix .price02_default, dispo via bouton panier,
# réf « ref.124300 » dans le titre, marque « ROLEX » dans le nom
_GINZA = """<html><head><title>ROLEX オイスターパーペチュアル41 ref.124300｜銀座LINKS</title></head>
<body><h1 class="ec-headingTitle">ROLEX オイスターパーペチュアル41 ref.124300</h1>
<span class="price02_default">1,180,000円</span>
<button class="ec-blockBtn--action">カートに入れる</button>
<div>付属品：箱・保証書（2023/11） ランク・状態：S（未使用品） 参考定価：981,000円</div>
</body></html>"""

# fiche satin doll : marque SEULEMENT dans le <title>, LimitedAvailability = DISPONIBLE,
# 付属品 contient « BOX » (ne doit pas être coupé)
_SATIN = """<html><head><title>ロレックス メンズ サブマリーナー | 中古｜サテンドール</title>
<script type="application/ld+json">{"@type":"Product","name":"サブマリーナー デイト",
"offers":{"price":"3498000","availability":"https://schema.org/LimitedAvailability"}}</script>
</head><body><button class="ec-blockBtn--action">カートに入れる</button>
<div>型番 116610LV 付属品： 国内正規保証カード、BOX、クロノメータータグ、冊子 弊社付属品：</div>
</body></html>"""


def _detail(monkeypatch, html, entry=None):
    from backend import http_client
    monkeypatch.setattr(http_client, "get_text", lambda url, **kw: html)
    c = EccubeConnector(entry or {"boutique": "T", "base_url": "https://x"})
    return c.build_detail({"id": "1", "url": "https://x/products/detail/1"})


def test_capital_jsonld_dispo(monkeypatch):
    w = _detail(monkeypatch, _CAPITAL)
    assert w["reference"] == "126234"
    assert w["marque"] == "Rolex"                       # JSON-LD brand
    assert w["prix_ttc"] == 2255000.0
    assert w["vendue"] is False                         # bouton カートに入れる
    # 付属品 tronqué à RECOMMEND mais BOX/保証書 conservés → full set
    assert w["raw"]["accessoires"] == "純正ボックス、国際保証書（Z番）、取扱説明書"
    assert is_full_set(w["raw"]["accessoires"])


def test_capital_soldout_jsonld(monkeypatch):
    w = _detail(monkeypatch, _CAPITAL_SOLD)
    assert w["vendue"] is True                          # OutOfStock + bouton SOLD OUT


def test_ginza_sans_jsonld(monkeypatch):
    w = _detail(monkeypatch, _GINZA)
    assert w["reference"] == "124300"                   # « ref.124300 » du titre
    assert w["marque"] == "Rolex"
    assert w["prix_ttc"] == 1180000.0                   # .price02_default (pas 参考定価)
    assert w["vendue"] is False                         # bouton panier présent
    assert is_full_set(w["raw"]["accessoires"])         # 箱・保証書


def test_satin_marque_via_title_et_box_preserve(monkeypatch):
    w = _detail(monkeypatch, _SATIN)
    assert w["reference"] == "116610LV"
    assert w["marque"] == "Rolex"                        # uniquement dans le <title>
    assert w["vendue"] is False                          # LimitedAvailability = dispo
    assert "BOX" in w["raw"]["accessoires"]              # BOX pas coupé par le stop
    assert is_full_set(w["raw"]["accessoires"])          # BOX + 保証カード


def test_iter_listing_pagination(monkeypatch):
    from backend import http_client
    pages = {
        "https://x/products/list?pageno=1":
            '<a href="/products/detail/10">a</a><a href="/products/detail/11">b</a>',
        "https://x/products/list?pageno=2":
            '<a href="/products/detail/12">c</a>',
        "https://x/products/list?pageno=3": "<div>vide</div>",
    }
    monkeypatch.setattr(http_client, "get_text", lambda url, **kw: pages.get(url, ""))
    c = EccubeConnector({"boutique": "T", "base_url": "https://x"})
    ids = [it["id"] for it in c.iter_listing(None)]
    assert ids == ["10", "11", "12"]                     # dédup + arrêt page vide
