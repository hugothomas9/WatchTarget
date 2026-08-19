"""Configuration centrale : chemins, HTTP, change, coûts d'import, secrets (.env)."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent      # .../scrap-montres
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "montres.db"
TARGETS_PATH = BASE_DIR / "backend" / "targets.json"


def _load_env():
    """Charge scrap-montres/.env (KEY=VALUE) sans dépendance externe.
    Ne remplace jamais une variable déjà présente dans l'environnement."""
    env = BASE_DIR / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


_load_env()

# Proxy résidentiel (voir docs/infra-proxy-scaling.md). Vide = connexion directe.
# Format : http://user:pass@gateway:port — dans .env : PROXY_URL=...
PROXY_URL = os.environ.get("PROXY_URL", "")

# Webhook Discord pour les alertes (nouvelles cibles / opportunités). Vide = off.
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

# Bot Telegram pour les alertes cibles (voir docs/specs/cibles-motscles-telegram.md).
# Vide = off (no-op silencieux). Token via @BotFather, chat_id via @userinfobot.
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# Base de données : vide = SQLite local (DB_PATH) ; sinon URL PostgreSQL en prod
# (ex postgresql://user:pass@host:5432/scrapmontres). Voir docs/specs/deploiement-*.
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Mode mono-utilisateur LOCAL (SQLite, pas de domaine → le Login Widget Telegram ne
# fonctionne pas) : l'accès sans session garde les droits admin sur les alertes.
# En PROD (DATABASE_URL défini), un visiteur anonyme n'a AUCUN accès aux alertes
# et /api/collecte est réservé à l'admin (cf. api._scope) — faille corrigée en revue.
LOCAL_ADMIN = not DATABASE_URL

# --- HTTP (politesse anti-bot) ---
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
TIMEOUT = 25
REQUEST_DELAY = 0.3
MAX_RETRIES = 2

# Limite de fiches parcourues par boutique en mode incrémental.
MAX_ITEMS_INCREMENTAL = 60

# --- Coûts pris en compte dans la « marge nette » des opportunités ---
# MODE VALISE (choix de Hugo) : la montre revient dans les bagages → douane,
# TVA d'import et port désactivés. Seule reste la commission de la plateforme
# de revente (Chrono24 ~6,5%), payée si on vend là où on mesure les prix.
# Pour repasser en mode « import déclaré » : 0.045 / 0.20 / 120.
DOUANE_PCT = 0.0
TVA_IMPORT_PCT = 0.0
PORT_ASSURANCE_EUR = 0
COMMISSION_VENTE_PCT = 0.065  # commission plateforme à la revente

# --- Auto-pricing marché (Chrono24) ---
SPREAD_MIN_EUR = 700          # seuil d'opportunité : médiane EU − détaxé JP
LIQUIDITY_MIN_LISTINGS = 5    # liquidité mini : nb d'annonces actives pour la réf
MARKET_CACHE_DAYS = 30        # TTL du prix marché par réf
MARKET_BAND_EUR = (1500, 15000)   # bande de prix détaxé où chercher les spreads
MARKET_DELAY = 1.5          # curl_cffi + proxy rotatif : cadence rapide OK
MARKET_MAX_LISTINGS = 60      # annonces max lues par réf (1 page suffit)

# --- Change JPY -> EUR (API gratuite, sans clé) ---
FX_API_URL = "https://api.frankfurter.app/latest?from=JPY&to=EUR"
JPY_EUR_CACHE = DATA_DIR / "fx_cache.json"
FX_CACHE_TTL_HOURS = 24
# Taux de repli si l'API est injoignable (≈ valeur observée 2026-06, à rafraîchir).
JPY_EUR_FALLBACK = 0.0054
