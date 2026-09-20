from backend import verify_dispo as v


def test_watchnian_soldout_et_dispo():
    assert v.status_from_html("Watchnian", "<div class='price-soldout'>SOLD</div>") == "vendue"
    # dispo = preuve positive (bouton panier) — cf. test_watchnian_fail_safe
    assert v.status_from_html("Watchnian", "<button>カートに入れる</button>") == "dispo"


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


def test_watchnian_fail_safe_inconnu_par_defaut():
    """Réécriture anti-angle-mort : DISPO exige une preuve POSITIVE (bouton
    panier). Une page méconnaissable (structure changée, redirection vers un
    listing) → INCONNU — l'ancien « dispo par défaut » gardait des vendues en
    vitrine à vie dès que le site changeait."""
    assert v.status_from_html("Watchnian", "<div class='price-soldout'>SOLD OUT</div>") == "vendue"
    assert v.status_from_html("Watchnian", "<button>カートに入れる</button>") == "dispo"
    # prix affiché SANS panier : présent aussi sur les pages vendues → ambigu
    assert v.status_from_html("Watchnian", "<div class='block-goods-price'>¥100</div>") is None
    assert v.status_from_html("Watchnian", "<html>accueil quelconque</html>") is None


def test_housekihiroba_ligne_zaiko_scopee():
    """La valeur lue doit venir de la LIGNE 在庫 du tableau th/td — le texte
    global contient « 在庫なし » dans un template <script> sur TOUTES les fiches
    (c'est l'angle mort : 258 montres ne pouvaient jamais passer vendues)."""
    dispo = ("<table><tr><th>在庫</th><td>在庫有り(In Stock) ご注文頂けます。</td></tr></table>"
             "<script>var t='在庫なし';</script>")
    assert v.status_from_html("Housekihiroba", dispo) == "dispo"
    vendu = "<table><tr><th>在庫</th><td>在庫なし</td></tr></table>"
    assert v.status_from_html("Housekihiroba", vendu) == "vendue"
    # pas de ligne 在庫 identifiable → INCONNU (jamais un statut par défaut)
    assert v.status_from_html("Housekihiroba", "<html>rien</html>") is None
