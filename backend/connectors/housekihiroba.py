"""Connecteur Housekihiroba (宝石広場) — https://housekihiroba.jp/shop/

ATTENTION : le sous-domaine www NE résout PAS → base sans www.
Plateforme ASP.NET, pages encodées en Shift_JIS étendu → on décode en cp932
(shift_jis strict casse sur certains caractères ; utf-8 est du mojibake).

Structure du site :
  - listing par catégorie : /shop/c/{code}/  (ex Rolex occasion c01rxus,
    Rolex neuf/tous c01rx, Omega occasion c01omus…). Le suffixe « us » = 中古
    (occasion). Pagination par ?p=N, 32 fiches/page.
  - fiche produit : /shop/g/{id}/  (id = « g » + chiffres, ex g663853001).

La réf (型番) n'est lisible que sur la fiche (pattern watchnian) → on fournit
item_url() (skip par URL) et pas item_uid(). La fiche expose :
  - <title> « {réf} {modèle} {中古|新品} ｜ {marque} | … » ;
  - un tableau de specs th/td (型番, 材質（メイン）, カラー, 文字盤特徴, 付属品…) ;
  - le prix TTC dans <span class="price_"> « 2,750,000円 » ;
  - une ligne 在庫 → « 在庫有り(In Stock) » (dispo) / « 在庫なし »/品切れ (vendu) ;
  - og:image pour la photo principale, og:title pour le modèle.
"""
import re

from bs4 import BeautifulSoup

from .. import http_client
from .. import variants
from ..brands import normalize_marque
from .base import BaseConnector, watch, strip_html

_ENC = "cp932"

# fiche produit dans un listing : /shop/g/g663853001/
_GID_RE = re.compile(r"/shop/g/(g\d+)/")

# catégories « occasion » (中古) par défaut des grandes marques (suffixe « us »).
# Surchargble via entry["categories"]. Chaque code = /shop/c/{code}/.
_DEFAULT_CATEGORIES = [
    "c01rxus",  # Rolex
    "c01omus",  # Omega
    "c01apus",  # Audemars Piguet
    "c01ppus",  # Patek Philippe
    "c01vcus",  # Vacheron Constantin
    "c01jlus",  # Jaeger-LeCoultre
    "c01iwus",  # IWC
    "c01huus",  # Hublot
    "c01caus",  # Cartier
    "c01brus",  # Breitling
    "c01frus",  # Franck Muller
    "c01zeus",  # Zenith
]

# libellés de spec (th) → sens. On lit la valeur (td) associée.
_REF_LABELS = ("型番",)
_MAT_LABELS = ("材質（メイン）", "材質", "素材", "ケース素材", "ケース")
_DIAL_LABELS = ("カラー", "文字盤", "文字盤特徴")
_ACC_LABELS = ("付属品",)
_STOCK_LABELS = ("在庫",)

_SOLD_RE = re.compile(r"在庫なし|品切れ|売り切れ|完売|ご売約|SOLD\s*OUT|Out\s*of\s*Stock",
                      re.I)
_INSTOCK_RE = re.compile(r"在庫有り|In\s*Stock", re.I)
# état : 中古 (occasion) / 新品 (neuf), présent dans le titre et la catégorie
_ETAT_RE = re.compile(r"(中古|新品|未使用)")


def _digits(s):
    d = re.sub(r"[^0-9]", "", s or "")
    return float(d) if d else None


class HousekihirobaConnector(BaseConnector):
    boutique = "Housekihiroba"

    def _base(self):
        return (self.entry.get("base_url") or "https://housekihiroba.jp").rstrip("/")

    # --- hooks ---
    def brands_to_scan(self):
        return list(self.entry.get("categories") or _DEFAULT_CATEGORIES)

    def iter_listing(self, category):
        base = self._base()
        max_pages = self.entry.get("max_pages_per_brand", 30)
        seen_ids = set()
        page = 1
        while page <= max_pages:
            url = f"{base}/shop/c/{category}/?p={page}"
            html = http_client.get_text(url, encoding=_ENC)
            ids = [i for i in dict.fromkeys(_GID_RE.findall(html))
                   if i not in seen_ids]
            if not ids:
                break                  # plus de nouvelle fiche → fin de pagination
            for gid in ids:
                seen_ids.add(gid)
                yield {"id": gid, "url": f"{base}/shop/g/{gid}/"}
            page += 1

    def item_url(self, item):
        return item["url"]             # réf seulement sur la fiche → skip par URL

    # --- parsing fiche ---
    def _specs(self, soup) -> dict:
        """Tableau(x) de specs : {libellé th → valeur td}. Plusieurs tables sur
        la fiche (specs produit + ligne 在庫) → on les fusionne."""
        specs = {}
        for tr in soup.find_all("tr"):
            cells = tr.find_all(["th", "td"])
            if len(cells) != 2:
                continue
            label = strip_html(str(cells[0]))
            value = strip_html(str(cells[1]))
            if label and value and label not in specs:
                specs[label] = value
        return specs

    def _pick(self, specs, labels) -> str:
        for lab in labels:
            for k, v in specs.items():
                if lab == k or lab in k:
                    if v:
                        return v
        return ""

    def _image(self, url) -> str:
        """L'og:image du site est malformée : « https://housekihiroba.jp//
        {host_cloudfront}/img/… » (double slash + faux host → 404). On rétablit
        l'URL CloudFront réelle. Gère aussi les cas relatifs classiques."""
        url = (url or "").strip()
        if not url:
            return ""
        # host CloudFront collé après un double slash → on le remet en tête
        url = re.sub(r"^https?://housekihiroba\.jp//+", "https://", url)
        if url.startswith("//"):
            return "https:" + url
        if url.startswith("/"):
            return self._base() + url
        return url

    def _price(self, soup):
        el = soup.select_one(".price_")
        if el:
            v = _digits(el.get_text())
            if v:
                return v
        # fallback : 1er « …円 » du corps
        m = re.search(r"([0-9][0-9,]{3,})\s*円", soup.get_text(" "))
        return _digits(m.group(1)) if m else None

    def _vendue(self, specs, text) -> bool:
        stock = self._pick(specs, _STOCK_LABELS)
        if stock:
            if _INSTOCK_RE.search(stock):
                return False
            if _SOLD_RE.search(stock):
                return True
        # pas de ligne 在庫 lisible → signal texte global
        return bool(_SOLD_RE.search(text)) and not _INSTOCK_RE.search(text)

    def build_detail(self, item):
        # erreur réseau → exception → _safe_build None → retentée au prochain run
        html = http_client.get_text(item["url"], encoding=_ENC)
        soup = BeautifulSoup(html, "html.parser")
        text = strip_html(html)
        specs = self._specs(soup)

        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        og_title = soup.select_one('meta[property="og:title"]')
        og_image = soup.select_one('meta[property="og:image"]')

        # référence : 型番 (fiche) ; fallback = 1er token du titre
        ref = self._pick(specs, _REF_LABELS)
        if not ref and title:
            ref = title.split()[0]

        # modèle : og:title (« デイトジャスト »), sinon la catégorie/titre nettoyé
        modele = ""
        if og_title and og_title.get("content"):
            modele = og_title["content"].strip()
        if not modele:
            cat = specs.get("カテゴリ", "")
            modele = re.sub(r"\(.*?\)|（.*?）", "", cat).strip() or title

        # marque : normalize_marque scanne le libellé → le titre contient « ロレックス »
        marque = normalize_marque(specs.get("カテゴリ", "") + " " + title)

        etat_m = _ETAT_RE.search(title) or _ETAT_RE.search(specs.get("カテゴリ", ""))
        etat = etat_m.group(1) if etat_m else ""

        prix = self._price(soup)
        vendue = self._vendue(specs, text)

        cadran_raw = self._pick(specs, _DIAL_LABELS)
        matiere_raw = self._pick(specs, _MAT_LABELS)
        accessoires = self._pick(specs, _ACC_LABELS)

        img = self._image(og_image["content"] if og_image else "")

        return watch(
            boutique=self.boutique,
            reference=ref,
            url=item["url"],
            marque=marque,
            modele=modele,
            prix_ttc=prix,
            etat=etat,
            images=[img] if img else [],
            vendue=vendue,
            raw={
                "accessoires": accessoires,
                "cadran": variants.normalize_dial(cadran_raw),
                "matiere": variants.normalize_material(matiere_raw),
            },
        )
