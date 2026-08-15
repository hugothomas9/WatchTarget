"""Connecteur EC-CUBE GÉNÉRIQUE (Ginza LINKS, THE CAPITAL WATCHES, Satin Doll…).

Contrairement à Shopify, EC-CUBE n'expose pas de JSON : on énumère les fiches
depuis /products/list?category_id=…&pageno=N puis on ouvre chaque fiche
/products/detail/{id}. La réf n'étant lisible que sur la fiche (pattern watchnian),
on fournit item_url() (skip par URL) et pas item_uid().

La fiche donne le prix/dispo/nom via le JSON-LD Product quand il existe (the
capital, satin doll), sinon via les sélecteurs EC-CUBE (.price02_default) ; le
型番/付属品/état sont lus dans le bloc description (identique à tous les thèmes).
"""
import re
import json

from bs4 import BeautifulSoup

from .. import http_client
from ..brands import normalize_marque
from .base import BaseConnector, watch, strip_html

_DETAIL_RE = re.compile(r"/products/detail/(\d+)")
# réf précédée d'un libellé (jamais un nombre nu → « …41 » n'est pas pris)
_REF_RE = re.compile(r"(?:ref\.?|型番|リファレンス|品番|モデル番号)\s*[:.：]?\s*"
                     r"([0-9A-Za-z][0-9A-Za-z.\-/]{2,})", re.I)
# 付属品 : on capture large puis on tronque au 1er libellé/section suivant (le texte
# qui suit varie : « ランク・状態… », « RECOMMEND NEW… », « 弊社付属品… »)
_ACC_RE = re.compile(r"付属品[：: 　]*\s*([^<\n]{2,80})")
# stop au libellé de spec OU en-tête de section suivant. PAS de règle « ASCII
# générique » : « BOX » est un accessoire légitime, pas une frontière de section.
_ACC_STOP = re.compile(r"ランク|状態|当店|弊社|参考定価|保証[：:]|コマ|管理番号|品番|型番"
                       r"|スペック|商品説明|関連商品|おすすめ|最近チェック"
                       r"|RECOMMEND|RANKING|PICKUP|CATEGORY|CONTENTS")
_ETAT_RE = re.compile(r"(?:ランク[・･]?状態|状態|コンディション)[：: 　]*\s*([^<\n]{1,20})")
# cadran/matière : valeur COURTE après le label (on ne scanne pas tout le texte,
# sinon la lunette/bracelet — ex « ベゼル ホワイトゴールド » — fausserait la matière)
_DIAL_RE = re.compile(r"文字盤[：: 　]*\s*([^\s　<\n、,]{1,14})")
_MAT_RE = re.compile(r"(?:ケース素材|素材|ケース)[：: 　]*\s*([^\s　<\n、,]{1,14})")
_PRICE_SELECTORS = (".price02_default", ".ec-price__price", "#detail_box__price",
                    ".sale_price", ".price01_default")
_SOLD_RE = re.compile(r"SOLD\s*OUT|売り切れ|完売|在庫切れ|OutOfStock|SoldOut", re.I)


def _digits(s):
    d = re.sub(r"[^0-9]", "", s or "")
    return float(d) if d else None


class EccubeConnector(BaseConnector):
    boutique = "EC-CUBE"

    def _base(self):
        return self.entry["base_url"].rstrip("/")

    def brands_to_scan(self):
        # category_id de marque/catégorie montres ; None = /products/list global
        return list(self.entry.get("categories") or [None])

    def iter_listing(self, category):
        base = self._base()
        max_pages = self.entry.get("max_pages_per_brand", 15)
        seen_ids = set()
        page = 1
        while page <= max_pages:
            qs = f"?pageno={page}"
            if category:
                qs += f"&category_id={category}"
            html = http_client.get_text(f"{base}/products/list{qs}")
            ids = [i for i in dict.fromkeys(_DETAIL_RE.findall(html))
                   if i not in seen_ids]
            if not ids:
                break                      # plus de nouvelle fiche → fin de pagination
            for pid in ids:
                seen_ids.add(pid)
                yield {"id": pid, "url": f"{base}/products/detail/{pid}"}
            page += 1

    def item_url(self, item):
        return item["url"]                 # réf seulement sur la fiche → skip par URL

    def _jsonld_product(self, soup):
        for tag in soup.select('script[type="application/ld+json"]'):
            if not tag.string:
                continue
            try:
                data = json.loads(tag.string)
            except ValueError:
                continue
            for o in (data if isinstance(data, list) else [data]):
                if isinstance(o, dict) and o.get("@type") == "Product":
                    return o
        return None

    def _price_from_dom(self, soup):
        for sel in _PRICE_SELECTORS:
            el = soup.select_one(sel)
            if el:
                v = _digits(el.get_text())
                if v:
                    return v
        return None

    def _vendue(self, offers, soup, text) -> bool:
        # signal le plus fiable et commun aux 3 thèmes : le bouton d'achat
        # (« カートに入れる » = dispo ; « SOLD OUT » = vendu). On le scope au bouton
        # pour ne pas attraper un badge SOLD OUT d'un produit « RECOMMEND ».
        btn = soup.select_one(".ec-blockBtn--action, .ec-productRole__btn")
        if btn:
            t = btn.get_text(" ", strip=True)
            if "カート" in t:
                return False
            if _SOLD_RE.search(t):
                return True
        # sinon le JSON-LD : seuls OutOfStock/SoldOut = vendu (LimitedAvailability
        # = stock limité mais DISPONIBLE, ne pas confondre)
        avail = str(offers.get("availability") or "")
        if avail:
            return bool(re.search(r"OutOfStock|SoldOut|Discontinued", avail, re.I))
        return bool(_SOLD_RE.search(text))

    def _marque(self, ld, name, soup) -> str:
        b = ld.get("brand")
        if isinstance(b, dict):
            b = b.get("name")
        if b and normalize_marque(b) != b:         # marque reconnue dans le JSON-LD
            return normalize_marque(b)
        m = normalize_marque(name)
        if m and m != name:                        # marque reconnue dans le nom
            return m
        if soup.title:                             # sinon le <title> (satin doll)
            mt = normalize_marque(soup.title.get_text())
            if mt and mt != soup.title.get_text():
                return mt
        return m

    def _acc(self, text) -> str:
        m = _ACC_RE.search(text)
        if not m:
            return ""
        val = m.group(1)
        stop = _ACC_STOP.search(val)
        if stop:
            val = val[:stop.start()]
        return val.strip(" 　、,・")

    def build_detail(self, item):
        # erreur réseau → exception → _safe_build None → retentée au prochain run
        html = http_client.get_text(item["url"])
        soup = BeautifulSoup(html, "html.parser")
        text = strip_html(html)
        ld = self._jsonld_product(soup) or {}
        offers = ld.get("offers") or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}

        name = ld.get("name") or (soup.select_one(".ec-headingTitle") or
                                  soup.title).get_text(" ", strip=True)
        prix = _digits(str(offers.get("price"))) if offers.get("price") else None
        if prix is None:
            prix = self._price_from_dom(soup)

        vendue = self._vendue(offers, soup, text)

        mref = _REF_RE.search(name) or _REF_RE.search(text)
        ref = mref.group(1) if mref else ""
        acc = self._acc(text)
        mdial = _DIAL_RE.search(text)
        mmat = _MAT_RE.search(text)
        metat = _ETAT_RE.search(text)
        etat = metat.group(1).strip() if metat else ""

        img = ""
        og = soup.select_one('meta[property="og:image"]')
        if ld.get("image"):
            im = ld["image"]
            img = im[0] if isinstance(im, list) else im
        elif og and og.get("content"):
            img = og["content"]

        return watch(
            boutique=self.boutique, reference=ref, url=item["url"],
            marque=self._marque(ld, name, soup), modele=name,
            prix_ttc=prix, etat=etat, vendue=vendue,
            images=[img] if img else [],
            raw={"accessoires": acc,
                 "cadran": mdial.group(1) if mdial else "",
                 "matiere": mmat.group(1) if mmat else ""},
        )
