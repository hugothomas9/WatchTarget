"""Connecteur Gem Castle Yukizaki (gc-yukizaki.com) — ~20 boutiques, 1 catalogue.

Listing d'occasion par marque : /k/watch/{brand}/used, paginé par ?page_no=N
(48 fiches/page, fin = page vide). ATTENTION : le miroir international
gc-yukizaki.com sert un cache d'edge qui IGNORE ?page_no (toutes les pages
renvoient la page 1) ET auto-traduit le corps en anglais (« traduction
automatique, peut être incorrecte » — dixit le site). On récupère donc listing
ET fiche sur le site japonais canonique gc-yukizaki.jp, où la pagination
fonctionne et où les specs sont en japonais fiable. L'URL stockée honore le
base_url configuré (.com) pour rester cohérente avec le registre.

Chaque fiche porte un JSON-LD Product propre (name JP, offers.price JPY,
availability, itemCondition, image) → source sûre pour prix/dispo/image. Le
corps expose un tableau de specs en paires .body-col-title / .body-col-desc
(型番 réf, 素材 matière, 文字盤色 cadran, 付属品 accessoires, ランク état) plus
l'id stable #info_item_kataban (réf) et #info_jotai (état).
"""
import json
import re

from bs4 import BeautifulSoup

from .. import http_client, variants
from ..brands import normalize_marque
from .base import BaseConnector, watch, strip_html

# fiche produit = /i/W123456 ; W + digits est un code interne (PAS la référence)
_PROD_RE = re.compile(r"/i/(W\d+)")

MAX_PAGES = 200   # garde-fou pagination par marque (rolex used ≈ 9 pages)

# slugs de marques horlogères du menu /k/watch (override possible via registry)
DEFAULT_BRANDS = [
    "rolex", "omega", "tudor", "cartier", "hublot", "breitling", "iwc",
    "panerai", "audemarspiguet", "patekphilippe", "vacheronconstantin",
    "alangesohne", "breguet", "franckmuller", "richardmille", "rogerdubuis",
    "jaegerlecoultre", "zenith", "tagheuer", "chopard", "bvlgari", "chanel",
    "harrywinston", "vancleefarpels", "piaget", "hermes",
]

# libellés de spec possibles (JP sur .jp, EN auto-traduit sur .com) → on matche
# les deux pour rester robuste quel que soit l'hôte réellement interrogé.
_REF_LABELS = ("型番", "model number")
_MAT_LABELS = ("ケース素材", "素材", "material")
_DIAL_LABELS = ("文字盤色", "文字盤種", "文字盤", "text dial color", "text plate", "dial")
_ACC_LABELS = ("付属品", "accessories", "accessory")


class YukizakiConnector(BaseConnector):
    boutique = "Yukizaki"

    def _base(self) -> str:
        """Hôte pour l'URL stockée de la fiche (honore le registry, ex .com)."""
        return self.entry["base_url"].rstrip("/")

    def _catalog(self) -> str:
        """Hôte réellement scrapé : .jp (pagination OK + specs JP fiables).
        Le .com est un cache d'edge qui ignore ?page_no et auto-traduit."""
        return self._base().replace("gc-yukizaki.com", "gc-yukizaki.jp")

    def _get(self, url: str) -> str:
        return http_client.get_text(url)

    def brands_to_scan(self):
        """Slugs de marques : liste du registry sinon défaut horloger."""
        return list(self.entry.get("brands") or DEFAULT_BRANDS)

    def iter_listing(self, brand):
        """Fiches d'occasion d'une marque, page après page (?page_no=N).
        Fin de marque = page sans fiche OU identique à la précédente."""
        cat = self._catalog()
        prev_key = None
        for page in range(1, MAX_PAGES + 1):
            suffix = "" if page == 1 else f"?page_no={page}"
            url = f"{cat}/k/watch/{brand}/used{suffix}"
            try:
                html = self._get(url)
            except Exception:
                break
            codes = self._listing_codes(html)
            key = tuple(codes)
            if not codes or key == prev_key:
                break     # page vide ou pagination qui a bouclé → marque suivante
            prev_key = key
            for code in codes:
                # URL stockée sur l'hôte configuré (.com), fetch détail sur .jp
                yield {"url": f"{self._base()}/i/{code}", "code": code}

    def _listing_codes(self, html):
        """Codes /i/W... de la grille produit (item-list_item), dédupliqués.
        On cible la grille pour exclure les carrousels de reco (autres marques)."""
        soup = BeautifulSoup(html, "html.parser")
        codes = []
        cells = soup.find_all(class_="item-list_item")
        # la grille PC et la grille SP dupliquent les mêmes fiches → set d'ordre
        blocks = cells if cells else [soup]
        for cell in blocks:
            for a in cell.find_all("a", href=_PROD_RE):
                m = _PROD_RE.search(a["href"])
                if m and m.group(1) not in codes:
                    codes.append(m.group(1))
        return codes

    def item_url(self, item):
        return item["url"]   # skip sans fetch si déjà en base (base._url_seen)

    def _jsonld(self, soup):
        """Nœud JSON-LD Product de la fiche (name/price/availability/condition/image)."""
        for sc in soup.find_all("script", type="application/ld+json"):
            if not sc.string or "Product" not in sc.string:
                continue
            try:
                d = json.loads(sc.string)
            except ValueError:
                continue
            for node in (d if isinstance(d, list) else [d]):
                if isinstance(node, dict) and node.get("@type") == "Product":
                    return node
        return None

    def _specs(self, soup):
        """Tableau de specs {libellé: valeur} depuis les paires body-col."""
        specs = {}
        for col in soup.find_all(class_="body-col"):
            t = col.find(class_="body-col-title")
            d = col.find(class_="body-col-desc")
            if not t or not d:
                continue
            label = strip_html(str(t)).lower()
            value = strip_html(str(d))
            if label and value and label not in specs:
                specs[label] = value
        return specs

    @staticmethod
    def _pick(specs, labels):
        """1re valeur dont le libellé contient l'un des labels cherchés."""
        for lab in labels:
            for k, v in specs.items():
                if lab in k and v:
                    return v
        return ""

    def build_detail(self, item):
        # fiche scrapée sur .jp (JP fiable) même si l'URL stockée est en .com
        fetch_url = item["url"].replace("gc-yukizaki.com", "gc-yukizaki.jp")
        html = self._get(fetch_url)
        soup = BeautifulSoup(html, "html.parser")
        ld = self._jsonld(soup)
        if not ld:
            return None
        name = (ld.get("name") or "").strip()

        offers = ld.get("offers") or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        price = offers.get("price")
        prix = float(price) if price else None
        avail = offers.get("availability") or ""
        cond = offers.get("itemCondition") or ""
        img = ld.get("image")
        images = img if isinstance(img, list) else ([img] if img else [])

        specs = self._specs(soup)

        # référence : id stable #info_item_kataban → spec 型番 → repli sur le nom
        ref_el = soup.find(id="info_item_kataban")
        ref = strip_html(str(ref_el)) if ref_el else ""
        if not ref:
            ref = self._pick(specs, _REF_LABELS)
        if not ref:
            mr = re.search(r"\b([A-Za-z]*\d[A-Za-z0-9.\-/]{3,})\b", name)
            ref = mr.group(1) if mr else ""

        dial = self._pick(specs, _DIAL_LABELS)
        material = self._pick(specs, _MAT_LABELS)
        accessoires = self._pick(specs, _ACC_LABELS)

        # état : #info_jotai (ex « 中古[ B ]… ») → repli sur itemCondition
        jotai_el = soup.find(id="info_jotai")
        etat = ""
        if jotai_el:
            etat = re.split(r"[：:*]", strip_html(str(jotai_el)))[0].strip()
        if not etat:
            etat = ("中古" if "Used" in cond or "Refurbished" in cond
                    else ("新品" if "New" in cond else ""))

        # dispo : JSON-LD de la fiche uniquement. On NE scanne PAS le corps pour
        # « SOLD OUT / 売り切れ » : ces marqueurs apparaissent sur les fiches
        # vendues des carrousels de reco, pas sur le produit courant.
        vendue = "OutOfStock" in avail or "SoldOut" in avail

        return watch(
            boutique=self.boutique, reference=ref, url=item["url"],
            marque=normalize_marque(name), modele=name,
            prix_ttc=prix, etat=etat,
            images=images, vendue=vendue,
            raw={"accessoires": accessoires,
                 "cadran": variants.normalize_dial(dial or name),
                 "matiere": variants.normalize_material(material or name)},
        )
