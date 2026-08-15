from backend import verify_dispo as v


def test_watchnian_soldout_et_dispo():
    assert v.status_from_html("Watchnian", "<div class='price-soldout'>SOLD</div>") == "vendue"
    assert v.status_from_html("Watchnian", "<div class='block-goods-price'>¥100</div>") == "dispo"


def test_jackroad_availability():
    assert v.status_from_html("Jack Road", '"availability":"http://schema.org/OutOfStock"') == "vendue"
    assert v.status_from_html("Jack Road", '"availability":"http://schema.org/InStock"') == "dispo"
    assert v.status_from_html("Jack Road", "<html>rien</html>") is None


def _kamekichi_page(in_stock, stock_type):
    """Reconstitue le HTML SPA : widget bargain (NEGO) + produits liés (OUT) qui
    PRÉCÈDENT l'article — c'est le piège qui donnait des faux positifs. Le vrai
    statut est dans itemPageData.webItem."""
    import json
    data = {"props": {"pageProps": {
        "commonPage": {"bargain": {"webItem": {"stockType": "NEGO"}}},
        "itemPageData": {
            "webItem": {"stock": {"inStock": in_stock}, "stockType": stock_type},
            "relatedItems": [{"stockType": "OUT"}, {"stockType": "OUT"}]}}}}
    return f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script>'


def test_kamekichi_stocktype():
    # article en stock malgré le widget NEGO et les produits liés OUT (ex-faux positif)
    assert v.status_from_html("Kame-Kichi", _kamekichi_page(True, "IN")) == "dispo"
    assert v.status_from_html("Kame-Kichi", _kamekichi_page(False, "SOLDOUT")) == "vendue"
    # inStock absent → on retombe sur stockType de l'article
    assert v.status_from_html("Kame-Kichi", _kamekichi_page(None, "IN")) == "dispo"
    assert v.status_from_html("Kame-Kichi", _kamekichi_page(None, "OUT")) == "vendue"
    # pas de __NEXT_DATA__ ou article absent → indéterminé (on ne touche à rien)
    assert v.status_from_html("Kame-Kichi", "<html>rien</html>") is None


def test_firekids_marqueurs():
    assert v.status_from_html("Fire Kids", "取り置き中") == "vendue"
    assert v.status_from_html("Fire Kids", "<button>カートに入れる</button>") == "dispo"
    assert v.status_from_html("Fire Kids", "<html>?</html>") is None


def test_boutique_inconnue():
    assert v.status_from_html("Autre", "<html>x</html>") is None


def test_shopify_page_availability():
    # Moon Phase/Timeseek/Brand Yukichi : dispo lue sur la PAGE (JSON-LD), pas le .json
    ins = '"availability":"http://schema.org/InStock"'
    out = '"availability":"https://schema.org/OutOfStock"'
    assert v.status_from_html("Moon Phase", ins) == "dispo"
    assert v.status_from_html("Brand Yukichi", out) == "vendue"
    # fallback bouton quand pas de JSON-LD
    assert v.status_from_html("Timeseek", "<button>カートに入れる</button>") == "dispo"
    assert v.status_from_html("Brand Yukichi",
                              "<button disabled>売り切れ</button>") == "vendue"
    assert v.status_from_html("Moon Phase", "<html>rien</html>") is None


def test_eccube_bouton_et_jsonld():
    # Ginza LINKS / The Capital / Satin Doll : bouton d'achat scopé puis JSON-LD
    assert v.status_from_html(
        "Ginza LINKS", '<button class="ec-blockBtn--action">カートに入れる</button>') == "dispo"
    assert v.status_from_html(
        "The Capital", '<button class="ec-blockBtn--action">SOLD OUT</button>') == "vendue"
    # LimitedAvailability = DISPONIBLE (piège Satin Doll)
    assert v.status_from_html(
        "Satin Doll", '"availability":"https://schema.org/LimitedAvailability"') == "dispo"
    assert v.status_from_html("The Capital", "<html>?</html>") is None
