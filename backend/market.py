"""Prix marché européen par référence — cœur de l'auto-pricing.

Sources pluggables (via Playwright, les deux sites bloquent le HTTP simple) :
  - chrono24 : annonces ACTIVES en € (profondeur de marché + prix affichés)
  - ebay     : annonces VENDUES en € (prix de transaction réels)

Le scan (market_scan.py) interroge une réf, calcule des stats robustes
(médiane / P25 / P75, nb d'annonces) et les cache dans market_prices (TTL).
"""
import re
import statistics

from . import config

_PRICE_RE = re.compile(r"(\d[\d\s  .,]{2,12})\s*€")


def parse_prices_eur(text: str) -> list[float]:
    """Extrait tous les prix en euros d'un texte/HTML (formats FR : espaces
    fines, points de milliers, virgule décimale)."""
    out = []
    for raw in _PRICE_RE.findall(text):
        s = re.sub(r"[\s  ]", "", raw)
        # virgule décimale finale (",50") → on la coupe ; les points = milliers
        s = re.sub(r",\d{1,2}$", "", s).replace(".", "").replace(",", "")
        if s.isdigit():
            v = float(s)
            if 100 <= v <= 500_000:      # garde-fou anti-bruit (années, réfs…)
                out.append(v)
    return out


def stats_from_prices(prices: list[float]) -> dict | None:
    """Stats robustes sur une liste de prix. None si trop peu de données."""
    if len(prices) < 2:
        return None
    prices = sorted(prices)
    # coupe les extrêmes aberrants (annonces fantaisistes) si assez de points
    if len(prices) >= 8:
        k = max(1, len(prices) // 10)
        prices = prices[k:-k]
    qs = statistics.quantiles(prices, n=4) if len(prices) >= 3 else \
        [prices[0], statistics.median(prices), prices[-1]]
    return {
        "median_eur": round(statistics.median(prices), 2),
        "p25_eur": round(qs[0], 2),
        "p75_eur": round(qs[2], 2),
        "n_annonces": len(prices),
    }


class MarketSource:
    """Contrat d'une source de prix marché."""
    name = "base"

    def fetch_prices(self, reference: str) -> list[float]:
        """Prix en € observés pour cette référence (annonces ou ventes)."""
        raise NotImplementedError


class PlaywrightSource(MarketSource):
    """Base commune des sources navigateur : un seul browser réutilisé."""
    def __init__(self):
        self._pw = None
        self._browser = None
        self._ctx = None

    # inutiles pour lire des prix (le texte du DOM n'a pas besoin de CSS)
    _BLOCKED = ("image", "media", "font", "stylesheet")

    def _page(self):
        from playwright.sync_api import sync_playwright
        if self._pw is None:
            self._pw = sync_playwright().start()
            args = ["--disable-blink-features=AutomationControlled"]
            kw = {}
            if config.PROXY_URL:            # proxy résidentiel (IP rotatives)
                # Chromium exige les identifiants SÉPARÉS de l'URL du serveur
                from urllib.parse import urlparse
                u = urlparse(config.PROXY_URL)
                kw["proxy"] = {
                    "server": f"{u.scheme}://{u.hostname}:{u.port}",
                    "username": u.username or "",
                    "password": u.password or "",
                }
            try:
                # vrai Chrome installé : empreinte authentique, bien moins
                # détectable que le headless-shell de Playwright (C24 bloquait)
                self._browser = self._pw.chromium.launch(
                    headless=True, channel="chrome", args=args, **kw)
            except Exception:
                self._browser = self._pw.chromium.launch(
                    headless=True, args=args, **kw)
            self._ctx = self._browser.new_context(
                locale="fr-FR", viewport={"width": 1280, "height": 900})
            # bloque images/médias/fontes : ~80% de bande passante en moins
            # (coût proxy) et pages bien plus rapides — on ne lit que du texte
            self._ctx.route(
                "**/*",
                lambda route: route.abort()
                if route.request.resource_type in self._BLOCKED
                else route.continue_())
        return self._ctx.new_page()

    def close(self):
        if self._pw is not None:
            self._browser.close()
            self._pw.stop()
            self._pw = None


class Chrono24Source:
    """Annonces actives Chrono24 (€) pour une référence.

    On récupère le HTML server-rendu de la page de recherche via curl_cffi en
    imitant l'empreinte TLS de Safari (SEUL le fingerprint Safari passe le
    « managed challenge » Cloudflare de Chrono24, même à travers le proxy).
    Pas de navigateur → rapide et léger (~0,6 Mo/réf, aucune image).
    Cartes `.js-listing-item`, prix `.wt-listing-item-price` ; le total réel
    d'annonces (« 68 annonces ») sert de métrique de liquidité (n_annonces)."""
    name = "chrono24"
    SEARCH = "https://www.chrono24.fr/search/index.htm?dosearch=true&query={ref}"
    _IMPERSONATE = ("safari17_0", "safari17_2", "safari15_5")
    _COUNT_RE = re.compile(r"([\d\s  ]{1,9})\s*annonces")

    def _proxies(self):
        return ({"http": config.PROXY_URL, "https": config.PROXY_URL}
                if config.PROXY_URL else None)

    def fetch(self, reference: str) -> tuple[list[float], int | None]:
        from curl_cffi import requests as cr
        from bs4 import BeautifulSoup
        url = self.SEARCH.format(ref=reference)
        html = None
        last = None
        for imp in self._IMPERSONATE:      # rotation de fingerprint si échec
            try:
                r = cr.get(url, impersonate=imp, proxies=self._proxies(),
                           timeout=35)
                if r.status_code == 200 and "js-listing-item" in r.text:
                    html = r.text
                    break
                last = f"HTTP {r.status_code}"
            except Exception as e:
                last = f"{type(e).__name__}"
        if html is None:
            raise RuntimeError(f"chrono24 inaccessible ({last})")

        soup = BeautifulSoup(html, "html.parser")
        prices = []
        for el in soup.select(".js-listing-item .wt-listing-item-price"):
            prices.extend(parse_prices_eur(el.get_text(" ", strip=True)))
        total = None
        m = self._COUNT_RE.search(soup.get_text(" "))
        if m:
            digits = re.sub(r"[^0-9]", "", m.group(1))
            total = int(digits) if digits else None
        return prices, total

    def fetch_prices(self, reference: str) -> list[float]:
        return self.fetch(reference)[0]

    def close(self):
        pass


class WatchChartsSource:
    """Enrichissement WatchCharts : jours-pour-vendre + volatilité par référence.

    Le prix marché de WC est rendu en JS (API payante) → non récupéré.
    Mais Median Days on Market et Volatility SONT dans le HTML statique.
    Pipeline : DDG-lite (sans proxy) résout réf→fiche modèle, puis curl_cffi
    +Safari+proxy lit la fiche (WC est derrière Cloudflare comme Chrono24)."""
    name = "watchcharts"
    _UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
    _DAYS_RE = re.compile(r"Median Days on Market\s+([\d.]+)")
    _VOL_RE = re.compile(r"(?:Market )?Volatility\s+([\d.]+)\s*%")

    def _proxies(self):
        return ({"http": config.PROXY_URL, "https": config.PROXY_URL}
                if config.PROXY_URL else None)

    def resolve(self, reference: str) -> str | None:
        """réf → URL de fiche modèle WatchCharts, via DuckDuckGo lite (sans proxy)."""
        from curl_cffi import requests as cr
        from .matching import normalize_ref
        r = cr.post("https://lite.duckduckgo.com/lite/",
                    data={"q": f"watchcharts watch_model {reference}"},
                    impersonate="chrome124", headers={"User-Agent": self._UA},
                    timeout=25)
        urls = re.findall(r'(https?://watchcharts\.com/watch_model/[^\s"<]+)', r.text)
        rn = normalize_ref(reference)
        for u in urls:                       # priorité au slug qui contient la réf
            if rn and rn in normalize_ref(u):
                return u
        return urls[0] if urls else None

    def read(self, url: str) -> dict:
        """Lit une fiche modèle WC connue → {days, vol, model_url}. Pas de DDG."""
        from curl_cffi import requests as cr
        if not url.endswith("/overview"):
            url = url.rstrip("/") + "/overview"
        html = cr.get(url, impersonate="safari17_0", proxies=self._proxies(),
                      timeout=30).text
        txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
        d = self._DAYS_RE.search(txt)
        v = self._VOL_RE.search(txt)
        return {"days": float(d.group(1)) if d else None,
                "vol": float(v.group(1)) if v else None,
                "model_url": url}

    def stats(self, reference: str, known_url: str | None = None) -> dict | None:
        """{days, vol, model_url}. Réutilise known_url si fourni (0 requête DDG)."""
        url = known_url or self.resolve(reference)   # DDG seulement si pas de cache
        if not url:
            return None
        return self.read(url)


class EbaySoldSource(PlaywrightSource):
    """Annonces VENDUES eBay.fr (€) pour une référence = prix de transaction.
    On ne lit que les éléments PRIX des cartes (pas les frais de port)."""
    name = "ebay_sold"
    SEARCH = ("https://www.ebay.fr/sch/i.html?_nkw={ref}"
              "&LH_Sold=1&LH_Complete=1&_sacat=31387")

    def fetch_prices(self, reference: str) -> list[float]:
        page = self._page()
        try:
            page.goto(self.SEARCH.format(ref=reference),
                      timeout=45000, wait_until="domcontentloaded")
            page.wait_for_timeout(2500)
            texts = page.locator(
                ".s-item__price, .s-card__price").all_inner_texts()
            prices = []
            for t in texts:
                prices.extend(parse_prices_eur(t))
            return prices
        finally:
            page.close()
