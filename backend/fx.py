"""Taux de change JPY -> EUR via API gratuite, avec cache disque journalier."""
import json
import os
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
    # écriture atomique : évite un cache corrompu si API et collecte écrivent en même temps
    tmp = config.JPY_EUR_CACHE.with_suffix(".tmp")
    tmp.write_text(json.dumps(
        {"rate": rate, "fetched_at": datetime.now(timezone.utc).isoformat()}
    ))
    os.replace(tmp, config.JPY_EUR_CACHE)


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


_PAIR_FALLBACK = {("USD", "EUR"): 0.86}
_pair_cache: dict = {}   # cache mémoire process (l'auto-pricing tourne en batch)


def get_pair(base: str, quote: str) -> float:
    """Taux base→quote via frankfurter (cache mémoire). Sert à convertir les
    prix Chrono24 exprimés en USD vers l'euro."""
    if base == quote:
        return 1.0
    key = (base, quote)
    if key in _pair_cache:
        return _pair_cache[key]
    try:
        resp = requests.get(
            f"https://api.frankfurter.app/latest?from={base}&to={quote}",
            timeout=config.TIMEOUT)
        resp.raise_for_status()
        rate = float(resp.json()["rates"][quote])
    except (requests.RequestException, KeyError, ValueError):
        rate = _PAIR_FALLBACK.get(key, 1.0)
    _pair_cache[key] = rate
    return rate
