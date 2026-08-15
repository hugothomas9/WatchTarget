"""Connecteur Shopify GÉNÉRIQUE — une seule classe pour toutes les boutiques
Shopify (elles exposent toutes /products.json et /collections/<h>/products.json).

Tout est dans le JSON du listing (prix, dispo, created_at, body_html), donc
build_detail ne refait AUCUN appel réseau : la fiche complète est déjà là.
Chaque boutique se déclare dans le registry avec `base_url` et, si le site n'est
pas 100% horlogerie (recycle-shop), une liste `collections` pour se limiter aux
montres.

Les specs (型番/品番, モデル, 付属品, 状態) sont écrites différemment selon la
boutique : tableau <td><strong>label<br></strong>valeur (moon-phase), listes
<dl><dt>label</dt><dd>valeur</dd> (brand-yukichi), ou prose « Ref.xxx » (timeseek).
_specs() gère les deux structures ; _ref() ajoute des filets de secours (Ref. en
prose, tag de référence, SKU).
"""
import re

from bs4 import BeautifulSoup

from .. import http_client
from ..brands import normalize_marque
from .. import variants
from .base import BaseConnector, watch, make_uid, strip_html

MAX_PAGES = 60

# libellés de spec (une boutique n'en utilise qu'une variante)
_REF_LABELS = ("型番", "品番", "リファレンス", "モデル番号", "Ref", "Ref.")
_MODELE_LABELS = ("モデル", "シリーズ", "シリーズ名")
_ETAT_LABELS = ("状態", "商品ランク", "コンディション", "ランク")
_MARQUE_LABELS = ("ブランド", "メーカー")
_ACC_LABEL = "付属品"

# accessoires en PROSE (timeseek n'a pas de champ 付属品 : « 付属品は純正ボックス
# および…ギャランティーが揃った完品です » + bloc structuré « 箱 あり ギャランティー 2025.10 »)
_ACC_PROSE_RE = re.compile(r"付属品[はをに]?[:：]?\s*(.{4,80}?)(?:。|です|揃|$)")
_ACC_BOX_RE = re.compile(r"箱\s*(あり|なし|無し|無)")
_ACC_WARR_RE = re.compile(r"(ギャランティー|保証書)\s*([0-9]{4}[.\-/年][0-9]{1,2})")

# réf en prose (timeseek : « Ref.126720VTNR ») + réf isolée dans les tags
_REF_PROSE_RE = re.compile(r"(?:型番|品番|リファレンス|Ref)\.?\s*[:：]?\s*"
                           r"([A-Za-z0-9][A-Za-z0-9.\-/]{2,})")
_REF_TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-/]{3,}$")

# la marque quand la collection EST une marque (brand-yukichi : /collections/rolex)
_BRAND_COLLECTION = {"rolex", "omega", "cartier", "tudor", "seiko", "grand-seiko",
                     "breitling", "panerai", "iwc", "hublot", "chanel"}


def _to_float(v):
    if v is None:
        return None
    digits = re.sub(r"[^0-9]", "", str(v).split(".")[0])
    return float(digits) if digits else None


class ShopifyConnector(BaseConnector):
    boutique = "Shopify"

    def _base(self) -> str:
        return self.entry["base_url"].rstrip("/")

    def brands_to_scan(self):
        # collections explicites (site non 100% horlogerie) sinon catalogue global
        return list(self.entry.get("collections") or [None])

    def _sold(self, var) -> bool:
        # Certaines boutiques (timeseek, brand-yukichi) exposent leur catalogue SANS
        # checkout en ligne : `available` y est TOUJOURS false (= « pas commandable en
        # ligne », pas « vendu »). Pour elles trust_available=False → présence dans le
        # feed = en vente (les vendues sont retirées du catalogue par la boutique).
        if not self.entry.get("trust_available", True):
            return False
        return not var.get("available", True)

    def iter_listing(self, collection):
        base = self._base()
        path = (f"/collections/{collection}/products.json" if collection
                else "/products.json")
        page = 1
        while page <= MAX_PAGES:
            data = http_client.get_json(f"{base}{path}?limit=250&page={page}")
            products = data.get("products", [])
            if not products:
                break
            for p in products:
                var = (p.get("variants") or [{}])[0]
                yield {"vendue": self._sold(var), "p": p, "collection": collection}
            page += 1

    # --- lecture des specs (deux structures HTML possibles) ---
    def _specs(self, body_html: str) -> dict:
        """Extrait {label: valeur} depuis <dl><dt>/<dd> ET <td><strong>label…"""
        soup = BeautifulSoup(body_html or "", "html.parser")
        specs = {}
        for dl in soup.find_all("dl"):
            dts, dds = dl.find_all("dt"), dl.find_all("dd")
            for dt, dd in zip(dts, dds):
                label = dt.get_text(strip=True)
                val = dd.get_text(" ", strip=True)
                if label and val:
                    specs.setdefault(label, val)
        for td in soup.find_all("td"):
            strong = td.find(["strong", "b"])
            if not strong:
                continue
            label = strong.get_text(strip=True)
            full = td.get_text(" ", strip=True)
            val = full.replace(label, "", 1).strip(" :：")
            if label and val:
                specs.setdefault(label, val)
        return specs

    def _pick(self, specs, labels):
        for lab in labels:
            if lab in specs and specs[lab]:
                return specs[lab]
        return ""

    def _ref(self, p, specs) -> str:
        ref = self._pick(specs, _REF_LABELS)
        if ref:
            return re.sub(r"\s+", "", ref)
        # prose « Ref.xxx » (timeseek)
        m = _REF_PROSE_RE.search(strip_html(p.get("body_html") or ""))
        if m:
            return m.group(1)
        # tag qui ressemble à une référence (alphanumérique avec au moins un chiffre)
        for tag in p.get("tags") or []:
            t = str(tag).strip()
            if _REF_TAG_RE.match(t) and any(c.isdigit() for c in t):
                return t
        # dernier recours : SKU de la variante
        sku = (p.get("variants") or [{}])[0].get("sku") or ""
        m = _REF_PROSE_RE.search(sku)
        return m.group(1) if m else ""

    def _marque(self, p, collection, specs) -> str:
        marque = self._pick(specs, _MARQUE_LABELS)   # label ブランド (moon-phase)
        if marque:
            return normalize_marque(marque)
        if collection and collection.lower() in _BRAND_COLLECTION:
            return normalize_marque(collection)
        return normalize_marque(p.get("title", "")) or p.get("vendor", "")

    def _acc(self, p, specs) -> str:
        """付属品 : champ de spec, sinon reconstruit depuis la prose (timeseek)."""
        acc = specs.get(_ACC_LABEL, "")
        if acc:
            return acc
        body = strip_html(p.get("body_html") or "")
        parts = []
        m = _ACC_PROSE_RE.search(body)
        if m:
            parts.append(m.group(1))
        m = _ACC_BOX_RE.search(body)
        if m:
            parts.append("箱" + m.group(1))
        m = _ACC_WARR_RE.search(body)
        if m:
            parts.append(m.group(1) + m.group(2))
        return " ".join(parts)

    def _url(self, p) -> str:
        return f"{self._base()}/products/{p.get('handle')}"

    def item_uid(self, item):
        # tout est dans le listing → on peut calculer l'uid sans ouvrir de fiche
        p = item["p"]
        ref = self._ref(p, self._specs(p.get("body_html")))
        return make_uid(self.boutique, ref, self._url(p))

    def build_detail(self, item):
        p, collection = item["p"], item["collection"]
        specs = self._specs(p.get("body_html"))
        ref = self._ref(p, specs)
        var = (p.get("variants") or [{}])[0]
        acc = self._acc(p, specs)
        modele = self._pick(specs, _MODELE_LABELS) or p.get("title", "")
        return watch(
            boutique=self.boutique, reference=ref, url=self._url(p),
            marque=self._marque(p, collection, specs), modele=modele,
            prix_ttc=_to_float(var.get("price")),
            etat=self._pick(specs, _ETAT_LABELS) or p.get("product_type", ""),
            date_ajout_site=(p.get("created_at") or "")[:10],
            images=[i["src"] for i in (p.get("images") or [])][:1],
            vendue=item["vendue"],
            raw={"accessoires": acc, "tags": p.get("tags"),
                 "cadran": variants.dial_from_specs(specs),
                 "matiere": variants.material_from_specs(specs)},
        )
