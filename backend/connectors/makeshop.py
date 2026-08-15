"""Connecteur MakeShop GÉNÉRIQUE (plateforme shopserve.jp) — King's Road, 7HOURS…

MakeShop pagine son listing en JS : « changePage » remplace `/list.html` par
`/list{N}.html` (page 2 = list2.html, page 3 = list3.html…). On énumère les
catégories-marques depuis le menu (liens `/SHOP/{id}/list.html`), puis on pagine
chacune jusqu'à épuisement.

Chaque fiche porte un JSON-LD `ProductGroup` propre (nom, prix JPY, état, dispo,
image) + un corps texte avec les specs japonaises (型番 réf, 素材 matière,
文字盤カラー cadran, 付属品 accessoires). On lit le JSON-LD pour les valeurs sûres
et le corps pour les specs de pricing et le full set.

Registry :
  encoding    : « euc-jp » pour les sites EUC-JP (7HOURS, BrandBank)
  categories  : liste d'IDs de catégories pour restreindre (priorisation) ; sinon
                on lit le menu marques complet du site.
"""
import re

from bs4 import BeautifulSoup

from .. import http_client, variants
from ..brands import normalize_marque
from .base import BaseConnector, watch, strip_html

# fiche produit = /SHOP/<id>.html (pas une catégorie …/list.html)
_PROD_RE = re.compile(r"/SHOP/([a-z]*-?\d{3,})\.html")
_CAT_RE = re.compile(r"/SHOP/(\d+)/list\.html")

# catégories du menu qui ne sont PAS des marques (agrégats/transverses) → ignorées
_SKIP_CATS = {"111385", "251305"}   # « USED・未使用品 » (doublonne tout), « 保証 »

# specs dans le corps de la fiche (labels japonais MakeShop)
_REF_RE = re.compile(r"型番[：:\s]*([A-Za-z0-9][A-Za-z0-9.\-/]{2,})")
_MAT_RE = re.compile(r"(?:素材|材質)[：:\s]*([^\s、,。]{2,20})")
_DIAL_RE = re.compile(r"文字盤(?:カラー)?[：:\s]*([^\s、,。]{1,12})")
_ACC_RE = re.compile(r"付属品[：:\s]*([^*。\n]{2,60})")

MAX_PAGES = 120   # garde-fou pagination par catégorie


class MakeShopConnector(BaseConnector):
    boutique = "MakeShop"

    def _base(self) -> str:
        return self.entry["base_url"].rstrip("/")

    def _get(self, url: str) -> str:
        enc = self.entry.get("encoding")   # EUC-JP pour 7HOURS / BrandBank
        return http_client.get_text(url, encoding=enc)

    def brands_to_scan(self):
        """IDs de catégories-marques : liste explicite du registry (priorisation)
        sinon menu marques complet du site (accueil)."""
        cats = self.entry.get("categories")
        if cats:
            return list(cats)
        html = self._get(f"{self._base()}/")
        found = []
        for cid in _CAT_RE.findall(html):
            if cid not in _SKIP_CATS and cid not in found:
                found.append(cid)
        return found

    def iter_listing(self, cat):
        """Fiches d'une catégorie, page après page (list.html, list2.html…)."""
        base = self._base()
        seen_pages = set()
        for page in range(1, MAX_PAGES + 1):
            suffix = "list.html" if page == 1 else f"list{page}.html"
            try:
                html = self._get(f"{base}/SHOP/{cat}/{suffix}")
            except Exception:
                break
            urls = []
            for m in _PROD_RE.finditer(html):
                u = f"{base}/SHOP/{m.group(1)}.html"
                if u not in urls:
                    urls.append(u)
            # page vide ou identique à la précédente → fin de la catégorie
            key = tuple(urls)
            if not urls or key in seen_pages:
                break
            seen_pages.add(key)
            for u in urls:
                yield {"url": u}

    def item_url(self, item):
        return item["url"]   # skip sans fetch si déjà en base (base._url_seen)

    def _jsonld(self, soup):
        """Renvoie le nœud JSON-LD Product OU ProductGroup de la fiche (les deux
        structures existent selon le site : King's Road = ProductGroup à variantes,
        7HOURS = Product simple)."""
        import json
        for sc in soup.find_all("script", type="application/ld+json"):
            if not sc.string or "Product" not in sc.string:
                continue
            try:
                d = json.loads(sc.string)
            except ValueError:
                continue
            for node in (d if isinstance(d, list) else [d]):
                if isinstance(node, dict) and node.get("@type") in (
                        "Product", "ProductGroup"):
                    return node
        return None

    def build_detail(self, item):
        html = self._get(item["url"])
        soup = BeautifulSoup(html, "html.parser")
        ld = self._jsonld(soup)
        if not ld:
            return None
        # 7HOURS préfixe le nom d'un ID interne « 【149114】 » — à retirer (ce n'est
        # PAS la référence : la vraie réf suit la marque, ex « ROLEX 67180 »)
        name = re.sub(r"^\s*[【〔\[]\s*\d+\s*[】〕\]]\s*", "", ld.get("name") or "")
        prix = None
        cond = avail = ""
        img = ld.get("image")
        # ProductGroup → variantes (hasVariant) ; Product → offers direct
        offers_nodes = ld.get("hasVariant") or [ld]
        for v in offers_nodes:
            off = v.get("offers") or {}
            p = off.get("price")
            if p and (prix is None or float(p) < prix):
                prix = float(p)      # option « +garantie » gonfle le prix → on garde le mini
            cond = cond or off.get("itemCondition") or ""
            avail = avail or off.get("availability") or ""
            img = img or v.get("image")
        vendue = "OutOfStock" in avail or "SoldOut" in avail

        body = strip_html(html)
        mref = _REF_RE.search(body)
        ref = mref.group(1) if mref else ""
        if not ref:                                   # secours : réf dans le nom
            mr = re.search(r"\b([A-Za-z]*\d[A-Za-z0-9.\-/]{3,})\b", name)
            ref = mr.group(1) if mr else ""
        macc = _ACC_RE.search(body)
        mmat = _MAT_RE.search(body)
        mdial = _DIAL_RE.search(body)
        etat = "USED 中古" if "Used" in cond else ("新品" if "New" in cond else "")

        return watch(
            boutique=self.boutique, reference=ref, url=item["url"],
            marque=normalize_marque(name), modele=name,
            prix_ttc=prix, etat=etat,
            images=[img] if img else [],
            vendue=vendue,
            raw={"accessoires": macc.group(1) if macc else "",
                 "cadran": variants.normalize_dial(mdial.group(1) if mdial else name),
                 "matiere": variants.normalize_material(mmat.group(1) if mmat else name)},
        )
