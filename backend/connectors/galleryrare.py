"""Connecteur Gallery Rare (g-rare.com) — plateforme FutureShop (classes fs-c-*).

Pas d'API JSON publique, MAIS chaque fiche produit expose un JSON-LD `Product`
propre : prix JPY (offers.price), dispo (availability In/OutOfStock), état
(itemCondition) ET un champ `description` qui contient la table de specs complète
(HTML échappé). Cette table `th/td` porte tout ce qu'on veut : 型番 (référence),
ブランド (marque), 文字盤色 (cadran), 素材 (matière), 付属品 (accessoires),
ランク/状態 (état). On lit donc UNIQUEMENT le JSON-LD de la fiche.

Listing : catégorie montres `/c/watch`, paginée `?page=N&sort=latest` (40 items/
page, newest-first → l'incrémental s'arrête tôt), page vide = fin. Chaque item du
listing donne l'URL fiche `/c/watch/{skuCode}` + le nom → item_url() permet de
sauter au re-scan ce qui est déjà en base sans ouvrir la fiche.

Registry (optionnel) :
  brands : liste de slugs de sous-catégories montres (rolex, seiko, tudor…) pour
           restreindre/prioriser ; sinon on scanne toute la catégorie `/c/watch`.
"""
import json
import re
from html import unescape

from bs4 import BeautifulSoup

from .. import http_client, variants
from ..brands import normalize_marque
from .base import BaseConnector, watch, strip_html

MAX_PAGES = 200   # garde-fou pagination (catégorie complète ~66 pages)

# Item du listing : l'anchor fiche finit par le skuCode numérique. La catégorie
# racine sert des URL plates (/c/watch/11310785), les pages marque des URL
# imbriquées (/c/watch/rolex/oyster-perpetual/11395782) → on ne garde que le
# skuCode et on canonicalise vers la forme plate (uid stable quel que soit le
# chemin de scan). Les liens de catégorie (/c/watch/rolex) finissent par un slug
# non numérique → ignorés.
_ITEM_RE = re.compile(r'<a href="/c/watch/(?:[^"]*/)?(\d+)"')

# libellés de la table de specs (th) → nos champs
_REF_LABELS = ("型番", "品番", "リファレンス")
_BRAND_LABELS = ("ブランド", "メーカー")
_DIAL_LABELS = ("文字盤色", "文字盤", "カラー", "色")
_MAT_LABELS = ("素材", "ケース素材", "材質")
_ACC_LABELS = ("付属品",)
_RANK_LABELS = ("ランク",)
_COND_LABELS = ("状態",)

# Gallery Rare abrège la matière en codes (SS, TI, K18YG, SS/K18YG two-tone…).
# variants._MATERIALS gère déjà ss/yg/wg/k18yg/k18wg/pt ; on complète les codes
# manquants en les réécrivant vers un mot que variants sait mapper (préfixe long
# d'abord : K18PG avant PG).
_MAT_EXPAND = [
    ("K18PG", "ローズゴールド"), ("K18RG", "ローズゴールド"),
    ("PG", "ローズゴールド"), ("RG", "ローズゴールド"),
    ("TI", "チタン"), ("GP", "ゴールド"),
]
# Cadrans : couleurs JP absentes du dictionnaire commun → équivalent connu.
_DIAL_EXPAND = [("ネイビー", "ブルー"), ("スレート", "グレー")]

# note « （ランクについて） » collée à la valeur ランク → à retirer
_RANK_NOTE_RE = re.compile(r"[（(].*?[)）]")


def _expand(text, table):
    up = (text or "").upper()
    extra = " ".join(rep for code, rep in table if code in up)
    return f"{text} {extra}" if extra else (text or "")


class GalleryRareConnector(BaseConnector):
    boutique = "Gallery Rare"

    def _base(self) -> str:
        return self.entry["base_url"].rstrip("/")

    # --- hooks ---
    def brands_to_scan(self):
        """Slugs de sous-catégories montres (registry) sinon toute la catégorie."""
        brands = self.entry.get("brands")
        return list(brands) if brands else [None]

    def _cat_path(self, brand):
        return f"/c/watch/{brand}" if brand else "/c/watch"

    def iter_listing(self, brand):
        """Items d'une catégorie, du plus récent au plus ancien (sort=latest),
        page après page jusqu'à épuisement."""
        base = self._base()
        path = self._cat_path(brand)
        seen_pages = set()
        for page in range(1, MAX_PAGES + 1):
            url = f"{base}{path}?page={page}&sort=latest"
            try:
                html = http_client.get_text(url)
            except Exception:
                break
            ids = list(dict.fromkeys(_ITEM_RE.findall(html)))
            key = tuple(ids)
            if not ids or key in seen_pages:
                break     # page vide ou identique à la précédente → fin de catégorie
            seen_pages.add(key)
            for sku in ids:
                yield {"url": f"{base}/c/watch/{sku}", "vendue": False}

    def item_url(self, item):
        return item["url"]   # skip sans fetch si déjà en base (base._url_seen)

    # --- lecture de la fiche ---
    def _product_ld(self, html: str):
        """Renvoie le nœud JSON-LD @type=Product de la fiche (ou None)."""
        for sc in re.findall(
                r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html, re.S):
            try:
                d = json.loads(sc)
            except ValueError:
                continue
            for node in (d if isinstance(d, list) else [d]):
                if isinstance(node, dict) and node.get("@type") == "Product":
                    return node
        return None

    def _specs(self, description: str) -> dict:
        """Parse la table `detailSpec` (th→td) du champ description (HTML échappé)."""
        soup = BeautifulSoup(unescape(description or ""), "html.parser")
        specs = {}
        for tr in soup.find_all("tr"):
            th, td = tr.find("th"), tr.find("td")
            if not th or not td:
                continue
            label = th.get_text(" ", strip=True)
            val = td.get_text(" ", strip=True)
            if label and val:
                specs.setdefault(label, val)
        return specs

    @staticmethod
    def _pick(specs, labels):
        for lab in labels:
            for k, v in specs.items():
                if (k == lab or lab in k) and v:
                    return v
        return ""

    def _image(self, ld) -> str:
        """URL image principale, taille correcte (le JSON-LD sert du xs=100px)."""
        img = unescape(ld.get("image") or "")
        base = img.split("?", 1)[0]
        return f"{base}?size=l&w=NjAw" if base else ""

    def build_detail(self, item):
        html = http_client.get_text(item["url"])
        ld = self._product_ld(html)
        if not ld:
            return None
        offers = ld.get("offers") or {}
        avail = offers.get("availability") or ""
        vendue = "InStock" not in avail   # OutOfStock / SoldOut / vide → indisponible
        price = offers.get("price")
        try:
            price = float(price) if price is not None else None
        except (TypeError, ValueError):
            price = None

        specs = self._specs(ld.get("description"))
        name = strip_html(ld.get("name") or "")
        ref = re.sub(r"\s+", "", self._pick(specs, _REF_LABELS))
        brand_txt = self._pick(specs, _BRAND_LABELS) or name
        dial_txt = self._pick(specs, _DIAL_LABELS)
        mat_txt = self._pick(specs, _MAT_LABELS)
        etat = self._pick(specs, _RANK_LABELS) or self._pick(specs, _COND_LABELS)
        etat = _RANK_NOTE_RE.sub("", etat).strip()   # retire « （ランクについて） »
        if "UsedCondition" in (offers.get("itemCondition") or "") and not etat:
            etat = "中古"

        return watch(
            boutique=self.boutique, reference=ref, url=item["url"],
            marque=normalize_marque(brand_txt), modele=name,
            prix_ttc=price, etat=etat,
            images=[self._image(ld)] if ld.get("image") else [],
            vendue=vendue,
            raw={"accessoires": self._pick(specs, _ACC_LABELS),
                 "cadran": variants.normalize_dial(_expand(dial_txt or name, _DIAL_EXPAND)),
                 "matiere": variants.normalize_material(_expand(mat_txt or name, _MAT_EXPAND))},
        )
