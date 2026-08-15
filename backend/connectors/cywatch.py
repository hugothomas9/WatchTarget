"""Connecteur CY WATCH (cywatch-tokyo.jp) — Shopify, API JSON native.

Tout est dans le JSON /collections/<marque>/products.json (ou /collections/
all-item pour toutes marques) : prix TTC, dispo, date (created_at), et le
body_html porte 型番 (réf), モデル (modèle) et 付属品 (accessoires → full set).
"""
import re

from bs4 import BeautifulSoup

from .. import http_client
from .base import BaseConnector, watch

BASE = "https://cywatch-tokyo.jp"
BRAND_COLLECTION = {"omega": "omega", "rolex": "rolex"}


def _to_float(v):
    if v is None:
        return None
    digits = re.sub(r"[^0-9]", "", str(v).split(".")[0])
    return float(digits) if digits else None


class CywatchConnector(BaseConnector):
    boutique = "CY Watch"

    def brands_to_scan(self):
        if self.entry.get("all_brands"):
            return ["all-item"]
        return [BRAND_COLLECTION.get(b.lower(), b.lower())
                for b in self.entry.get("brands", ["omega"])]

    _LABELS = ("型番", "モデル", "文字盤", "素材", "ケース", "ブレス・ストラップ",
               "ケース径", "ムーブメント", "パワーリザーブ", "防水性能", "状態")
    _STOP = ("当店の保証", "について", "保証は", "明示", "返品", "ご注意", "送料",
             "コンディション", "管理番号", "備考")

    def _specs(self, body_html: str):
        """Lit 型番 / モデル / 付属品 (multi-valeurs) dans le body_html.
        Le 付属品 s'étale sur plusieurs <p> (ex: 正規の外箱, 正規の保証書) ; on les
        accumule jusqu'au libellé suivant ou au bloc de politique de garantie."""
        soup = BeautifulSoup(body_html or "", "html.parser")
        seq = []
        for p in soup.find_all("p"):
            t = p.get_text(" ", strip=True)
            if t and (not seq or seq[-1] != t):   # dédoublonne les répétitions
                seq.append(t)
        ref = modele = cadran = matiere = ""
        acc_parts = []
        for i, t in enumerate(seq):
            nxt = seq[i + 1] if i + 1 < len(seq) else ""
            if t == "型番":
                ref = nxt
            elif t == "モデル":
                modele = nxt
            elif t == "文字盤":
                cadran = nxt
            elif t in ("素材", "ケース"):
                matiere = matiere or nxt
            elif t == "付属品":
                j = i + 1
                while (j < len(seq) and len(acc_parts) < 5
                       and seq[j] not in self._LABELS
                       and not any(s in seq[j] for s in self._STOP)):
                    acc_parts.append(seq[j])
                    j += 1
        return ref, modele, " ".join(acc_parts), cadran, matiere

    def iter_listing(self, brand):
        page = 1
        while page <= 40:
            data = http_client.get_json(
                f"{BASE}/collections/{brand}/products.json?limit=250&page={page}")
            products = data.get("products", [])
            if not products:
                break
            for p in products:
                var = (p.get("variants") or [{}])[0]
                yield {"vendue": not var.get("available", True), "p": p, "brand": brand}
            page += 1

    def build_detail(self, item):
        p, brand = item["p"], item["brand"]
        var = (p.get("variants") or [{}])[0]
        ref, modele, acc, cadran, matiere = self._specs(p.get("body_html"))
        marque = p.get("title", "") if brand == "all-item" else brand
        return watch(
            boutique=self.boutique, reference=ref,
            url=f"{BASE}/products/{p.get('handle')}", marque=marque,
            modele=modele or p.get("title", ""),
            prix_ttc=_to_float(var.get("price")),
            etat=p.get("product_type", ""),
            date_ajout_site=(p.get("created_at") or "")[:10],
            images=[i["src"] for i in (p.get("images") or [])][:1],
            vendue=item["vendue"],
            raw={"accessoires": acc, "tags": p.get("tags"),
                 "cadran": cadran, "matiere": matiere},
        )
