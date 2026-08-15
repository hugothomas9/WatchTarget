"""Registre des boutiques et mapping type-de-connecteur.

Filtres de collecte (entonnoir commun, cf. base.BaseConnector) :
  available_only  : on ne garde que les montres en stock
  full_set_only   : boîte + papiers obligatoires (付属品)
  max_age_days    : on se limite aux annonces récentes quand la date est connue
  max_pages_per_brand : borne le crawl des gros sites (les plus récentes d'abord)
"""
from .watchnian import WatchnianConnector
from .cywatch import CywatchConnector
from .kamekichi import KamekichiConnector
from .jackroad import JackroadConnector
from .firekids import FirekidsConnector
from .shopify import ShopifyConnector
from .eccube import EccubeConnector
from .makeshop import MakeShopConnector
from .brandbank import BrandBankConnector
from .galleryrare import GalleryRareConnector
from .yukizaki import YukizakiConnector
from .housekihiroba import HousekihirobaConnector
from .gmt import GmtConnector

CONNECTORS: dict = {
    "watchnian": WatchnianConnector,
    "cywatch": CywatchConnector,
    "kamekichi": KamekichiConnector,
    "jackroad": JackroadConnector,
    "firekids": FirekidsConnector,
    "shopify": ShopifyConnector,
    "eccube": EccubeConnector,
    "makeshop": MakeShopConnector,
    "brandbank": BrandBankConnector,
    "galleryrare": GalleryRareConnector,
    "yukizaki": YukizakiConnector,
    "housekihiroba": HousekihirobaConnector,
    "gmt": GmtConnector,
}

# max_workers : fetch des fiches en parallèle (borné) en mode full — assez bas
# pour rester poli avec les serveurs (throttle jackroad observé en séquentiel long).
_FILTERS = {"available_only": True, "full_set_only": True, "max_age_days": 120,
            "max_workers": 6}

BOUTIQUES: list = [
    {"boutique": "CY Watch", "connector": "cywatch", "all_brands": True, **_FILTERS},
    {"boutique": "Kame-Kichi", "connector": "kamekichi", "all_brands": True, **_FILTERS},
    {"boutique": "Fire Kids", "connector": "firekids", "all_brands": True,
     "max_pages_per_brand": 200, **_FILTERS},
    {"boutique": "Jack Road", "connector": "jackroad", "all_brands": True,
     "max_pages_per_brand": 3, **_FILTERS},
    {"boutique": "Watchnian", "connector": "watchnian", "all_brands": True,
     "max_pages_per_brand": 2, **_FILTERS},
    # Boutiques Vague 1 : max_age_days=None — la date affichée = date de MISE EN LIGNE
    # (souvent des mois), pas un signal de fraîcheur : la montre reste EN STOCK. Le bon
    # filtre pour une boutique = la disponibilité (available_only), pas la récence.
    # --- Vague 1 : boutiques Shopify (connecteur générique, tout dans le JSON) ---
    {"boutique": "Moon Phase", "connector": "shopify",
     "base_url": "https://moon-phase.jp", "all_brands": True,
     **_FILTERS, "max_age_days": None},
    # timeseek/brand-yukichi : leur catalogue en ligne est ENTIÈREMENT en OutOfStock
    # (bouton « 売り切れ » désactivé partout — ils ne vendent pas via checkout en ligne).
    # Le flag `available` reflète bien ce OutOfStock → on l'utilise (trust_available par
    # défaut = True) : ces boutiques ne remontent que ce qui est réellement en vente.
    {"boutique": "Timeseek", "connector": "shopify",
     "base_url": "https://timeseek.net", "all_brands": True,
     **_FILTERS, "max_age_days": None},
    # brand-yukichi est un recycle-shop généraliste → on se limite aux montres
    {"boutique": "Brand Yukichi", "connector": "shopify",
     "base_url": "https://brand-yukichi.jp", "collections": ["watch"],
     "all_brands": True, **_FILTERS, "max_age_days": None},
    # --- Vague 1 : boutiques EC-CUBE (fiche ouverte par produit : réf sur la fiche) ---
    {"boutique": "Ginza LINKS", "connector": "eccube",
     "base_url": "https://ginzalinks.com", "all_brands": True,
     "max_pages_per_brand": 20, **_FILTERS, "max_age_days": None},
    {"boutique": "The Capital", "connector": "eccube",
     "base_url": "https://www.thecapital-watches.com", "categories": ["1"],
     "all_brands": True, "max_pages_per_brand": 20, **_FILTERS, "max_age_days": None},
    {"boutique": "Satin Doll", "connector": "eccube",
     "base_url": "https://www.satindollweb.com", "all_brands": True,
     "max_pages_per_brand": 20, **_FILTERS, "max_age_days": None},
    # --- Vague 2 : boutiques MakeShop (sitemap → fiches JSON-LD ProductGroup) ---
    # date = lastmod du sitemap (≈ mise en ligne), pas un signal de fraîcheur → max_age None.
    # séquentiel (max_workers 1) : chaque fiche = 1 fetch, on reste poli sur shopserve.
    {"boutique": "King's Road", "connector": "makeshop",
     "base_url": "https://www.kingsroad.jp", "all_brands": True,
     **_FILTERS, "max_age_days": None, "max_workers": 4},
    # 7HOURS : même plateforme, JSON-LD Product (pas ProductGroup), UTF-8
    {"boutique": "7HOURS", "connector": "makeshop",
     "base_url": "https://7hours.jp", "all_brands": True,
     **_FILTERS, "max_age_days": None, "max_workers": 4},
    # --- Vague 3 : boutiques artisanales (une plateforme différente chacune) ---
    # date de mise en ligne indisponible/peu fiable → max_age_days None (comme vague 1/2).
    # BrandBank : Color Me Shop, EUC-JP, pas de JSON-LD (meta og + specs corps)
    {"boutique": "BrandBank", "connector": "brandbank",
     "base_url": "https://www.brandbank-watchshop.com", "all_brands": True,
     **_FILTERS, "max_age_days": None, "max_workers": 4},
    # Gallery Rare : FutureShop, JSON-LD Product par fiche
    {"boutique": "Gallery Rare", "connector": "galleryrare",
     "base_url": "https://www.g-rare.com", "all_brands": True,
     **_FILTERS, "max_age_days": None, "max_workers": 4},
    # Yukizaki : gc-yukizaki (.com = cache cassé → le connecteur scrape .jp en interne),
    # JSON-LD Product par fiche
    {"boutique": "Yukizaki", "connector": "yukizaki",
     "base_url": "https://gc-yukizaki.com", "all_brands": True,
     **_FILTERS, "max_age_days": None, "max_workers": 4},
    # Housekihiroba : ASP.NET, Shift_JIS (cp932), pagination ?p=N
    {"boutique": "Housekihiroba", "connector": "housekihiroba",
     "base_url": "https://housekihiroba.jp", "all_brands": True,
     "max_pages_per_brand": 30, **_FILTERS, "max_age_days": None, "max_workers": 4},
    # GMT : gmt-j.com, WAF → curl_cffi interne, API JSON déjà filtrée « en stock »
    {"boutique": "GMT", "connector": "gmt",
     "base_url": "https://www.gmt-j.com", "all_brands": True,
     **_FILTERS, "max_age_days": None, "max_workers": 4},
]
