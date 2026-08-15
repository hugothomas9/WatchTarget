"""Connecteur KAME-KICHI (kame-kichi.com / かめ吉) — Next.js, JSON __NEXT_DATA__.

Listing (dispo/réf/prix) via le JSON __NEXT_DATA__ de /search (toutes marques,
trié nouveautés) ou /brands/<MARQUE>. Le 付属品 (accessoires → full set) n'est
que sur la fiche /items/<id>, donc on ne l'ouvre que pour les montres dispo.
"""
import json

from bs4 import BeautifulSoup

from .. import http_client
from .base import BaseConnector, watch, make_uid

BASE = "https://www.kame-kichi.com"
BRAND_PATH = {"omega": "OMEGA", "rolex": "ROLEX"}
PAGE_SIZE = 18
MAX_PAGES = 200


def _next_data(html: str) -> dict:
    tag = BeautifulSoup(html, "html.parser").select_one("script#__NEXT_DATA__")
    return json.loads(tag.string) if tag and tag.string else {}


class KamekichiConnector(BaseConnector):
    boutique = "Kame-Kichi"

    def brands_to_scan(self):
        if self.entry.get("all_brands"):
            return [None]      # None = listing global /search (toutes marques)
        return [BRAND_PATH.get(b.lower(), b.upper())
                for b in self.entry.get("brands", ["omega"])]

    def _page_url(self, brand, page):
        if brand is None:                         # catalogue COMPLET toutes marques
            return f"{BASE}/search?page={page}"     # (et non op=NEWARRIVAL, plafonné à ~212)
        return f"{BASE}/brands/{brand}?page={page}"

    def iter_listing(self, brand):
        page = 1
        while page <= MAX_PAGES:
            sp = (_next_data(http_client.get_text(self._page_url(brand, page)))
                  .get("props", {}).get("pageProps", {}).get("searchPage", {}))
            items = sp.get("webItems", [])
            if not items:
                break
            for it in items:
                yield {"vendue": it.get("stockType", "IN") != "IN", "it": it}
            total = sp.get("pagination", {}).get("totalCount", 0)
            if total and page * PAGE_SIZE >= total:
                break
            page += 1

    # accessoires = liste typée des éléments PRÉSENTS (box / guarantee / booklet)
    _ACC_MAP = {"box": "純正箱 box", "guarantee": "国際保証書 guarantee warranty",
                "booklet": "冊子 booklet"}

    def item_uid(self, item):
        it = item["it"]
        return make_uid(self.boutique, it.get("refno", ""),
                        f"{BASE}/items/{it.get('itemId')}")

    def _accessoires(self, item_page: dict) -> str:
        acc = item_page.get("webItem", {}).get("accessories", []) or []
        types = [a.get("type", "") for a in acc if isinstance(a, dict)]
        return " ".join(self._ACC_MAP.get(t, t) for t in types)

    def build_detail(self, item):
        it = item["it"]
        img = it.get("mainImageUri") or it.get("mailImageUri") or ""
        if img.startswith("//"):
            img = "https:" + img
        # erreur réseau → exception → _safe_build renvoie None → retentée plus tard
        data = _next_data(http_client.get_text(f"{BASE}/items/{it.get('itemId')}"))
        ip = data.get("props", {}).get("pageProps", {}).get("itemPageData", {})
        acc = self._accessoires(ip)
        return watch(
            boutique=self.boutique, reference=it.get("refno", ""),
            url=f"{BASE}/items/{it.get('itemId')}",
            marque=it.get("brandJa", ""), modele=it.get("modelJa", ""),
            prix_ttc=float(it["salesPrice"]) if it.get("salesPrice") else None,
            etat=it.get("usedEx", ""), images=[img] if img else [],
            vendue=item["vendue"],
            raw={"accessoires": acc, "color": it.get("color"),
                 "cadran": it.get("color") or "", "matiere": it.get("material") or ""},
        )
