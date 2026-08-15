"""Connecteur WATCHNIAN (watchnian.com — groupe Komehyo, montres d'occasion).

Server-rendered. Catégorie de marque = /shop/c/<code>/ (Omega=com), paginée via
rel="next" (/shop/c/com_p2/...). La référence (型番), le prix TTC, l'état, le
付属品 (full set) et le statut vendu sont sur la fiche /shop/g/<id>/.
"""
import re

from bs4 import BeautifulSoup

from .. import http_client
from .base import BaseConnector, watch, strip_html

BASE = "https://watchnian.com"
BRAND_CATEGORY = {"omega": "com", "rolex": "crl"}

_CAL_RE = re.compile(r"Cal\.?\s*([A-Za-z0-9/\-]+)", re.I)
_DATE_RE = re.compile(r"(\d{4}/\d{1,2}/\d{1,2})")


class WatchnianConnector(BaseConnector):
    boutique = "Watchnian"

    def brands_to_scan(self):
        if self.entry.get("all_brands"):
            html = http_client.get_text(f"{BASE}/shop/r/rg-goods/?filtercode13=1")
            codes = sorted(set(re.findall(r"/shop/c/([a-z]{2,4})/", html)))
            return codes or list(BRAND_CATEGORY.values())
        return [BRAND_CATEGORY.get(b.lower(), b.lower())
                for b in self.entry.get("brands", ["omega"])]

    def iter_listing(self, code):
        max_pages = self.entry.get("max_pages_per_brand",
                                   2 if self.entry.get("all_brands") else 40)
        url, pages, seen = f"/shop/c/{code}/", 0, set()
        while url and pages < max_pages:
            pages += 1
            soup = BeautifulSoup(http_client.get_text(BASE + url), "html.parser")
            urls = []
            for a in soup.select('a[href^="/shop/g/"]'):
                href = a["href"].split("#")[0]
                if href not in seen:
                    seen.add(href)
                    urls.append(href)
            if not urls:
                break
            for u in urls:
                yield {"vendue": False, "url": u}
            nxt = soup.select_one('a[rel="next"]')
            url = nxt["href"].split("#")[0] if nxt and nxt.get("href") else None

    def item_url(self, item):
        u = item["url"]
        return BASE + u if u.startswith("/") else u

    def _specs(self, soup) -> dict:
        out = {}
        for dl in soup.select("dl"):
            for dt, dd in zip(dl.find_all("dt"), dl.find_all("dd")):
                k, v = strip_html(str(dt)), strip_html(str(dd))
                if k and k not in out:
                    out[k] = v
        return out

    def build_detail(self, item):
        u = item["url"]
        soup = BeautifulSoup(http_client.get_text(BASE + u), "html.parser")
        sp = self._specs(soup)
        marque = sp.get("ブランド", "")
        if "OMEGA" in marque.upper():
            marque = "Omega"
        cal = ""
        m = _CAL_RE.search(sp.get("ムーブメント", ""))
        if m:
            cal = m.group(1)
        vendue = soup.select_one(".price-soldout") is not None
        prix_ttc = None
        inp = soup.select_one("input.js_loancalc_price, #js_loancalc_price, "
                              "input[id*=loancalc]")
        if inp and inp.get("value"):
            digits = re.sub(r"[^0-9]", "", inp["value"])
            prix_ttc = float(digits) if digits else None
        if prix_ttc is None:                       # fallback : bloc prix visible
            pb = soup.select_one(".block-goods-price--price")
            if pb:
                digits = re.sub(r"[^0-9]", "", pb.get_text())
                prix_ttc = float(digits) if digits else None
        date_ajout = ""
        pb = soup.select_one(".block-goods-price")
        if pb:
            dm = _DATE_RE.search(pb.get_text(" ", strip=True))
            if dm:
                date_ajout = dm.group(1)
        og = soup.select_one('meta[property="og:image"]')
        return watch(
            boutique=self.boutique,
            reference=sp.get("型番（型式番号）", "") or sp.get("型番", ""),
            url=BASE + u if u.startswith("/") else u,
            marque=marque, modele=sp.get("モデル", ""), prix_ttc=prix_ttc,
            etat=sp.get("状態", ""), date_ajout_site=date_ajout,
            description=f"{sp.get('モデル','')} (Cal.{cal})" if cal else sp.get("モデル", ""),
            images=[og["content"]] if og and og.get("content") else [],
            vendue=vendue,
            # cadran/matière (+ lunette/bracelet) pour matcher la variante EveryWatch
            raw={"calibre": cal, "accessoires": sp.get("付属品", ""),
                 "cadran": sp.get("文字盤", ""),
                 "matiere": sp.get("ケース", "") or sp.get("素材", ""),
                 "lunette": sp.get("ベゼル", ""), "bracelet": sp.get("ブレスレット", "")},
        )
