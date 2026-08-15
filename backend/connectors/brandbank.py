"""Connecteur BrandBank (ブランドバンク) — plateforme Color Me Shop (カラーミーショップ).

Color Me Shop n'expose pas de JSON-LD : on lit les balises meta OpenGraph pour
le nom / le prix (`product:price:amount` en JPY) et l'image, puis on parse le
corps texte pour les specs japonaises (商品品番 réf, 素材 matière, 文字盤カラー
cadran, 付属品 accessoires, 商品ランク état).

Listing par catégorie-marque : `/shopbrand/{slug}/` (page 1) puis
`/shopbrand/{slug}/page{N}/order/`. Les fiches produit sont en `/shopdetail/{id}/`.
La réf ET l'URL sont lisibles depuis le listing (l'id est dans l'URL, mais la réf
n'est que sur la fiche) → on fournit item_url() pour sauter au re-scan sans fetch.

Vendu : le site RETIRE les fiches vendues (404). En repli, une fiche encore en
ligne mais épuisée porte `<... class="gensan">soldout</...>` (vide = disponible)
ou n'a plus de balise prix.

Registry :
  encoding : « euc-jp » (obligatoire, tout le site est en EUC-JP)
  categories : liste de slugs à parcourir (ex ['rolex','ct24']) ; sinon défaut
               ci-dessous (marques horlogères). ct33-ct45 = modèles Rolex (déjà
               couverts par 'rolex'), ct46+ = maroquinerie/bijoux (hors montres).
"""
import re

from bs4 import BeautifulSoup

from .. import http_client, variants
from ..brands import normalize_marque
from .base import BaseConnector, watch, strip_html

_DETAIL_RE = re.compile(r"/shopdetail/(\d{6,})/")

# specs dans le corps de la fiche (labels Color Me Shop japonais)
# réf : 商品品番 chez BrandBank (parfois 型番/品番 ailleurs sur la plateforme)
_REF_RE = re.compile(r"(?:商品品番|型番|品番)[：: 　]*\s*"
                     r"([0-9A-Za-z][0-9A-Za-z./\-]{2,})")
_MAT_RE = re.compile(r"(?:素材|材質)[：: 　]*\s*([^\s　、,。<]{1,16})")
_DIAL_RE = re.compile(r"文字盤(?:カラー)?[：: 　]*\s*([^\s　、,。<]{1,16})")
_ACC_RE = re.compile(r"付属品[：: 　]*\s*([^。\n<]{2,80})")
_ETAT_RE = re.compile(r"(?:商品ランク|ランク|状態)[：: 　]*\s*([^\s　、,。<]{1,16})")
# repli prix si la balise meta manque : « ￥2,000,000 » / « 2,000,000円 »
_PRICE_TXT_RE = re.compile(r"[￥¥]\s*([0-9][0-9,]{3,})|([0-9][0-9,]{3,})\s*円")

MAX_PAGES = 120   # garde-fou pagination par catégorie

# Catégories horlogères par défaut (slugs du menu). 'rolex' agrège tous les
# modèles Rolex ; les ct** sont les autres marques ; ct52/ct54 = montres diverses.
_DEFAULT_CATS = [
    "rolex",   # ROLEX (tous modèles)
    "ct7",     # Grand Seiko
    "ct8",     # Patek Philippe
    "ct9",     # Vacheron Constantin
    "ct24",    # Omega
    "ct25",    # Audemars Piguet
    "ct29",    # Panerai
    "ct31",    # Hublot
    "ct32",    # Tudor
    "ct52",    # 時計 (montres, divers)
    "ct54",    # 【時計】その他
]


class BrandBankConnector(BaseConnector):
    boutique = "BrandBank"

    def _base(self) -> str:
        return self.entry["base_url"].rstrip("/")

    def _get(self, url: str) -> str:
        # tout BrandBank est en EUC-JP (défaut si le registry ne précise rien)
        enc = self.entry.get("encoding", "euc-jp")
        return http_client.get_text(url, encoding=enc)

    def brands_to_scan(self):
        return list(self.entry.get("categories") or _DEFAULT_CATS)

    def iter_listing(self, slug):
        """Fiches d'une catégorie, page après page (page1 = URL nue, puis
        /page{N}/order/). Fin quand une page ne renvoie plus d'id nouveau."""
        base = self._base()
        seen = set()
        for page in range(1, MAX_PAGES + 1):
            suffix = f"/shopbrand/{slug}/" if page == 1 else \
                     f"/shopbrand/{slug}/page{page}/order/"
            try:
                html = self._get(f"{base}{suffix}")
            except Exception:
                break
            ids = [i for i in dict.fromkeys(_DETAIL_RE.findall(html))
                   if i not in seen]
            if not ids:
                break     # page vide (au-delà de la dernière) → fin de la catégorie
            for pid in ids:
                seen.add(pid)
                yield {"id": pid, "url": f"{base}/shopdetail/{pid}/"}

    def item_url(self, item):
        # la réf n'est que sur la fiche → skip par URL si déjà en base
        return item["url"]

    def _meta(self, soup, prop, attr="property"):
        el = soup.find("meta", attrs={attr: prop})
        return el.get("content", "").strip() if el and el.get("content") else ""

    def _price(self, soup, body):
        amt = self._meta(soup, "product:price:amount")
        if amt:
            d = re.sub(r"[^0-9]", "", amt)
            if d:
                return float(d)
        m = _PRICE_TXT_RE.search(body)
        if m:
            d = re.sub(r"[^0-9]", "", m.group(1) or m.group(2))
            if d:
                return float(d)
        return None

    def _vendue(self, soup, price) -> bool:
        # fiche encore en ligne mais épuisée : <.gensan>soldout</.gensan>
        g = soup.select_one(".gensan")
        if g and g.get_text(strip=True).lower() == "soldout":
            return True
        return price is None   # plus de prix affiché → considéré épuisé

    def build_detail(self, item):
        # 404 (fiche vendue retirée) → raise → _safe_build None → retentée
        html = self._get(item["url"])
        soup = BeautifulSoup(html, "html.parser")
        body = strip_html(html)

        title = self._meta(soup, "og:title")
        # nom propre : on retire le suffixe boutique « -ブランドバンク… » / « | … »
        name = re.split(r"\s*[|｜]\s*|-ブランドバンク", title)[0].strip()
        # marque : la ligne ブランド名 de la description OG est la plus fiable
        desc = self._meta(soup, "og:description")
        mbrand = re.search(r"ブランド名[：: 　]*\s*([^\n\r]+)", desc)
        marque = normalize_marque(mbrand.group(1) if mbrand else name)

        price = self._price(soup, body)
        vendue = self._vendue(soup, price)

        mref = _REF_RE.search(body)
        ref = mref.group(1) if mref else ""
        mmat = _MAT_RE.search(body)
        mdial = _DIAL_RE.search(body)
        macc = _ACC_RE.search(body)
        metat = _ETAT_RE.search(body)

        acc = macc.group(1).strip(" 　、,・") if macc else ""
        # tronque la clause « ※付属品欄に記載… » qui suit parfois les accessoires
        acc = re.split(r"※", acc)[0].strip(" 　、,・")

        img = self._meta(soup, "og:image")

        return watch(
            boutique=self.boutique, reference=ref, url=item["url"],
            marque=marque, modele=name,
            prix_ttc=price,
            etat=metat.group(1).strip() if metat else "",
            images=[img] if img else [],
            vendue=vendue,
            raw={"accessoires": acc,
                 "cadran": variants.normalize_dial(
                     mdial.group(1) if mdial else name),
                 "matiere": variants.normalize_material(
                     mmat.group(1) if mmat else name)},
        )
