# Scraper Montres JP — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construire un outil qui scrape des boutiques de montres japonaises, centralise leur stock dans SQLite, et fait ressortir les montres ciblées avec leur prix détaxé en € et le bénéfice estimé à la revente en France.

**Architecture:** Backend Python modulaire calqué sur le projet `scrap alternance` : connecteurs (1 par boutique) → pipeline → SQLite → API FastAPI. Front React/Vite à 3 pages (Stock, Cibles, Favoris). Modules de logique pure (`fx`, `pricing`, `matching`) testés en TDD et indépendants des sites.

**Tech Stack:** Python 3.12, requests + BeautifulSoup (Playwright headless en fallback), SQLite, FastAPI + uvicorn, React 18 + Vite, pytest.

## Global Constraints

- **Racine projet :** `/Users/famillethomas/Downloads/Projet/scrap-montres/`. Tous les chemins ci-dessous sont relatifs à cette racine.
- **Pas de git pour l'instant** — ignorer toute étape "commit". Un "checkpoint" = exécuter les tests de la tâche et la marquer faite.
- **Taxe conso JP = 10%, prix affichés en TTC (税込).** Prix détaxé = HT (税抜) si donné, sinon `prix_ttc / 1.10` (jamais `× 0.90`).
- **Bénéfice principal = `revente_fr − prix_detaxe_eur − couts_optionnels_eur`** (pas de douane/port/commission sauf via `couts_optionnels_eur`).
- **Langue du code :** commentaires et docstrings en français, comme le projet alternance.
- **Politesse scraping :** délai entre requêtes, retries, user-agent réaliste (réutiliser le pattern `http_client.py`).

---

### Task 1: Scaffold projet + config + requirements

**Files:**
- Create: `backend/__init__.py` (vide)
- Create: `backend/config.py`
- Create: `backend/requirements.txt`
- Create: `data/.gitkeep` (vide)
- Create: `tests/__init__.py` (vide)

**Interfaces:**
- Produces: `config.BASE_DIR`, `config.DATA_DIR`, `config.DB_PATH`, `config.TARGETS_PATH`, `config.USER_AGENT`, `config.TIMEOUT`, `config.REQUEST_DELAY`, `config.MAX_RETRIES`, `config.JPY_EUR_CACHE`, `config.FX_API_URL`.

- [ ] **Step 1: Créer `backend/requirements.txt`**

```
requests>=2.31
beautifulsoup4>=4.12
fastapi>=0.110
uvicorn>=0.29
pytest>=8.0
```

- [ ] **Step 2: Créer `backend/config.py`**

```python
"""Configuration centrale : chemins, HTTP, change."""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent      # .../scrap-montres
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "montres.db"
TARGETS_PATH = BASE_DIR / "backend" / "targets.json"

# --- HTTP (politesse anti-bot) ---
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
TIMEOUT = 25
REQUEST_DELAY = 1.0
MAX_RETRIES = 2

# Limite de fiches parcourues par boutique en mode incrémental.
MAX_ITEMS_INCREMENTAL = 60

# --- Change JPY -> EUR (API gratuite, sans clé) ---
FX_API_URL = "https://api.frankfurter.app/latest?from=JPY&to=EUR"
JPY_EUR_CACHE = DATA_DIR / "fx_cache.json"
FX_CACHE_TTL_HOURS = 24
# Taux de repli si l'API est injoignable (≈ valeur récente, à ajuster).
JPY_EUR_FALLBACK = 0.0060
```

- [ ] **Step 3: Créer les fichiers vides**

```bash
mkdir -p backend tests data
touch backend/__init__.py tests/__init__.py data/.gitkeep
```

- [ ] **Step 4: Vérifier l'import**

Run: `cd /Users/famillethomas/Downloads/Projet/scrap-montres && python -c "from backend import config; print(config.DB_PATH)"`
Expected: affiche `.../scrap-montres/data/montres.db`

- [ ] **Step 5: Checkpoint** (pas de git)

---

### Task 2: Module change `fx.py` (JPY → EUR, caché)

**Files:**
- Create: `backend/fx.py`
- Test: `tests/test_fx.py`

**Interfaces:**
- Consumes: `config.FX_API_URL`, `config.JPY_EUR_CACHE`, `config.FX_CACHE_TTL_HOURS`, `config.JPY_EUR_FALLBACK`.
- Produces: `fx.jpy_to_eur(amount_jpy: float, rate: float | None = None) -> float`, `fx.get_rate(force: bool = False) -> float`.

- [ ] **Step 1: Écrire le test qui échoue**

```python
# tests/test_fx.py
from backend import fx

def test_jpy_to_eur_applique_le_taux():
    assert fx.jpy_to_eur(100000, rate=0.006) == 600.0

def test_jpy_to_eur_arrondi_2_decimales():
    assert fx.jpy_to_eur(123456, rate=0.0061) == round(123456 * 0.0061, 2)

def test_get_rate_utilise_le_fallback_si_pas_de_cache(monkeypatch, tmp_path):
    from backend import config
    monkeypatch.setattr(config, "JPY_EUR_CACHE", tmp_path / "fx.json")
    def boom(*a, **k):
        raise RuntimeError("offline")
    monkeypatch.setattr(fx, "_fetch_remote", boom)
    assert fx.get_rate() == config.JPY_EUR_FALLBACK
```

- [ ] **Step 2: Lancer le test (échec attendu)**

Run: `cd /Users/famillethomas/Downloads/Projet/scrap-montres && python -m pytest tests/test_fx.py -v`
Expected: FAIL (module `fx` inexistant)

- [ ] **Step 3: Écrire `backend/fx.py`**

```python
"""Taux de change JPY -> EUR via API gratuite, avec cache disque journalier."""
import json
from datetime import datetime, timezone

import requests

from . import config


def jpy_to_eur(amount_jpy: float, rate: float | None = None) -> float:
    """Convertit un montant en yens vers l'euro. `rate` = EUR pour 1 JPY."""
    if rate is None:
        rate = get_rate()
    return round(amount_jpy * rate, 2)


def _fetch_remote() -> float:
    resp = requests.get(config.FX_API_URL, timeout=config.TIMEOUT)
    resp.raise_for_status()
    return float(resp.json()["rates"]["EUR"])


def _read_cache():
    try:
        data = json.loads(config.JPY_EUR_CACHE.read_text())
        ts = datetime.fromisoformat(data["fetched_at"])
        age_h = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
        if age_h < config.FX_CACHE_TTL_HOURS:
            return float(data["rate"])
    except (FileNotFoundError, KeyError, ValueError):
        pass
    return None


def _write_cache(rate: float):
    config.JPY_EUR_CACHE.parent.mkdir(parents=True, exist_ok=True)
    config.JPY_EUR_CACHE.write_text(json.dumps(
        {"rate": rate, "fetched_at": datetime.now(timezone.utc).isoformat()}
    ))


def get_rate(force: bool = False) -> float:
    """Renvoie le taux EUR/JPY (cache 24h, fallback si API injoignable)."""
    if not force:
        cached = _read_cache()
        if cached is not None:
            return cached
    try:
        rate = _fetch_remote()
        _write_cache(rate)
        return rate
    except (requests.RequestException, KeyError, ValueError):
        return config.JPY_EUR_FALLBACK
```

- [ ] **Step 4: Lancer le test (succès attendu)**

Run: `cd /Users/famillethomas/Downloads/Projet/scrap-montres && python -m pytest tests/test_fx.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Checkpoint**

---

### Task 3: Module `pricing.py` (détaxe + bénéfice)

**Files:**
- Create: `backend/pricing.py`
- Test: `tests/test_pricing.py`

**Interfaces:**
- Consumes: `fx.jpy_to_eur`.
- Produces:
  - `pricing.prix_detaxe_jpy(prix_ttc: float | None, prix_ht: float | None) -> float | None`
  - `pricing.compute_benef(prix_ttc, prix_ht, revente_min, revente_max, rate, couts_opt=0.0) -> dict`
    retournant `{"prix_detaxe_jpy", "prix_detaxe_eur", "benef_min", "benef_max", "benef_pct_min", "benef_pct_max"}`.

- [ ] **Step 1: Écrire le test qui échoue**

```python
# tests/test_pricing.py
from backend import pricing

def test_detaxe_utilise_le_ht_si_present():
    assert pricing.prix_detaxe_jpy(prix_ttc=110000, prix_ht=100000) == 100000

def test_detaxe_divise_le_ttc_par_1_1_si_pas_de_ht():
    assert pricing.prix_detaxe_jpy(prix_ttc=110000, prix_ht=None) == 100000.0

def test_detaxe_none_si_aucun_prix():
    assert pricing.prix_detaxe_jpy(None, None) is None

def test_compute_benef_complet():
    r = pricing.compute_benef(
        prix_ttc=1100000, prix_ht=None,
        revente_min=9500, revente_max=11000,
        rate=0.006, couts_opt=0.0,
    )
    assert r["prix_detaxe_jpy"] == 1000000.0
    assert r["prix_detaxe_eur"] == 6000.0
    assert r["benef_min"] == 3500.0
    assert r["benef_max"] == 5000.0
    assert round(r["benef_pct_min"], 4) == round(3500 / 6000, 4)

def test_compute_benef_soustrait_couts_optionnels():
    r = pricing.compute_benef(
        prix_ttc=1100000, prix_ht=None,
        revente_min=9500, revente_max=11000,
        rate=0.006, couts_opt=500.0,
    )
    assert r["benef_min"] == 3000.0
```

- [ ] **Step 2: Lancer le test (échec attendu)**

Run: `cd /Users/famillethomas/Downloads/Projet/scrap-montres && python -m pytest tests/test_pricing.py -v`
Expected: FAIL (module `pricing` inexistant)

- [ ] **Step 3: Écrire `backend/pricing.py`**

```python
"""Détaxe japonaise (10%) et calcul du bénéfice d'arbitrage vers la France."""
from . import fx

TVA_JP = 0.10  # taxe à la consommation japonaise


def prix_detaxe_jpy(prix_ttc: float | None, prix_ht: float | None) -> float | None:
    """Prix détaxé en yens : le HT (税抜) s'il est donné, sinon TTC / 1.10."""
    if prix_ht is not None:
        return float(prix_ht)
    if prix_ttc is not None:
        return round(float(prix_ttc) / (1 + TVA_JP), 2)
    return None


def compute_benef(prix_ttc, prix_ht, revente_min, revente_max,
                  rate: float, couts_opt: float = 0.0) -> dict:
    """Calcule le prix détaxé en € et le bénéfice min/max vs fourchette de revente FR."""
    detaxe_jpy = prix_detaxe_jpy(prix_ttc, prix_ht)
    if detaxe_jpy is None:
        return {"prix_detaxe_jpy": None, "prix_detaxe_eur": None,
                "benef_min": None, "benef_max": None,
                "benef_pct_min": None, "benef_pct_max": None}
    detaxe_eur = fx.jpy_to_eur(detaxe_jpy, rate=rate)
    cout = detaxe_eur + couts_opt
    benef_min = round(revente_min - cout, 2)
    benef_max = round(revente_max - cout, 2)
    return {
        "prix_detaxe_jpy": detaxe_jpy,
        "prix_detaxe_eur": detaxe_eur,
        "benef_min": benef_min,
        "benef_max": benef_max,
        "benef_pct_min": (benef_min / cout) if cout else None,
        "benef_pct_max": (benef_max / cout) if cout else None,
    }
```

- [ ] **Step 4: Lancer le test (succès attendu)**

Run: `cd /Users/famillethomas/Downloads/Projet/scrap-montres && python -m pytest tests/test_pricing.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Checkpoint**

---

### Task 4: Module `matching.py` (référence ↔ cible)

**Files:**
- Create: `backend/matching.py`
- Test: `tests/test_matching.py`

**Interfaces:**
- Produces:
  - `matching.normalize_ref(ref: str) -> str` (majuscules, sans espaces/ponctuation/préfixes "ref"/"référence").
  - `matching.match_target(watch_ref: str, targets: list[dict]) -> dict | None` (renvoie la cible dont une `references` normalisée est contenue dans la réf normalisée de la montre, ou l'inverse).

- [ ] **Step 1: Écrire le test qui échoue**

```python
# tests/test_matching.py
from backend import matching

TARGETS = [
    {"id": "sub-126610LN", "references": ["126610LN", "126610 LN"]},
    {"id": "speedmaster-311", "references": ["311.30.42.30.01.005"]},
]

def test_normalize_enleve_espaces_casse_prefixe():
    assert matching.normalize_ref("Ref. 126610 LN") == "126610LN"
    assert matching.normalize_ref("référence: 126610-ln") == "126610LN"

def test_match_trouve_la_cible_malgre_variante():
    t = matching.match_target("Rolex Submariner Ref 126610LN", TARGETS)
    assert t["id"] == "sub-126610LN"

def test_match_none_si_aucune_cible():
    assert matching.match_target("Seiko SKX007", TARGETS) is None
```

- [ ] **Step 2: Lancer le test (échec attendu)**

Run: `cd /Users/famillethomas/Downloads/Projet/scrap-montres && python -m pytest tests/test_matching.py -v`
Expected: FAIL

- [ ] **Step 3: Écrire `backend/matching.py`**

```python
"""Rapprochement tolérant entre une référence scrapée et les cibles du JSON."""
import re

_PREFIX_RE = re.compile(r"\b(ref(erence)?|référence|réf|model[e]?)\b\.?:?", re.I)
_NONALNUM_RE = re.compile(r"[^A-Z0-9]")


def normalize_ref(ref: str) -> str:
    """Normalise une référence : retire préfixes, ponctuation, espaces, casse."""
    if not ref:
        return ""
    ref = _PREFIX_RE.sub(" ", ref)
    return _NONALNUM_RE.sub("", ref.upper())


def match_target(watch_ref: str, targets: list[dict]) -> dict | None:
    """Renvoie la cible dont une référence normalisée matche celle de la montre."""
    w = normalize_ref(watch_ref)
    if not w:
        return None
    for t in targets:
        for ref in t.get("references", []):
            n = normalize_ref(ref)
            if n and (n in w or w in n):
                return t
    return None
```

- [ ] **Step 4: Lancer le test (succès attendu)**

Run: `cd /Users/famillethomas/Downloads/Projet/scrap-montres && python -m pytest tests/test_matching.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Checkpoint**

---

### Task 5: `targets.json` + loader

**Files:**
- Create: `backend/targets.json`
- Create: `backend/targets.py`
- Test: `tests/test_targets.py`

**Interfaces:**
- Consumes: `config.TARGETS_PATH`.
- Produces: `targets.load_targets(path=None) -> list[dict]`. Chaque cible : `id, marque, modele, references[], revente_fr_min, revente_fr_max, criteres{}, couts_optionnels_eur`.

- [ ] **Step 1: Créer `backend/targets.json` (exemple amorce, à compléter par l'utilisateur)**

```json
{
  "targets": [
    {
      "id": "rolex-submariner-126610LN",
      "marque": "Rolex",
      "modele": "Submariner Date",
      "references": ["126610LN", "126610 LN"],
      "revente_fr_min": 9500,
      "revente_fr_max": 11000,
      "criteres": { "etat_min": "très bon", "annee_min": 2015 },
      "couts_optionnels_eur": 0
    }
  ]
}
```

- [ ] **Step 2: Écrire le test qui échoue**

```python
# tests/test_targets.py
from backend import targets

def test_load_targets_renvoie_une_liste():
    ts = targets.load_targets()
    assert isinstance(ts, list)
    assert ts and ts[0]["id"] == "rolex-submariner-126610LN"
    assert "references" in ts[0]
```

- [ ] **Step 3: Lancer le test (échec attendu)**

Run: `cd /Users/famillethomas/Downloads/Projet/scrap-montres && python -m pytest tests/test_targets.py -v`
Expected: FAIL

- [ ] **Step 4: Écrire `backend/targets.py`**

```python
"""Chargement de la liste des montres ciblées (targets.json)."""
import json

from . import config


def load_targets(path=None) -> list[dict]:
    """Charge les cibles depuis targets.json. Renvoie [] si le fichier est absent."""
    path = path or config.TARGETS_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    return data.get("targets", [])
```

- [ ] **Step 5: Lancer le test (succès attendu)**

Run: `cd /Users/famillethomas/Downloads/Projet/scrap-montres && python -m pytest tests/test_targets.py -v`
Expected: PASS

- [ ] **Step 6: Checkpoint**

---

### Task 6: `connectors/base.py` (normaliseur de fiche + classe de base)

**Files:**
- Create: `backend/connectors/__init__.py` (vide)
- Create: `backend/connectors/base.py`
- Create: `backend/http_client.py`
- Test: `tests/test_base_connector.py`

**Interfaces:**
- Consumes: `config.USER_AGENT`, `config.TIMEOUT`, `config.REQUEST_DELAY`, `config.MAX_RETRIES`.
- Produces:
  - `http_client.get_text(url, **kw) -> str`, `http_client.get_json(url, **kw) -> dict`.
  - `base.strip_html(html: str) -> str`.
  - `base.watch(*, boutique, reference, url, marque="", modele="", prix_ttc=None, prix_ht=None, etat="", annee="", date_ajout_site="", description="", images=None, raw=None) -> dict` — fiche normalisée. Construit aussi `uid = f"{boutique}:{normalize_ref(reference)}:{url}"`.
  - `base.BaseConnector` avec `boutique: str`, `__init__(self, entry: dict)`, `seen_uids: set[str]`, `collect(self, mode: str) -> list[dict]` (lève `NotImplementedError`).

- [ ] **Step 1: Écrire `backend/http_client.py`** (copie adaptée du projet alternance)

```python
"""Client HTTP partagé : session unique, en-têtes réalistes, retries, délai poli."""
import time
import requests

from .config import USER_AGENT, TIMEOUT, REQUEST_DELAY, MAX_RETRIES

_session = None


def session() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        s.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8,fr;q=0.7",
        })
        _session = s
    return _session


def _request(method: str, url: str, **kwargs):
    kwargs.setdefault("timeout", TIMEOUT)
    last_exc = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = session().request(method, url, **kwargs)
            time.sleep(REQUEST_DELAY)
            return resp
        except requests.RequestException as exc:
            last_exc = exc
            time.sleep(REQUEST_DELAY * (attempt + 1))
    raise last_exc


def get_text(url: str, **kwargs) -> str:
    resp = _request("GET", url, **kwargs)
    resp.raise_for_status()
    return resp.text


def get_json(url: str, **kwargs) -> dict:
    resp = _request("GET", url, **kwargs)
    resp.raise_for_status()
    return resp.json()
```

- [ ] **Step 2: Écrire le test qui échoue**

```python
# tests/test_base_connector.py
from backend.connectors import base

def test_watch_normalise_les_champs_et_construit_uid():
    w = base.watch(
        boutique="Jackroad", reference="Ref. 126610LN",
        url="https://x.jp/item/1", prix_ttc=1100000,
    )
    assert w["boutique"] == "Jackroad"
    assert w["prix_ttc"] == 1100000
    assert w["uid"] == "Jackroad:126610LN:https://x.jp/item/1"
    assert w["images"] == []

def test_strip_html():
    assert base.strip_html("<p>Bon&nbsp;état</p>") == "Bon état"

def test_base_connector_collect_non_implemente():
    import pytest
    c = base.BaseConnector({"boutique": "X"})
    with pytest.raises(NotImplementedError):
        c.collect("full")
```

- [ ] **Step 3: Lancer le test (échec attendu)**

Run: `cd /Users/famillethomas/Downloads/Projet/scrap-montres && python -m pytest tests/test_base_connector.py -v`
Expected: FAIL

- [ ] **Step 4: Écrire `backend/connectors/base.py`**

```python
"""Classe de base des connecteurs boutiques + normaliseur de fiche montre."""
import re
from html import unescape

from ..matching import normalize_ref

_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(html: str) -> str:
    """Convertit un fragment HTML en texte brut."""
    if not html:
        return ""
    text = _TAG_RE.sub(" ", html)
    text = unescape(text).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def watch(*, boutique, reference, url, marque="", modele="", prix_ttc=None,
          prix_ht=None, etat="", annee="", date_ajout_site="", description="",
          images=None, raw=None) -> dict:
    """Construit une fiche montre normalisée (schéma commun à tous les connecteurs)."""
    return {
        "uid": f"{boutique}:{normalize_ref(reference)}:{url}",
        "boutique": boutique,
        "reference": (reference or "").strip(),
        "marque": marque or "",
        "modele": modele or "",
        "prix_ttc": prix_ttc,
        "prix_ht": prix_ht,
        "etat": etat or "",
        "annee": str(annee or ""),
        "date_ajout_site": date_ajout_site or "",
        "description": description or "",
        "url": url or "",
        "images": images or [],
        "raw": raw or {},
    }


class BaseConnector:
    """Un connecteur reçoit une entrée de registre et expose collect(mode)."""
    boutique = "base"

    def __init__(self, entry: dict):
        self.entry = entry
        self.boutique = entry.get("boutique", self.boutique)
        self.base_url = entry.get("base_url", "")
        self.seen_uids: set[str] = set()  # injecté par le pipeline (incrémental)

    def collect(self, mode: str) -> list[dict]:
        """mode ∈ {'full','incremental'} → liste de fiches via base.watch()."""
        raise NotImplementedError
```

- [ ] **Step 5: Lancer le test (succès attendu)**

Run: `cd /Users/famillethomas/Downloads/Projet/scrap-montres && python -m pytest tests/test_base_connector.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Checkpoint**

---

### Task 7: `db.py` (schéma watches + favorites + upsert)

**Files:**
- Create: `backend/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: `config.DB_PATH`, `config.DATA_DIR`.
- Produces:
  - `db.connect() -> sqlite3.Connection`, `db.init_db(conn)`, `db.now_iso() -> str`.
  - `db.upsert_watch(conn, w: dict) -> bool` (True si nouvelle). Persiste les colonnes de prix calculées si présentes dans `w` : `prix_detaxe_jpy, prix_detaxe_eur, benef_min, benef_max, target_id`.
  - `db.get_watches(conn, only_targets=False, limit=500) -> list[Row]`.
  - `db.toggle_favorite(conn, uid) -> bool` (True si désormais favori), `db.get_favorites(conn) -> list[Row]`, `db.is_favorite(conn, uid) -> bool`.
  - `db.load_seen_uids(conn) -> set[str]`, `db.record_seen(conn, uids)`.

- [ ] **Step 1: Écrire le test qui échoue**

```python
# tests/test_db.py
import sqlite3
from backend import db, config

def make_conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    conn = db.connect()
    db.init_db(conn)
    return conn

W = {
    "uid": "Jackroad:126610LN:https://x.jp/1", "boutique": "Jackroad",
    "reference": "126610LN", "marque": "Rolex", "modele": "Submariner",
    "prix_ttc": 1100000, "prix_ht": None, "etat": "très bon", "annee": "2018",
    "date_ajout_site": "2026-06-20", "description": "", "url": "https://x.jp/1",
    "images": ["a.jpg"], "raw": {}, "prix_detaxe_jpy": 1000000.0,
    "prix_detaxe_eur": 6000.0, "benef_min": 3500.0, "benef_max": 5000.0,
    "target_id": "rolex-submariner-126610LN",
}

def test_upsert_nouvelle_puis_existante(tmp_path, monkeypatch):
    conn = make_conn(tmp_path, monkeypatch)
    assert db.upsert_watch(conn, W) is True
    assert db.upsert_watch(conn, W) is False
    assert len(db.get_watches(conn)) == 1

def test_get_watches_only_targets(tmp_path, monkeypatch):
    conn = make_conn(tmp_path, monkeypatch)
    db.upsert_watch(conn, W)
    db.upsert_watch(conn, {**W, "uid": "B:X:u2", "url": "u2", "reference": "X",
                           "target_id": None, "benef_min": None})
    assert len(db.get_watches(conn, only_targets=True)) == 1

def test_favorites_toggle(tmp_path, monkeypatch):
    conn = make_conn(tmp_path, monkeypatch)
    db.upsert_watch(conn, W)
    assert db.toggle_favorite(conn, W["uid"]) is True
    assert db.is_favorite(conn, W["uid"]) is True
    assert len(db.get_favorites(conn)) == 1
    assert db.toggle_favorite(conn, W["uid"]) is False
    assert db.get_favorites(conn) == []
```

- [ ] **Step 2: Lancer le test (échec attendu)**

Run: `cd /Users/famillethomas/Downloads/Projet/scrap-montres && python -m pytest tests/test_db.py -v`
Expected: FAIL

- [ ] **Step 3: Écrire `backend/db.py`**

```python
"""Couche SQLite : schéma watches + favorites, upsert, requêtes."""
import json
import sqlite3
from datetime import datetime, timezone

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS watches (
    uid             TEXT PRIMARY KEY,   -- {boutique}:{ref_norm}:{url}
    boutique        TEXT NOT NULL,
    reference       TEXT,
    marque          TEXT,
    modele          TEXT,
    prix_ttc        REAL,
    prix_ht         REAL,
    prix_detaxe_jpy REAL,
    prix_detaxe_eur REAL,
    benef_min       REAL,
    benef_max       REAL,
    target_id       TEXT,               -- id de la cible matchée (ou NULL)
    etat            TEXT,
    annee           TEXT,
    date_ajout_site TEXT,
    description     TEXT,
    url             TEXT,
    images          TEXT,               -- JSON
    status          TEXT DEFAULT 'dispo',   -- dispo | vendue
    first_seen      TEXT,
    last_seen       TEXT,
    raw             TEXT
);

CREATE TABLE IF NOT EXISTS favorites (
    uid       TEXT PRIMARY KEY,
    added_at  TEXT
);

CREATE TABLE IF NOT EXISTS seen (
    uid       TEXT PRIMARY KEY,
    last_seen TEXT
);

CREATE INDEX IF NOT EXISTS idx_watches_target ON watches(target_id);
CREATE INDEX IF NOT EXISTS idx_watches_boutique ON watches(boutique);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection):
    conn.executescript(SCHEMA)
    conn.commit()


def upsert_watch(conn, w: dict) -> bool:
    """Insère une montre ou met à jour last_seen/prix si elle existe. True si nouvelle."""
    ts = now_iso()
    exists = conn.execute("SELECT 1 FROM watches WHERE uid = ?", (w["uid"],)).fetchone()
    if exists:
        conn.execute(
            """UPDATE watches SET last_seen=?, prix_ttc=?, prix_ht=?,
               prix_detaxe_jpy=?, prix_detaxe_eur=?, benef_min=?, benef_max=?,
               target_id=?, status='dispo' WHERE uid=?""",
            (ts, w.get("prix_ttc"), w.get("prix_ht"), w.get("prix_detaxe_jpy"),
             w.get("prix_detaxe_eur"), w.get("benef_min"), w.get("benef_max"),
             w.get("target_id"), w["uid"]),
        )
        conn.commit()
        return False
    conn.execute(
        """INSERT INTO watches
           (uid, boutique, reference, marque, modele, prix_ttc, prix_ht,
            prix_detaxe_jpy, prix_detaxe_eur, benef_min, benef_max, target_id,
            etat, annee, date_ajout_site, description, url, images, status,
            first_seen, last_seen, raw)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (w["uid"], w["boutique"], w.get("reference"), w.get("marque"),
         w.get("modele"), w.get("prix_ttc"), w.get("prix_ht"),
         w.get("prix_detaxe_jpy"), w.get("prix_detaxe_eur"), w.get("benef_min"),
         w.get("benef_max"), w.get("target_id"), w.get("etat"), w.get("annee"),
         w.get("date_ajout_site"), w.get("description"), w.get("url"),
         json.dumps(w.get("images", []), ensure_ascii=False), "dispo", ts, ts,
         json.dumps(w.get("raw", {}), ensure_ascii=False)),
    )
    conn.commit()
    return True


def get_watches(conn, only_targets=False, limit=500):
    q = "SELECT * FROM watches"
    if only_targets:
        q += " WHERE target_id IS NOT NULL"
    q += " ORDER BY (benef_max IS NULL), benef_max DESC, first_seen DESC LIMIT ?"
    return conn.execute(q, (limit,)).fetchall()


def is_favorite(conn, uid) -> bool:
    return conn.execute("SELECT 1 FROM favorites WHERE uid=?", (uid,)).fetchone() is not None


def toggle_favorite(conn, uid) -> bool:
    """Bascule l'état favori. Renvoie True si désormais favori, False sinon."""
    if is_favorite(conn, uid):
        conn.execute("DELETE FROM favorites WHERE uid=?", (uid,))
        conn.commit()
        return False
    conn.execute("INSERT INTO favorites (uid, added_at) VALUES (?, ?)", (uid, now_iso()))
    conn.commit()
    return True


def get_favorites(conn):
    return conn.execute(
        """SELECT w.* FROM favorites f JOIN watches w ON w.uid = f.uid
           ORDER BY f.added_at DESC""").fetchall()


def load_seen_uids(conn) -> set:
    return {r["uid"] for r in conn.execute("SELECT uid FROM seen")}


def record_seen(conn, uids):
    ts = now_iso()
    conn.executemany(
        "INSERT INTO seen (uid, last_seen) VALUES (?, ?) "
        "ON CONFLICT(uid) DO UPDATE SET last_seen=excluded.last_seen",
        [(u, ts) for u in uids])
    conn.commit()
```

- [ ] **Step 4: Lancer le test (succès attendu)**

Run: `cd /Users/famillethomas/Downloads/Projet/scrap-montres && python -m pytest tests/test_db.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Checkpoint**

---

### Task 8: `pipeline.py` (orchestration full / incremental + enrichissement prix)

**Files:**
- Create: `backend/connectors/registry.py` (registre des boutiques + mapping connecteurs)
- Create: `backend/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `db`, `targets.load_targets`, `matching.match_target`, `pricing.compute_benef`, `fx.get_rate`, `base.watch`, `BaseConnector`.
- Produces:
  - `registry.BOUTIQUES: list[dict]` (chaque dict : `boutique, base_url, connector`), `registry.CONNECTORS: dict[str, type]`.
  - `pipeline.enrich(w: dict, targets: list, rate: float) -> dict` — ajoute `target_id` + champs de prix à une fiche.
  - `pipeline.run(mode: str = "incremental") -> dict` — collecte toutes les boutiques, enrichit, upsert, renvoie `{"fetched", "new"}`.

- [ ] **Step 1: Écrire `backend/connectors/registry.py`** (vide au départ, rempli quand les sites arrivent)

```python
"""Registre des boutiques et mapping type-de-connecteur. À compléter par site."""
# Chaque connecteur concret s'enregistre ici une fois écrit, ex :
# from .jackroad import JackroadConnector
# CONNECTORS = {"jackroad": JackroadConnector}
# BOUTIQUES = [{"boutique": "Jackroad", "base_url": "https://...", "connector": "jackroad"}]

CONNECTORS: dict = {}
BOUTIQUES: list = []
```

- [ ] **Step 2: Écrire le test qui échoue** (teste l'enrichissement, indépendant des sites)

```python
# tests/test_pipeline.py
from backend import pipeline

TARGETS = [{
    "id": "sub-126610LN", "references": ["126610LN"],
    "revente_fr_min": 9500, "revente_fr_max": 11000, "couts_optionnels_eur": 0,
}]

def test_enrich_montre_ciblee():
    w = {"reference": "Ref 126610LN", "prix_ttc": 1100000, "prix_ht": None}
    out = pipeline.enrich(dict(w), TARGETS, rate=0.006)
    assert out["target_id"] == "sub-126610LN"
    assert out["prix_detaxe_eur"] == 6000.0
    assert out["benef_min"] == 3500.0

def test_enrich_montre_hors_cible():
    w = {"reference": "Seiko SKX007", "prix_ttc": 50000, "prix_ht": None}
    out = pipeline.enrich(dict(w), TARGETS, rate=0.006)
    assert out["target_id"] is None
    assert out["benef_min"] is None
```

- [ ] **Step 3: Lancer le test (échec attendu)**

Run: `cd /Users/famillethomas/Downloads/Projet/scrap-montres && python -m pytest tests/test_pipeline.py -v`
Expected: FAIL

- [ ] **Step 4: Écrire `backend/pipeline.py`**

```python
"""Orchestration : pour chaque boutique → collect → enrichissement prix → SQLite."""
from . import db, fx, pricing
from .matching import match_target
from .targets import load_targets
from .connectors import registry


def enrich(w: dict, targets: list, rate: float) -> dict:
    """Ajoute target_id + prix détaxé + bénéfice à une fiche montre."""
    target = match_target(w.get("reference", ""), targets)
    if target is None:
        w.update({"target_id": None, "prix_detaxe_jpy": None,
                  "prix_detaxe_eur": None, "benef_min": None, "benef_max": None})
        # on calcule quand même le détaxé pour l'affichage du stock
        w["prix_detaxe_jpy"] = pricing.prix_detaxe_jpy(w.get("prix_ttc"), w.get("prix_ht"))
        if w["prix_detaxe_jpy"] is not None:
            w["prix_detaxe_eur"] = fx.jpy_to_eur(w["prix_detaxe_jpy"], rate=rate)
        return w
    calc = pricing.compute_benef(
        w.get("prix_ttc"), w.get("prix_ht"),
        target["revente_fr_min"], target["revente_fr_max"],
        rate=rate, couts_opt=target.get("couts_optionnels_eur", 0) or 0)
    w["target_id"] = target["id"]
    w.update(calc)
    return w


def run(mode: str = "incremental") -> dict:
    """Collecte toutes les boutiques du registre, enrichit, upsert en base."""
    targets = load_targets()
    rate = fx.get_rate()
    conn = db.connect()
    db.init_db(conn)
    seen = db.load_seen_uids(conn)

    fetched = new = 0
    for entry in registry.BOUTIQUES:
        cls = registry.CONNECTORS[entry["connector"]]
        connector = cls(entry)
        connector.seen_uids = seen
        for w in connector.collect(mode):
            fetched += 1
            w = enrich(w, targets, rate)
            if db.upsert_watch(conn, w):
                new += 1
            db.record_seen(conn, [w["uid"]])
    return {"fetched": fetched, "new": new}
```

- [ ] **Step 5: Lancer le test (succès attendu)**

Run: `cd /Users/famillethomas/Downloads/Projet/scrap-montres && python -m pytest tests/test_pipeline.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Checkpoint**

---

### Task 9: `api.py` (FastAPI : stock, cibles, favoris, collecte)

**Files:**
- Create: `backend/api.py`
- Create: `backend/run.py` (script CLI de collecte)
- Create: `scripts/collecte.sh`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `db`, `pipeline.run`.
- Produces (endpoints) :
  - `GET /api/stock` → liste des montres (toutes).
  - `GET /api/cibles` → montres avec `target_id` non nul, triées par bénéfice.
  - `GET /api/favoris` → favoris.
  - `POST /api/favoris/{uid}` → bascule favori, renvoie `{"favorite": bool}`.
  - `POST /api/collecte?mode=incremental` → lance `pipeline.run`, renvoie `{"fetched","new"}`.
  - Sert le front buildé (`frontend/dist`) si présent.
- Produces (CLI) : `run.py` lance `pipeline.run(mode)` depuis `sys.argv` (`--full`/`--incremental`).

- [ ] **Step 1: Écrire le test qui échoue**

```python
# tests/test_api.py
from fastapi.testclient import TestClient
from backend import api, config, db

def test_endpoints_de_base(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    conn = db.connect(); db.init_db(conn)
    db.upsert_watch(conn, {"uid": "B:R:u", "boutique": "B", "reference": "R",
                           "url": "u", "target_id": "t1", "benef_max": 100})
    client = TestClient(api.app)
    assert client.get("/api/stock").status_code == 200
    assert len(client.get("/api/cibles").json()) == 1
    r = client.post("/api/favoris/B:R:u").json()
    assert r["favorite"] is True
    assert len(client.get("/api/favoris").json()) == 1
```

- [ ] **Step 2: Lancer le test (échec attendu)**

Run: `cd /Users/famillethomas/Downloads/Projet/scrap-montres && python -m pytest tests/test_api.py -v`
Expected: FAIL

- [ ] **Step 3: Écrire `backend/api.py`**

```python
"""API REST au-dessus de SQLite, sert aussi le front React buildé.

Lancer :  uvicorn backend.api:app --port 8000
"""
import json

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import db, pipeline
from .config import BASE_DIR

app = FastAPI(title="Scraper Montres JP")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])


def _rows(rows):
    out = []
    for r in rows:
        d = dict(r)
        if d.get("images"):
            try:
                d["images"] = json.loads(d["images"])
            except (TypeError, ValueError):
                d["images"] = []
        out.append(d)
    return out


@app.get("/api/stock")
def stock():
    conn = db.connect(); db.init_db(conn)
    return _rows(db.get_watches(conn))


@app.get("/api/cibles")
def cibles():
    conn = db.connect(); db.init_db(conn)
    return _rows(db.get_watches(conn, only_targets=True))


@app.get("/api/favoris")
def favoris():
    conn = db.connect(); db.init_db(conn)
    return _rows(db.get_favorites(conn))


@app.post("/api/favoris/{uid:path}")
def toggle_favori(uid: str):
    conn = db.connect(); db.init_db(conn)
    return {"favorite": db.toggle_favorite(conn, uid)}


@app.post("/api/collecte")
def collecte(mode: str = "incremental"):
    return pipeline.run(mode)


# Front buildé (optionnel : présent après `npm run build`)
_dist = BASE_DIR / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="front")
```

- [ ] **Step 4: Écrire `backend/run.py`**

```python
"""Collecte en ligne de commande : python -m backend.run [--full|--incremental]"""
import sys

from . import pipeline


def main():
    mode = "full" if "--full" in sys.argv else "incremental"
    res = pipeline.run(mode)
    print(f"Collecte {mode} terminée : {res['fetched']} fiches, {res['new']} nouvelles.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Écrire `scripts/collecte.sh`**

```bash
#!/usr/bin/env bash
# Lance une collecte. Usage : ./scripts/collecte.sh [--full|--incremental]
set -e
cd "$(dirname "$0")/.."
python -m backend.run "${1:---incremental}"
```

- [ ] **Step 6: Lancer le test (succès attendu)**

Run: `cd /Users/famillethomas/Downloads/Projet/scrap-montres && python -m pytest tests/test_api.py -v && chmod +x scripts/collecte.sh`
Expected: PASS

- [ ] **Step 7: Checkpoint**

---

### Task 10: Frontend React/Vite (3 pages : Stock, Cibles, Favoris)

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.js`
- Create: `frontend/index.html`
- Create: `frontend/src/main.jsx`
- Create: `frontend/src/App.jsx`

**Interfaces:**
- Consumes (API) : `/api/stock`, `/api/cibles`, `/api/favoris`, `POST /api/favoris/{uid}`, `POST /api/collecte`.

- [ ] **Step 1: Créer `frontend/package.json`**

```json
{
  "name": "montres-jp-front",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": { "dev": "vite", "build": "vite build", "preview": "vite preview" },
  "dependencies": { "react": "^18.3.1", "react-dom": "^18.3.1" },
  "devDependencies": { "@vitejs/plugin-react": "^4.3.4", "vite": "^6.0.0" }
}
```

- [ ] **Step 2: Créer `frontend/vite.config.js`**

```js
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': 'http://localhost:8000' } },
})
```

- [ ] **Step 3: Créer `frontend/index.html`**

```html
<!doctype html>
<html lang="fr">
  <head><meta charset="UTF-8" /><title>Montres JP — Arbitrage</title></head>
  <body><div id="root"></div><script type="module" src="/src/main.jsx"></script></body>
</html>
```

- [ ] **Step 4: Créer `frontend/src/main.jsx`**

```jsx
import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.jsx'

createRoot(document.getElementById('root')).render(<App />)
```

- [ ] **Step 5: Créer `frontend/src/App.jsx`**

```jsx
import React, { useEffect, useState } from 'react'

const PAGES = { stock: 'Stock', cibles: 'Cibles', favoris: 'Favoris' }
const eur = (v) => v == null ? '—' : v.toLocaleString('fr-FR') + ' €'

function Row({ w, onFav }) {
  return (
    <tr>
      <td><button onClick={() => onFav(w.uid)}>★</button></td>
      <td>{w.boutique}</td>
      <td>{w.marque} {w.modele}</td>
      <td>{w.reference}</td>
      <td>{w.etat}</td>
      <td>{eur(w.prix_detaxe_eur)}</td>
      <td>{w.benef_min != null ? `${eur(w.benef_min)} → ${eur(w.benef_max)}` : '—'}</td>
      <td><a href={w.url} target="_blank" rel="noreferrer">voir</a></td>
    </tr>
  )
}

export default function App() {
  const [page, setPage] = useState('cibles')
  const [rows, setRows] = useState([])
  const [busy, setBusy] = useState(false)

  const load = (p) => fetch(`/api/${p}`).then(r => r.json()).then(setRows)
  useEffect(() => { load(page) }, [page])

  const fav = (uid) => fetch(`/api/favoris/${encodeURIComponent(uid)}`,
    { method: 'POST' }).then(() => load(page))
  const collecte = () => {
    setBusy(true)
    fetch('/api/collecte?mode=incremental', { method: 'POST' })
      .then(r => r.json()).then(() => load(page)).finally(() => setBusy(false))
  }

  return (
    <div style={{ fontFamily: 'system-ui', padding: 20 }}>
      <h1>Montres JP — Arbitrage</h1>
      <nav style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        {Object.entries(PAGES).map(([k, label]) => (
          <button key={k} onClick={() => setPage(k)}
            style={{ fontWeight: page === k ? 700 : 400 }}>{label}</button>
        ))}
        <button onClick={collecte} disabled={busy} style={{ marginLeft: 'auto' }}>
          {busy ? 'Collecte…' : 'Lancer une collecte'}
        </button>
      </nav>
      <table border="1" cellPadding="6" style={{ borderCollapse: 'collapse', width: '100%' }}>
        <thead><tr>
          <th>★</th><th>Boutique</th><th>Montre</th><th>Réf</th><th>État</th>
          <th>Prix détaxé</th><th>Bénéfice</th><th>Lien</th>
        </tr></thead>
        <tbody>{rows.map(w => <Row key={w.uid} w={w} onFav={fav} />)}</tbody>
      </table>
      {rows.length === 0 && <p>Aucune montre — lance une collecte.</p>}
    </div>
  )
}
```

- [ ] **Step 6: Installer et builder pour vérifier**

Run: `cd /Users/famillethomas/Downloads/Projet/scrap-montres/frontend && npm install && npm run build`
Expected: build réussi, dossier `dist/` créé

- [ ] **Step 7: Checkpoint**

---

### Task 11: Connecteur exemple (template) + README de connecteur

**Files:**
- Create: `backend/connectors/_template.py`
- Create: `backend/connectors/README.md`

**Interfaces:**
- Produces: `_template.TemplateConnector(BaseConnector)` — squelette commenté montrant comment écrire un connecteur (pagination full vs incrémental, parsing BeautifulSoup, arrêt sur déjà-vu, fallback Playwright). Sert de modèle quand l'utilisateur enverra les vraies boutiques.

- [ ] **Step 1: Écrire `backend/connectors/_template.py`**

```python
"""Template de connecteur boutique. Copier ce fichier, l'adapter au site, puis
l'enregistrer dans registry.py. NE PAS appeler directement (URLs fictives)."""
from bs4 import BeautifulSoup

from .. import http_client
from ..config import MAX_ITEMS_INCREMENTAL
from .base import BaseConnector, watch, strip_html


class TemplateConnector(BaseConnector):
    boutique = "Template"

    def _parse_liste(self, html: str) -> list[str]:
        """Renvoie les URLs des fiches montres d'une page de listing."""
        soup = BeautifulSoup(html, "html.parser")
        return [a["href"] for a in soup.select("a.product-link")]  # À ADAPTER

    def _parse_fiche(self, url: str, html: str) -> dict:
        """Parse une fiche produit → base.watch(). Sélecteurs À ADAPTER au site."""
        soup = BeautifulSoup(html, "html.parser")
        def txt(sel):
            el = soup.select_one(sel)
            return el.get_text(strip=True) if el else ""
        prix_ttc = txt(".price-tax-included").replace("¥", "").replace(",", "")
        return watch(
            boutique=self.boutique,
            reference=txt(".reference"),
            url=url,
            marque=txt(".brand"),
            modele=txt(".model"),
            prix_ttc=float(prix_ttc) if prix_ttc.isdigit() else None,
            etat=txt(".condition"),
            annee=txt(".year"),
            date_ajout_site=txt(".date-added"),
            description=strip_html(txt(".description")),
            images=[img["src"] for img in soup.select(".gallery img")],
        )

    def collect(self, mode: str) -> list[dict]:
        results, page = [], 1
        while True:
            html = http_client.get_text(f"{self.base_url}/list?page={page}")
            urls = self._parse_liste(html)
            if not urls:
                break
            for url in urls:
                w = self._parse_fiche(url, http_client.get_text(url))
                # incrémental : on s'arrête dès qu'on retombe sur du déjà-vu
                if mode == "incremental" and w["uid"] in self.seen_uids:
                    return results
                results.append(w)
                if mode == "incremental" and len(results) >= MAX_ITEMS_INCREMENTAL:
                    return results
            page += 1
        return results
```

- [ ] **Step 2: Écrire `backend/connectors/README.md`**

```markdown
# Écrire un connecteur boutique

1. Copier `_template.py` → `<boutique>.py`, renommer la classe.
2. Adapter `_parse_liste` (URLs des fiches) et `_parse_fiche` (sélecteurs CSS).
3. Mapper les prix : récupérer le **TTC (税込)** ; passer le **HT (税抜)** dans
   `prix_ht` si le site l'affiche (sinon `pricing` divisera le TTC par 1.10).
4. Enregistrer dans `registry.py` : ajouter à `CONNECTORS` et `BOUTIQUES`.
5. Site 100% JavaScript ? Remplacer `http_client.get_text` par un rendu
   Playwright headless (à ajouter dans `http_client` au besoin).
6. Tester : `python -m backend.run --full` puis vérifier dans l'API.
```

- [ ] **Step 3: Checkpoint**

---

## Self-Review

- **Spec coverage :** stock complet → Task 7/8 ; nouveautés incrémentales → Task 8 + template Task 11 ; détaxe 10% → Task 3 ; conversion JPY/EUR → Task 2 ; matching réf → Task 4 ; targets.json → Task 5 ; 3 pages (Stock/Cibles/Favoris) → Task 9/10 ; favoris persistants → Task 7/9/10 ; scraping HTML + Playwright fallback → Task 6/11. ✅
- **Connecteurs réels :** volontairement hors-plan tant que l'utilisateur n'a pas envoyé les sites. Task 11 fournit le template ; chaque site = une nouvelle tâche « copier le template + adapter sélecteurs + enregistrer ».
- **Types cohérents :** `base.watch()` produit les clés consommées par `pipeline.enrich` et `db.upsert_watch` ; `compute_benef` renvoie exactement les clés stockées en base. ✅

## Reste à fournir par l'utilisateur

- La **liste des boutiques** (URLs) → 1 connecteur par site (copie du template).
- Les **références de montres** ciblées → à ajouter dans `targets.json` avec fourchette de revente FR.
