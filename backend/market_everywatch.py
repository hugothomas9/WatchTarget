"""Source de prix EveryWatch — PRIX RÉELLEMENT VENDUS (enchères + dealers), en EUR,
gratuit, sans token. Recette complète : docs/everywatch-findings.md.

Pipeline pour une réf (ex 279384RBR, cadran silver, matière steel) :
  1. SearchResults (GraphQL public) → variantes {referenceNumberId, image}
  2. getListingData (auctionType=result) → ventes réelles {eur, cadran, matière, variantId}
  3. on filtre les ventes sur le CADRAN + MATIÈRE de notre montre (pré-filtre texte)
  4. s'il reste plusieurs sous-variantes (ex -0007 bâtons / -0009 romains, tous « Silver »)
     ET qu'on a une photo → MATCHING IMAGE (photo boutique ↔ image variante) pour choisir
  5. médiane/P25/P75/n des ventes de la variante retenue (stats robustes = trim des extrêmes)

Fallbacks : pas de cadran connu → agrégat réf ; image absente/peu sûre → agrégat cadran+matière.
"""
import io
import json
import re
import time

from bs4 import BeautifulSoup

from . import variants
from .matching import normalize_ref
from .market import stats_from_prices

_API = "https://api.everywatch.com/api"
_SITE = "https://everywatch.com"
_HDRS = {"Referer": f"{_SITE}/watch-listing", "Origin": _SITE,
         "x-fe-webdriver": "false"}
_IMP = "safari17_0"
_SIZE_RE = re.compile(r"\d{2}mm\s+(.*)$")            # config = ce qui suit « 28mm »
_REFNUM_RE = re.compile(r"([0-9A-Za-z]+-\d{3,4})")   # « 279384RBR-0009 » dans le titre
_DAYS_RE = re.compile(r"Listed\s*For\s*([\d,]+)\s*Days", re.I)
_DATE_RE = re.compile(r"([A-Z][a-z]{2}),?\s*(20\d{2})")   # « Apr, 2026 » / « May 12 - … 2026 »
_MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def _months_ago(date_str: str):
    """Nb de mois écoulés depuis une date « Apr 2026 » (None si illisible)."""
    from datetime import datetime
    m = re.match(r"([A-Z][a-z]{2})\s+(20\d{2})", date_str or "")
    if not m or m.group(1) not in _MONTHS:
        return None
    now = datetime.now()
    return (now.year - int(m.group(2))) * 12 + (now.month - _MONTHS[m.group(1)])


def _session():
    from curl_cffi import requests as cr
    # PAS de proxy pour EveryWatch : testé, le proxy ROTATIF casse la session (cookies
    # semés depuis une IP, requête suivante depuis une autre → EveryWatch rejette →
    # taux de succès effondré). EveryWatch ne rate-limite pas notre IP directe (diagnostic :
    # 8/8 réfs Rolex/Omega OK en batch sans proxy). Le proxy reste réservé à Chrono24.
    s = cr.Session(impersonate=_IMP)
    s.get(f"{_SITE}/", timeout=25)                    # sème les cookies invité
    return s


class EveryWatchSource:
    name = "everywatch"

    def __init__(self):
        self._s = None

    def _sess(self):
        if self._s is None:
            self._s = _session()
        return self._s

    def _search_query(self, query: str) -> list[dict]:
        u = (f"{_API}/GraphQL?queryName=SearchResults&variables="
             + json.dumps({"query": query, "page": 1, "size": 30}))
        d = self._sess().get(u, headers=_HDRS, timeout=25).json()
        vs = (((d.get("data") or {}).get("data") or {}).get("data") or {}) \
            .get("searchResults", {}).get("variants", []) or []
        want = normalize_ref(query)
        out = []
        for v in vs:
            rn = v.get("referenceNumber") or ""
            if normalize_ref(rn.split("-")[0]) == want:
                out.append({"ref_num": rn,
                            "id": str(v.get("referenceNumberId")),
                            "image": (v.get("placeholderImageUrl") or "")
                            .replace("_120.webp", "_480.webp")})
        return out

    # --- étape 1 : réf → variantes ---
    def search(self, ref: str) -> list[dict]:
        """Résout la réf → variantes EveryWatch. Si la réf complète ne résout pas,
        on réessaie avec la BASE (sans le suffixe boutique : « 126234NG » → « 126234 »,
        « 179171G » → « 179171 »). Le cadran est filtré séparément par la suite, donc
        aucune perte de précision. Le fallback ne se déclenche QUE sur échec → sans
        risque pour les suffixes standard (116710BLNR résout du premier coup)."""
        out = self._search_query(ref)
        if out:
            return out
        base = re.sub(r"(?<=\d)[A-Za-z]{1,3}$", "", ref)
        if base and base != ref:
            return self._search_query(base)
        return out

    # --- étape 2 : ventes réelles (une carte = une vente) ---
    def sold_cards(self, ids: list[str], pages: int = 100) -> list[dict]:
        var = {"filterData": {"referenceNumber": ids}, "auctionType": "result",
               "pageNumber": 1, "pageSize": pages}
        r = self._sess().get(f"{_SITE}/api/listing/getListingData?variables="
                             + json.dumps(var), headers=_HDRS, timeout=35)
        soup = BeautifulSoup(r.text, "html.parser")
        out = []
        for card in soup.select("a[title]"):
            el = card.select_one("[data-prices]")
            if not el:
                continue
            try:
                eur = round(json.loads(el["data-prices"].replace("&quot;", '"'))
                            .get("netPayableEur") or 0)
            except (ValueError, KeyError):
                eur = 0
            if not eur:
                continue
            title = card.get("title", "")
            txt = re.sub(r"\s+", " ", card.get_text(" ", strip=True))
            m = _SIZE_RE.search(title)
            cfg = m.group(1) if m else ""
            mid = _REFNUM_RE.search(title)
            days = _DAYS_RE.search(txt)
            mdate = _DATE_RE.search(txt)
            out.append({
                "eur": eur, "cfg": cfg,
                "dial": variants.normalize_dial(cfg),
                "material": variants.normalize_material(cfg),
                "variant": mid.group(1) if mid else "",
                "missed_est": "Missed EST" in txt,
                "days": int(days.group(1).replace(",", "")) if days else None,
                "date": f"{mdate.group(1)} {mdate.group(2)}" if mdate else "",
            })
        return out

    def _stats(self, cards: list[dict], how: str, variant: str = "") -> dict | None:
        prices = [c["eur"] for c in cards]
        s = stats_from_prices(prices)
        if not s:
            return None
        # dernière vente = 1re carte du pool (EveryWatch renvoie les plus récentes
        # d'abord) — c'est LA donnée fraîche, plus parlante qu'une médiane lointaine
        last = cards[0]
        # LIQUIDITÉ EveryWatch : nb de ventes RÉELLES sur 12 mois glissants (fréquence
        # de transaction) — signal direct, sans proxy ni DDG, contrairement à WatchCharts.
        sales_12m = sum(1 for c in cards
                        if (ma := _months_ago(c.get("date"))) is not None and 0 <= ma <= 12)
        return {"ew_median_eur": s["median_eur"], "ew_p25_eur": s["p25_eur"],
                "ew_p75_eur": s["p75_eur"], "ew_n_sales": s["n_annonces"],
                "ew_last_eur": last["eur"], "ew_last_sale": last["date"],
                "ew_sales_12m": sales_12m,
                "ew_matched_by": how, "ew_variant": variant, "source": self.name}

    def _fetch_image(self, url: str):
        from .image_match import load_image
        try:
            return load_image(self._sess().get(url, headers=_HDRS, timeout=25).content)
        except Exception:
            return None

    # --- pipeline complet ---
    def stats(self, ref: str, cadran: str = "", matiere: str = "",
              image_url: str = "") -> dict | None:
        variants_ = self.search(ref)
        if not variants_:
            return None
        time.sleep(1)
        cards = self.sold_cards([v["id"] for v in variants_])
        # outliers : enchère adjugée sous l'estimation (« Missed EST » = liquidation)
        # et pièces restées 400+ jours invendues (bradées) → écartées des stats
        cards = [c for c in cards
                 if not c["missed_est"] and (c["days"] is None or c["days"] <= 400)]
        if not cards:
            return None

        my_dial = variants.normalize_dial(cadran)
        my_mat = variants.normalize_material(matiere)

        # pré-filtre texte : cadran (+ matière si connue)
        pool = [c for c in cards
                if (not my_dial or c["dial"] == my_dial)
                and (not my_mat or c["material"] == my_mat)]
        if not pool:
            # cadran inconnu du marché EW → on retombe sur l'agrégat réf
            return self._stats(cards, "ref")
        how = "dial+material" if my_dial else "ref"

        sub = sorted({c["variant"] for c in pool if c["variant"]})
        if len(sub) <= 1:
            return self._stats(pool, how, sub[0] if sub else "")

        # plusieurs sous-variantes (mêmes cadran/matière) → matching image si photo.
        # Garde-fou : sans info cadran, comparer la photo à 15+ variantes est long
        # (CLIP CPU) et ambigu → on reste sur l'agrégat, la prochaine collecte
        # apportera le cadran et resserrera.
        if image_url and (my_dial or len(sub) <= 8):
            chosen = self._match_variant(image_url, variants_, sub)
            if chosen:
                exact = [c for c in pool if c["variant"] == chosen]
                if exact:
                    return self._stats(exact, "variant-image", chosen)
        # sinon : agrégat cadran+matière (honnête, ±10%)
        return self._stats(pool, how)

    def _match_variant(self, image_url, variants_, sub_variants) -> str | None:
        """Choisit la sous-variante dont l'image est la plus proche de notre photo.
        Le matching image (CLIP/torch) est OPTIONNEL : s'il n'est pas installé
        (déploiement léger), on renvoie None → repli sur l'agrégat texte, sans crash."""
        try:
            from . import image_match
        except ImportError:
            return None
        from . import http_client
        try:
            q = image_match.load_image(http_client.session().get(image_url, timeout=25).content)
        except Exception:
            q = None
        if q is None:
            return None
        cands = [v for v in variants_ if v["ref_num"] in sub_variants and v["image"]]
        imgs, labels = [], []
        for v in cands:
            im = self._fetch_image(v["image"])
            if im is not None:
                imgs.append(im)
                labels.append(v["ref_num"])
        if len(imgs) < 2:
            return labels[0] if labels else None
        idx, score, marge = image_match.best_match(q, imgs)
        # marge faible = 2 candidates ~ex æquo → pas assez sûr → fallback texte
        if idx is None or marge < 0.01:
            return None
        return labels[idx]

    def close(self):
        pass
