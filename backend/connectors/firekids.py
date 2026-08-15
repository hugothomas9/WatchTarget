"""Connecteur FIRE KIDS (firekids.jp) — EC-CUBE, server-rendered.

Listing /products/list (global toutes marques, ou category_id par marque), trié
nouveautés : réf, marque, modèle, prix, dispo. Le 付属品 (full set) et l'état sont
dans la fiche /products/detail/<ID> → ouverte seulement pour les dispo.
"""
import re

from bs4 import BeautifulSoup

from .. import http_client
from .base import BaseConnector, watch, strip_html, make_uid

BASE = "https://firekids.jp"
BRAND_CATEGORY = {"omega": "9", "rolex": "8"}
_REF_RE = re.compile(r"Ref\.?\s*([A-Za-z0-9.\-]+)", re.I)
_YEAR_RE = re.compile(r"(\d{4})\s*年製")


def _price(txt: str):
    digits = re.sub(r"[^0-9]", "", txt or "")
    return float(digits) if digits else None


class FirekidsConnector(BaseConnector):
    boutique = "Fire Kids"

    def brands_to_scan(self):
        if self.entry.get("all_brands"):
            return [None]      # None = listing global toutes marques
        return [BRAND_CATEGORY[b.lower()] for b in self.entry.get("brands", ["omega"])
                if b.lower() in BRAND_CATEGORY]

    def iter_listing(self, cat):
        max_pages = self.entry.get("max_pages_per_brand",
                                   30 if self.entry.get("all_brands") else 90)
        catq = f"category_id={cat}&" if cat else ""
        page = 1
        while page <= max_pages:
            html = http_client.get_text(
                f"{BASE}/products/list?{catq}orderby=2&disp_number=120&pageno={page}")
            cards = BeautifulSoup(html, "html.parser").select("li.ec-shelfGrid__item")
            if not cards:
                break
            for li in cards:
                a = li.select_one('a[href*="/products/detail/"]')
                if a is None:
                    continue

                def txt(sel):
                    el = li.select_one(sel)
                    return el.get_text(" ", strip=True) if el else ""
                year_line = txt("p.year")
                ref_m = _REF_RE.search(year_line)
                year_m = _YEAR_RE.search(year_line)
                prix = _price(txt("p.price02-default"))
                url = a["href"]
                yield {
                    "vendue": li.select_one("span.soldout") is not None or prix is None,
                    "url": url if url.startswith("http") else BASE + url,
                    "reference": ref_m.group(1) if ref_m else "",
                    "marque": txt("p.bland"), "modele": txt("p.name"),
                    "annee": year_m.group(1) if year_m else "",
                    "prix": prix,
                    "img": (li.select_one("img.product-image") or {}).get("src", ""),
                }
            page += 1

    def item_uid(self, item):
        return make_uid(self.boutique, item["reference"], item["url"])

    def _accessoires(self, url):
        soup = BeautifulSoup(http_client.get_text(url), "html.parser")
        for tr in soup.select("table.product-detail tr"):
            th = tr.find("th")
            td = tr.find("td")
            if th and td and "付属品" in strip_html(str(th)):
                return strip_html(str(td))
        return ""

    def build_detail(self, item):
        # erreur réseau → exception → _safe_build renvoie None → retentée plus tard
        acc = self._accessoires(item["url"])
        return watch(
            boutique=self.boutique, reference=item["reference"], url=item["url"],
            marque=item["marque"], modele=item["modele"], prix_ttc=item["prix"],
            annee=item["annee"], images=[item["img"]] if item["img"] else [],
            vendue=item["vendue"], raw={"accessoires": acc},
        )
