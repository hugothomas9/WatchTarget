"""API REST au-dessus de SQLite, sert aussi le front React buildé.

Lancer :  uvicorn backend.api:app --port 8765
"""
import json
import threading
from contextlib import contextmanager

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import db, pipeline
from . import auth_telegram as auth
from .config import BASE_DIR

_COOKIE = "wt_session"


def _current_uid(request: Request):
    """id Telegram de la session (cookie signé), ou None si non connecté."""
    return auth.lire_session(request.cookies.get(_COOKIE))

app = FastAPI(title="Scraper Montres JP")
# Restreint au front de dev vite ; en prod le front est servi par la même origine.
app.add_middleware(CORSMiddleware,
                   allow_origins=["http://localhost:5173"],
                   allow_methods=["*"], allow_headers=["*"])

# Une seule collecte à la fois (un double-clic ou une collecte CLI simultanée
# provoquerait deux écritures concurrentes dans SQLite).
_collect_lock = threading.Lock()


@app.on_event("startup")
def _startup():
    conn = db.connect()
    db.init_db(conn)
    conn.close()


@contextmanager
def _conn():
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


def _rows(rows):
    from .etat import traduire_etat
    from .noms import traduire_nom
    out = []
    for r in rows:
        d = dict(r)
        if d.get("images"):
            try:
                d["images"] = json.loads(d["images"])
            except (TypeError, ValueError):
                d["images"] = []
        try:
            d["raw_accessoires"] = (json.loads(d.get("raw") or "{}")
                                    .get("accessoires", ""))
        except (TypeError, ValueError):
            d["raw_accessoires"] = ""
        # état traduit en FR pour l'affichage ; on garde l'original en info-bulle
        d["etat_original"] = d.get("etat") or ""
        d["etat"] = traduire_etat(d.get("etat"))
        # nom de montre : termes japonais → latin (original en info-bulle)
        d["modele_original"] = d.get("modele") or ""
        d["modele"] = traduire_nom(d.get("modele"))
        d.pop("raw", None)
        out.append(d)
    return out


@app.get("/api/stock")
def stock(marque: str = "", famille: str = "", sort: str = "date",
          dispo: int = 0):
    with _conn() as conn:
        return _rows(db.get_watches(conn, marque=marque or None,
                                    famille=famille or None, sort=sort,
                                    only_dispo=bool(dispo)))


@app.post("/api/auth/telegram")
def auth_telegram(payload: dict, response: Response):
    """Login Widget Telegram : vérifie la signature, crée/maj l'utilisateur, pose un
    cookie de session signé. `payload` = les champs renvoyés par le widget."""
    u = auth.verifier_widget(payload)
    if not u:
        raise HTTPException(401, "signature Telegram invalide")
    with _conn() as conn:
        db.upsert_user(conn, u["telegram_id"], u["first_name"], u["username"])
    response.set_cookie(_COOKIE, auth.creer_session(u["telegram_id"]),
                        httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30)
    return u


@app.get("/api/me")
def me(request: Request):
    """Utilisateur connecté (ou null)."""
    uid = _current_uid(request)
    if uid is None:
        return {"user": None}
    with _conn() as conn:
        row = db.get_user(conn, uid)
    return {"user": dict(row) if row else {"telegram_id": uid}}


@app.post("/api/logout")
def logout(response: Response):
    response.delete_cookie(_COOKIE)
    return {"ok": True}


# Portée des alertes : connecté → SES alertes ; sinon → toutes (usage admin/local).
def _scope(request: Request):
    uid = _current_uid(request)
    return uid if uid is not None else "__all__"


@app.get("/api/cibles")
def cibles(request: Request):
    """Montres dispo qui matchent les alertes (de l'utilisateur connecté, ou toutes
    en local), enrichies (prix vendu EW + marge) comme les opportunités."""
    with _conn() as conn:
        return _rows(db.get_cibles_matches(conn, telegram_id=_scope(request)))


@app.get("/api/alertes")
def alertes_list(request: Request):
    """Alertes de l'utilisateur connecté (ou toutes en local)."""
    with _conn() as conn:
        return [dict(r) for r in db.list_cibles(conn, telegram_id=_scope(request))]


@app.post("/api/alertes")
def alertes_add(payload: dict, request: Request):
    """Crée une alerte : {mots_cles, libelle?}. Rattachée à l'utilisateur connecté."""
    mots = (payload.get("mots_cles") or "").strip()
    if not mots:
        raise HTTPException(400, "mots_cles requis")
    with _conn() as conn:
        cid = db.add_cible(conn, mots, payload.get("libelle", ""),
                           telegram_id=_current_uid(request))
    return {"id": cid}


@app.delete("/api/alertes/{cible_id}")
def alertes_delete(cible_id: int, request: Request):
    """Supprime une alerte (seulement la sienne si connecté)."""
    with _conn() as conn:
        db.delete_cible(conn, cible_id, telegram_id=_scope(request))
    return {"ok": True}


@app.get("/api/familles")
def familles(marque: str = ""):
    if not marque:
        return []
    with _conn() as conn:
        return db.list_familles(conn, marque)


@app.get("/api/favoris")
def favoris(sort: str = "spread"):
    with _conn() as conn:
        return _rows(db.get_favorites(conn, sort=sort))


@app.get("/api/marques")
def marques():
    with _conn() as conn:
        return db.list_marques(conn)


@app.get("/api/opportunites")
def opportunites(spread_min: float = None, liq_min: int = None,
                 sort: str = "spread", marque: str = ""):
    from .config import SPREAD_MIN_EUR, LIQUIDITY_MIN_LISTINGS
    with _conn() as conn:
        rows = db.get_opportunities(
            conn,
            spread_min=spread_min if spread_min is not None else SPREAD_MIN_EUR,
            liq_min=liq_min if liq_min is not None else LIQUIDITY_MIN_LISTINGS,
            sort=sort, marque=marque or None)
        return _rows(rows)


def _analyze_favori_bg(uid: str):
    """Analyse EveryWatch (prix vendus + liquidité) d'un favori, en tâche de fond :
    le clic reste instantané, l'analyse tourne à part et se voit au refresh suivant."""
    from . import market_scan
    conn = db.connect()
    try:
        market_scan.analyze_one(conn, uid)
    except Exception:
        pass
    finally:
        conn.close()


@app.post("/api/favoris/{uid:path}")
def toggle_favori(uid: str):
    with _conn() as conn:
        now_fav = db.toggle_favorite(conn, uid)
    # dès qu'une montre est mise en favori, on lance son analyse (comme une
    # opportunité) : vérif dispo + pricing EveryWatch. Non bloquant pour l'UI.
    if now_fav:
        threading.Thread(target=_analyze_favori_bg, args=(uid,), daemon=True).start()
    return {"favorite": now_fav}


@app.post("/api/collecte")
def collecte(mode: str = "incremental"):
    if not _collect_lock.acquire(blocking=False):
        raise HTTPException(409, "Une collecte est déjà en cours.")
    try:
        return pipeline.run(mode)
    finally:
        _collect_lock.release()


# Front buildé (optionnel : présent après `npm run build`)
_dist = BASE_DIR / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="front")
