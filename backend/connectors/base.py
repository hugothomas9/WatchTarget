"""Classe de base des connecteurs boutiques + normaliseur de fiche montre."""
import re
from html import unescape

from ..matching import normalize_ref
from ..brands import normalize_marque
from ..familles import famille_de

_TAG_RE = re.compile(r"<[^>]+>")
_DATE_ANY_RE = re.compile(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})")


def iso_date(s: str) -> str:
    """Normalise une date scrapée (2026/6/3, 2026-06-03…) en ISO YYYY-MM-DD.
    Indispensable pour que le tri par date soit correct toutes boutiques confondues."""
    m = _DATE_ANY_RE.search(s or "")
    if not m:
        return ""
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


def strip_html(html: str) -> str:
    """Convertit un fragment HTML en texte brut."""
    if not html:
        return ""
    text = _TAG_RE.sub(" ", html)
    text = unescape(text).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def make_uid(boutique, reference, url) -> str:
    """Identifiant unique d'une montre. Calculable depuis un listing (réf + url)
    SANS ouvrir la fiche → permet de sauter au re-scan ce qui est déjà en base."""
    return f"{boutique}:{normalize_ref(reference)}:{url}"


def watch(*, boutique, reference, url, marque="", modele="", prix_ttc=None,
          prix_ht=None, etat="", annee="", date_ajout_site="", description="",
          images=None, vendue=False, raw=None) -> dict:
    """Construit une fiche montre normalisée (schéma commun à tous les connecteurs)."""
    marque_n = normalize_marque(marque)
    return {
        "uid": make_uid(boutique, reference, url),
        "boutique": boutique,
        "reference": (reference or "").strip(),
        "marque": marque_n,
        "famille": famille_de(marque_n, modele or "", description or ""),
        "modele": modele or "",
        "prix_ttc": prix_ttc,
        "prix_ht": prix_ht,
        "etat": etat or "",
        "annee": str(annee or ""),
        "date_ajout_site": iso_date(date_ajout_site),
        "description": description or "",
        "url": url or "",
        "images": images or [],
        "vendue": vendue,
        "raw": raw or {},
    }


class BaseConnector:
    """Connecteur boutique. La collecte suit un entonnoir commun :
    dispo → (récent < max_age) → full set (boîte + papiers). Chaque connecteur
    implémente trois hooks : brands_to_scan(), iter_listing(brand), build_detail(item)."""
    boutique = "base"

    def __init__(self, entry: dict):
        self.entry = entry
        self.boutique = entry.get("boutique", self.boutique)
        self.base_url = entry.get("base_url", "")
        self.seen_uids: set[str] = set()  # uids déjà examinés (injecté par le pipeline)
        self.seen_sink = None             # callback pour persister un uid examiné
        self._seen_urls = None            # cache URLs examinées (dérivé des uids)
        self.available_only = entry.get("available_only", True)
        self.full_set_only = entry.get("full_set_only", True)
        self.max_age_days = entry.get("max_age_days", 120)

    # --- hooks à implémenter par chaque connecteur ---
    def brands_to_scan(self) -> list:
        """Liste des marques/catégories à parcourir (identifiants internes au site)."""
        raise NotImplementedError

    def iter_listing(self, brand):
        """Génère les items d'une marque, du plus récent au plus ancien.
        Chaque item est un dict portant au moins la clé 'vendue'."""
        raise NotImplementedError

    def build_detail(self, item) -> dict | None:
        """Transforme un item de listing en fiche complète (base.watch()),
        avec raw['accessoires'] renseigné pour le filtre full set."""
        raise NotImplementedError

    def item_uid(self, item) -> str | None:
        """UID calculable depuis le listing SANS ouvrir la fiche (réf + url).
        Renvoie None si impossible (ex: watchnian, réf seulement sur la fiche).
        Sert à sauter au re-scan ce qui est déjà en base (pas de re-fetch)."""
        return None

    def item_url(self, item) -> str | None:
        """URL de la fiche, lisible depuis le listing. Fallback de skip quand
        item_uid est impossible (watchnian : la réf n'est que sur la fiche)."""
        return None

    def _url_seen(self, url: str) -> bool:
        """True si une fiche à cette URL a déjà été examinée (uid = boutique:ref:url)."""
        if self._seen_urls is None:
            prefix = self.boutique + ":"
            self._seen_urls = {u.split(":", 2)[2] for u in self.seen_uids
                               if u.startswith(prefix) and u.count(":") >= 2}
        return url in self._seen_urls

    def _mark_seen(self, uid):
        """Mémorise une montre EXAMINÉE (full-set ou non) → jamais re-vérifiée."""
        if uid:
            self.seen_uids.add(uid)
            if self._seen_urls is not None and uid.count(":") >= 2:
                self._seen_urls.add(uid.split(":", 2)[2])
            if self.seen_sink:
                self.seen_sink(uid)

    # --- entonnoir commun ---
    def collect(self, mode: str):
        """mode full + max_workers>1 → fetch des fiches en parallèle (borné) ;
        sinon séquentiel (l'incrémental reste séquentiel : léger, arrêt sur déjà-vu)."""
        if mode == "full" and self.entry.get("max_workers", 1) > 1:
            yield from self._collect_parallel()
        else:
            yield from self._collect_sequential(mode)

    def _safe_build(self, item):
        try:
            return self.build_detail(item)
        except Exception:
            return None

    def _keep(self, w, age_days_fn, is_full_set_fn) -> bool:
        """Filtres post-fiche communs : dispo, récence, full set."""
        if self.available_only and w.get("vendue"):
            return False
        if self.max_age_days and w.get("date_ajout_site"):
            age = age_days_fn(w["date_ajout_site"])
            if age is not None and age > self.max_age_days:
                return False
        if self.full_set_only and not is_full_set_fn(
                (w.get("raw") or {}).get("accessoires", "")):
            return False
        return True

    def _collect_sequential(self, mode):
        from ..filters import is_full_set, age_days
        from ..config import MAX_ITEMS_INCREMENTAL
        run_seen = set()   # ids rencontrés dans CE run (doublons de pagination)
        for brand in self.brands_to_scan():
            try:
                yield from self._scan_brand_seq(
                    brand, mode, run_seen, is_full_set, age_days,
                    MAX_ITEMS_INCREMENTAL)
            except Exception:
                continue   # marque en 403/erreur (throttle) → sautée, reprise au run suivant

    def _scan_brand_seq(self, brand, mode, run_seen, is_full_set, age_days,
                        MAX_ITEMS_INCREMENTAL):
            old_streak = 0
            fresh = 0
            for item in self.iter_listing(brand):
                if self.available_only and item.get("vendue"):
                    continue
                uid = self.item_uid(item)   # skip sans ouvrir la fiche (déjà en base)
                iurl = self.item_url(item)  # fallback skip par URL (watchnian)
                key = uid or iurl
                if key is not None and key in run_seen:
                    continue    # doublon intra-run (pagination qui glisse), pas un déjà-vu
                already = ((uid is not None and uid in self.seen_uids)
                           or (iurl is not None and self._url_seen(iurl)))
                if already:
                    if mode == "incremental":
                        break   # nouveautés épuisées pour CETTE marque → marque suivante
                    continue
                if key is not None:
                    run_seen.add(key)
                w = self._safe_build(item)
                if w is None:
                    continue    # échec réseau → PAS marquée seen → retentée au prochain run
                if w["uid"] in run_seen and key is None:
                    continue    # doublon intra-run détecté après la fiche
                if mode == "incremental" and key is None and w["uid"] in self.seen_uids:
                    break       # déjà-vu détecté après la fiche → marque suivante
                run_seen.add(w["uid"])
                self._mark_seen(w["uid"])
                # récence : arrêt anticipé de la marque après une série d'anciennes
                if (self.max_age_days and w.get("date_ajout_site")
                        and (a := age_days(w["date_ajout_site"])) is not None
                        and a > self.max_age_days):
                    old_streak += 1
                    if old_streak >= 30:
                        break
                    continue
                old_streak = 0
                if not self._keep(w, age_days, is_full_set):
                    continue
                yield w
                fresh += 1
                if mode == "incremental" and fresh >= MAX_ITEMS_INCREMENTAL:
                    break

    def _collect_parallel(self):
        """Full scan avec fetch des fiches en parallèle borné (max_workers)."""
        from ..filters import is_full_set, age_days
        from concurrent.futures import ThreadPoolExecutor
        workers = self.entry.get("max_workers", 8)
        yielded = set()
        for brand in self.brands_to_scan():
            candidates, local = [], set()
            try:
                for item in self.iter_listing(brand):
                    if self.available_only and item.get("vendue"):
                        continue
                    uid = self.item_uid(item)
                    if uid is not None and uid in self.seen_uids:
                        continue            # déjà en base → on saute (pas de fetch)
                    iurl = self.item_url(item)
                    if iurl is not None and self._url_seen(iurl):
                        continue
                    key = uid or iurl
                    if key is not None:
                        if key in local:
                            continue        # doublon de pagination intra-marque
                        local.add(key)
                    candidates.append(item)
            except Exception:
                pass       # marque en 403/erreur → on traite ce qu'on a, marque suivante
            if not candidates:
                continue
            with ThreadPoolExecutor(max_workers=workers) as ex:
                for w in ex.map(self._safe_build, candidates):
                    if w is None or w["uid"] in yielded:
                        continue
                    yielded.add(w["uid"])
                    self._mark_seen(w["uid"])   # DB write : thread principal only
                    if self._keep(w, age_days, is_full_set):
                        yield w
