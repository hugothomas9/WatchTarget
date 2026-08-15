"""Connecteur GMT — https://www.gmt-j.com/ (site direct, option A).

Le site est protégé par un WAF qui rejette `requests` en 403 (blocage sur
l'empreinte TLS, pas l'User-Agent). On passe donc par curl_cffi en impersonant
Safari 17 — exactement comme market.py / market_everywatch.py le font déjà pour
Chrono24 / EveryWatch. `http_client` (requests) est inutilisable ici.

Structure du site (Forcia faceted search) :
  * Le listing est rendu en JS : la vraie source est une API JSON Solr-like
    `/ec/api/ItemSearchGMT?maker={id}&order=dateDesc&rows=N&start=K`
    → `response.numFound` + `response.docs` (déjà filtrée « en stock » côté
    serveur : sellstatusid=1 uniquement, donc pas d'occasion vendue à trier).
    Chaque doc porte : genpinname (nom+réf), makername, salesprice, jancode
    (= clé de la fiche), selltypeid (1 neuf / 2 occasion / 3 consignation /
    4 non porté), usedrank, et des flags d'accessoires.
  * La fiche est `/item/{jancode}` (utf-8). Elle expose un JSON-LD Product
    propre (name, image, brand, price JPY) + un tableau de specs <th>/<td>
    (ダイアルカラー = cadran, 材質(ケース本体) = matière, 付属品 = accessoires,
    商品状況 = statut stock).
  * Les IDs de marque (maker) se lisent sur /item/maker/list.

Réf : la marque n'a pas de champ « 型番 » dédié ; la réf est noyée dans le nom
(ex « デイト 41 126610LN »). On prend le plus long token alphanumérique porteur
d'un chiffre, en écartant les tailles (36mm, 41…).
"""
import re
import json
import time
import threading

from bs4 import BeautifulSoup

from ..brands import normalize_marque
from .. import variants
from .base import BaseConnector, watch, strip_html

_API = "/ec/api/ItemSearchGMT"
_ROWS = 100                       # taille de page API
_MAX_PAGES = 60                   # garde-fou pagination par marque
_IMPERSONATE = "safari17_0"

# maker=... dans /item/maker/list (liens des marques du menu)
_MAKER_RE = re.compile(r"maker=(\d+)")

# selltypeid → état lisible
_SELLTYPE = {"1": "新品", "2": "中古 USED", "3": "中古 委託", "4": "未使用"}

# token de réf : ≥3 caractères, au moins un chiffre ; on écarte les tailles nues
_TOKEN_RE = re.compile(r"[0-9A-Za-z][0-9A-Za-z.\-/]{2,}")
_SIZE_RE = re.compile(r"^\d{1,2}(mm)?$", re.I)

_SOLD_RE = re.compile(r"SOLD\s*OUT|売り切れ|売切|品切れ|在庫なし|完売|ご成約|OutOfStock",
                      re.I)

# --- session curl_cffi partagée + throttle global (politesse) ---
_tls = threading.local()
_rate_lock = threading.Lock()
_last = [0.0]
_DELAY = 0.4


def _session():
    s = getattr(_tls, "gmt_sess", None)
    if s is None:
        from curl_cffi import requests as cr
        s = cr.Session(impersonate=_IMPERSONATE)
        s.get("https://www.gmt-j.com/", timeout=25)   # sème les cookies WAF
        _tls.gmt_sess = s
    return s


def _throttle():
    with _rate_lock:
        wait = _last[0] + _DELAY - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.monotonic()


def _extract_ref(name: str) -> str:
    """Réf = plus long token alphanumérique avec chiffre, hors tailles (36mm…)."""
    best = ""
    for tok in _TOKEN_RE.findall(name or ""):
        if not any(c.isdigit() for c in tok):
            continue
        if _SIZE_RE.match(tok):
            continue
        if len(tok) > len(best):
            best = tok
    return best


class GmtConnector(BaseConnector):
    boutique = "GMT"

    def _base(self) -> str:
        return (self.entry.get("base_url") or "https://www.gmt-j.com").rstrip("/")

    def _get_text(self, url: str, encoding: str | None = None) -> str:
        _throttle()
        r = _session().get(url, timeout=25)
        r.raise_for_status()
        if encoding:
            r.encoding = encoding
        return r.text

    def _get_json(self, url: str, params: dict) -> dict:
        _throttle()
        r = _session().get(url, params=params, timeout=25, headers={
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"{self._base()}/search",
        })
        r.raise_for_status()
        return r.json()

    # --- hooks ---
    def brands_to_scan(self):
        """IDs maker : liste explicite du registry (priorisation) sinon toutes
        les marques lues sur /item/maker/list."""
        cats = self.entry.get("categories")
        if cats:
            return list(cats)
        html = self._get_text(f"{self._base()}/item/maker/list")
        found = []
        for mid in _MAKER_RE.findall(html):
            if mid not in found:
                found.append(mid)
        return found

    def iter_listing(self, maker):
        """Docs d'une marque via l'API JSON, du plus récent au plus ancien."""
        base = self._base()
        for page in range(_MAX_PAGES):
            start = page * _ROWS
            try:
                d = self._get_json(f"{base}{_API}", {
                    "maker": str(maker), "order": "dateDesc",
                    "rows": str(_ROWS), "start": str(start)})
            except Exception:
                break
            resp = (d or {}).get("response") or {}
            docs = resp.get("docs") or []
            if not docs:
                break
            for doc in docs:
                # la fiche se résout par mapcode (≠ jancode pour l'occasion)
                code = doc.get("mapcode") or doc.get("jancode")
                if not code:
                    continue
                yield {
                    "jancode": code,
                    "url": f"{base}/item/{code}",
                    "genpinname": doc.get("genpinname") or "",
                    "makername": doc.get("makername") or "",
                    "salesprice": doc.get("salesprice") or "",
                    "selltypeid": doc.get("selltypeid") or "",
                    "usedrank": doc.get("usedrank") or "",
                    "vendue": doc.get("sellstatusid") not in (None, "1"),
                }
            num = resp.get("numFound")
            if num is not None and start + _ROWS >= int(num):
                break

    def item_url(self, item):
        return item["url"]        # réf sur la fiche → skip par URL (base._url_seen)

    # --- fiche ---
    def _jsonld_product(self, soup):
        for tag in soup.find_all("script", type="application/ld+json"):
            if not tag.string or "Product" not in tag.string:
                continue
            try:
                data = json.loads(tag.string)
            except ValueError:
                continue
            for node in (data if isinstance(data, list) else [data]):
                if isinstance(node, dict) and node.get("@type") == "Product":
                    return node
        return {}

    def _specs(self, soup) -> dict:
        """Tableau de specs <th>label</th><td>valeur</td> de la fiche."""
        out = {}
        for th in soup.find_all("th"):
            td = th.find_next("td")
            if td is None:
                continue
            k = strip_html(str(th))
            v = strip_html(str(td))
            if k and v and k not in out:
                out[k] = v
        return out

    def _material(self, specs: dict) -> str:
        for k, v in specs.items():
            if "ケース本体" in k:          # « 材質(ケース本体) » = matière du boîtier
                return v
        return variants.material_from_specs(specs)

    def build_detail(self, item):
        # échec réseau → exception → _safe_build None → retentée au prochain run
        html = self._get_text(item["url"], encoding="utf-8")
        soup = BeautifulSoup(html, "html.parser")
        ld = self._jsonld_product(soup)
        specs = self._specs(soup)

        name = ld.get("name") or item.get("genpinname") or ""
        brand = ld.get("brand")
        if isinstance(brand, dict):
            brand = brand.get("name")
        marque = normalize_marque(brand or item.get("makername") or name)

        ref = _extract_ref(item.get("genpinname") or "") or _extract_ref(name)

        offers = ld.get("offers") or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        prix = None
        if offers.get("price"):
            digits = re.sub(r"[^0-9]", "", str(offers["price"]))
            prix = float(digits) if digits else None
        if prix is None:
            digits = re.sub(r"[^0-9]", "", item.get("salesprice") or "")
            prix = float(digits) if digits else None

        img = ld.get("image")
        if isinstance(img, list):
            img = img[0] if img else ""
        if not img:                                   # occasion : pas d'image LD
            og = soup.select_one('meta[property="og:image"]')
            img = og.get("content") if og and og.get("content") else ""

        dial_txt = specs.get("ダイアルカラー") or variants.dial_from_specs(specs)
        mat_txt = self._material(specs)
        acc = specs.get("付属品", "")

        etat = _SELLTYPE.get(item.get("selltypeid"), "")
        rank = item.get("usedrank")
        if etat.startswith("中古") and rank and rank != "0":
            etat = f"{etat} ランク{rank}"

        stock = specs.get("商品状況", "")
        vendue = bool(item.get("vendue")) or bool(_SOLD_RE.search(stock))

        return watch(
            boutique=self.boutique, reference=ref, url=item["url"],
            marque=marque, modele=name,
            prix_ttc=prix, etat=etat,
            images=[img] if img else [],
            vendue=vendue,
            raw={"accessoires": acc,
                 "cadran": variants.normalize_dial(dial_txt or name),
                 "matiere": variants.normalize_material(mat_txt or name)},
        )
