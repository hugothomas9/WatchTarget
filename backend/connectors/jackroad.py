"""Connecteur JACK ROAD (jackroad.co.jp) — server-rendered, Shift_JIS.

Listing /shop/r/<code>/?p=N (réf, marque, prix, dispo) ; la fiche /shop/g/g<ID>/
porte le JSON-LD (releaseDate = date d'ajout) et le 付属品 (full set). On découvre
dynamiquement les codes marque depuis l'accueil quand all_brands est demandé.
"""
import re
import json

from bs4 import BeautifulSoup

from .. import http_client
from .base import BaseConnector, watch, strip_html, make_uid

BASE = "https://www.jackroad.co.jp"
BRAND_LIST = {"omega": "rjwom", "rolex": "rjwrx", "tudor": "rjwtu"}


def _price(txt: str):
    digits = re.sub(r"[^0-9]", "", txt or "")
    return float(digits) if digits else None


class JackroadConnector(BaseConnector):
    boutique = "Jack Road"

    def brands_to_scan(self):
        if self.entry.get("all_brands"):
            html = http_client.get_text(f"{BASE}/shop/default.aspx", encoding="cp932")
            codes = sorted(set(re.findall(r"/shop/r/(rjw[a-z]+)/", html)))
            return codes or list(BRAND_LIST.values())
        return [BRAND_LIST[b.lower()] for b in self.entry.get("brands", ["omega"])
                if b.lower() in BRAND_LIST]

    def iter_listing(self, code):
        max_pages = self.entry.get("max_pages_per_brand",
                                   3 if self.entry.get("all_brands") else 90)
        page = 1
        while page <= max_pages:
            html = http_client.get_text(f"{BASE}/shop/r/{code}/?p={page}",
                                        encoding="cp932")
            soup = BeautifulSoup(html, "html.parser")
            cards = []
            for a in soup.select('a.goods_name_[href^="/shop/g/"]'):
                li = a.find_parent("li")
                if li is not None and li not in cards:
                    cards.append(li)
            if not cards:
                break
            for li in cards:
                a = li.select_one('a.goods_name_[href^="/shop/g/"]')

                def txt(sel):
                    el = li.select_one(sel)
                    return el.get_text(" ", strip=True) if el else ""
                vendue = (li.select_one("div.list-soldout") is not None
                          or "在庫切れ" in txt("div.icon_product_info_"))
                img = li.select_one("img[data-src], img[src]")
                src = (img.get("data-src") or img.get("src") or "") if img else ""
                if src.startswith("/"):
                    src = BASE + src
                yield {
                    "vendue": vendue,
                    "url": BASE + a["href"].split("?")[0],
                    "reference": txt("p.item_no_ span") or txt("p.item_no_"),
                    "marque": txt("p.brand_name_ span.brand-ja") or "",
                    "modele": txt("span.item_name_"),
                    "prix": _price(txt("div.price-box p.price_main_") or txt("p.price_main_")),
                    "img": src,
                }
            page += 1

    def item_uid(self, item):
        return make_uid(self.boutique, item["reference"], item["url"])

    def _detail(self, url):
        """Renvoie (accessoires, date_ajout, cadran, matiere)."""
        html = http_client.get_text(url, encoding="cp932")
        soup = BeautifulSoup(html, "html.parser")
        acc = date = cadran = matiere = ""
        ld = soup.select_one('script[type="application/ld+json"]')
        if ld and ld.string:
            try:
                # le JSON-LD jackroad contient des '\' invalides (¥ en Shift_JIS) :
                # on ne répare QUE les échappements illégaux, pas les légitimes (\" \n…)
                d = json.loads(re.sub(r'\\(?![\\/"bfnrtu])', "/", ld.string))
                date = (d.get("releaseDate") or "")[:10]
            except (ValueError, AttributeError):
                pass
        for dl in soup.select("dl.comment-tbl"):
            for dt, dd in zip(dl.find_all("dt"), dl.find_all("dd")):
                label = strip_html(str(dt))
                if "付属品" in label:
                    acc = strip_html(str(dd))
                elif "文字盤" in label:
                    cadran = strip_html(str(dd))
                elif ("素材" in label or "ケース" in label) and not matiere:
                    matiere = strip_html(str(dd))
        return acc, date, cadran, matiere

    def build_detail(self, item):
        # NE PAS avaler les erreurs réseau : une exception → _safe_build → None
        # → la montre n'est pas marquée "examinée" et sera retentée au prochain run.
        acc, date, cadran, matiere = self._detail(item["url"])
        return watch(
            boutique=self.boutique, reference=item["reference"], url=item["url"],
            marque=item["marque"] or "Omega", modele=item["modele"],
            prix_ttc=item["prix"], date_ajout_site=date, vendue=item["vendue"],
            images=[item["img"]] if item.get("img") else [],
            raw={"accessoires": acc, "cadran": cadran, "matiere": matiere},
        )
