"""Client HTTP partagé : sessions par thread, retries (réseau ET 429/5xx),
délai de politesse GLOBAL (pas par thread — sinon N workers = N× le débit)."""
import threading
import time

import requests

from .config import USER_AGENT, TIMEOUT, REQUEST_DELAY, MAX_RETRIES

_tls = threading.local()
# NB : les boutiques japonaises se scrapent en DIRECT (elles bloquent le proxy
# résidentiel : watchnian → 403). Le proxy est réservé au pricing Cloudflare
# (Chrono24 / WatchCharts), géré séparément dans market.py via curl_cffi.

# Limiteur global : au plus une requête toutes les REQUEST_DELAY secondes,
# tous threads confondus. La concurrence reste utile car les latences réseau
# se recouvrent, mais le débit vers les sites reste borné et poli.
_rate_lock = threading.Lock()
_last_request = [0.0]

_RETRY_STATUSES = {429, 500, 502, 503, 504}


def session() -> requests.Session:
    s = getattr(_tls, "session", None)
    if s is None:
        s = requests.Session()
        s.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8,fr;q=0.7",
        })
        _tls.session = s
    return s


def _throttle():
    with _rate_lock:
        wait = _last_request[0] + REQUEST_DELAY - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_request[0] = time.monotonic()


def _request(method: str, url: str, **kwargs):
    kwargs.setdefault("timeout", TIMEOUT)
    last_exc = None
    for attempt in range(MAX_RETRIES + 1):
        _throttle()
        try:
            resp = session().request(method, url, **kwargs)
        except requests.RequestException as exc:
            last_exc = exc
            time.sleep(REQUEST_DELAY * (attempt + 1))
            continue
        if resp.status_code in _RETRY_STATUSES and attempt < MAX_RETRIES:
            # 429/5xx : backoff progressif avant de retenter
            time.sleep(REQUEST_DELAY * 4 * (attempt + 1))
            continue
        return resp
    raise last_exc


def get_text(url: str, encoding: str | None = None, **kwargs) -> str:
    resp = _request("GET", url, **kwargs)
    resp.raise_for_status()
    if encoding:
        resp.encoding = encoding
    return resp.text


def get_json(url: str, **kwargs) -> dict:
    resp = _request("GET", url, **kwargs)
    resp.raise_for_status()
    return resp.json()
