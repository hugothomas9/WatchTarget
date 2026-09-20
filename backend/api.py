"""API REST au-dessus de SQLite, sert aussi le front React buildé.

Lancer :  uvicorn backend.api:app --port 8765
"""
import hmac
import json
import threading
from contextlib import contextmanager

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import config, db, pipeline
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
          dispo: int = 0, q: str = ""):
    with _conn() as conn:
        return _rows(db.get_watches(conn, marque=marque or None,
                                    famille=famille or None, sort=sort,
                                    only_dispo=bool(dispo), q=q or None))


@app.get("/api/modeles")
def modeles(marque: str = ""):
    """Modèles génériques (familles normalisées : Daytona, Seamaster…) présents
    en base — filtre INDÉPENDANT de la marque (filtrable par marque en option)."""
    with _conn() as conn:
        sql = "SELECT famille, COUNT(*) c FROM watches WHERE famille != ''"
        args = []
        if marque:
            sql += " AND marque LIKE ?"
            args.append(f"%{marque}%")
        sql += " GROUP BY famille ORDER BY famille"
        return [r[0] for r in conn.execute(sql, args)]


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
                        httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30,
                        secure=not config.LOCAL_ADMIN)   # HTTPS only en prod
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


# Portée des alertes : connecté → SES alertes ; sans session → droits admin
# UNIQUEMENT en mono-utilisateur local (le fallback anonyme=admin en prod était
# une faille : n'importe qui pouvait lister/supprimer les alertes de tous).
def _scope(request: Request):
    uid = _current_uid(request)
    if uid is not None:
        return uid
    return "__all__" if config.LOCAL_ADMIN else None


@app.get("/api/cibles")
def cibles(request: Request):
    """Montres dispo qui matchent les alertes (de l'utilisateur connecté, ou toutes
    en local), enrichies (prix vendu EW + marge) comme les opportunités."""
    scope = _scope(request)
    if scope is None:            # anonyme en prod : rien à voir
        return []
    with _conn() as conn:
        return _rows(db.get_cibles_matches(conn, telegram_id=scope))


@app.get("/api/alertes")
def alertes_list(request: Request):
    """Alertes de l'utilisateur connecté (ou toutes en local)."""
    scope = _scope(request)
    if scope is None:
        return []
    with _conn() as conn:
        return [dict(r) for r in db.list_cibles(conn, telegram_id=scope)]


@app.post("/api/alertes")
def alertes_add(payload: dict, request: Request):
    """Crée une alerte : {mots_cles, libelle?}. Rattachée à l'utilisateur connecté."""
    uid = _current_uid(request)
    if uid is None and not config.LOCAL_ADMIN:
        raise HTTPException(401, "connexion Telegram requise pour créer une alerte")
    mots = (payload.get("mots_cles") or "").strip()
    if not mots:
        raise HTTPException(400, "mots_cles requis")
    with _conn() as conn:
        cid = db.add_cible(conn, mots, payload.get("libelle", ""), telegram_id=uid)
    return {"id": cid}


@app.delete("/api/alertes/{cible_id}")
def alertes_delete(cible_id: int, request: Request):
    """Supprime une alerte (seulement la sienne si connecté)."""
    scope = _scope(request)
    if scope is None:
        raise HTTPException(401, "connexion Telegram requise")
    with _conn() as conn:
        supprimee = db.delete_cible(conn, cible_id, telegram_id=scope)
    if not supprimee:
        raise HTTPException(404, "alerte introuvable (ou pas la tienne)")
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


@app.get("/api/historique/{uid:path}")
def historique(uid: str):
    """Historique de prix d'une montre (un point par changement de prix)."""
    with _conn() as conn:
        return [dict(p) for p in db.get_price_history(conn, uid)]


@app.get("/api/marques")
def marques():
    with _conn() as conn:
        return db.list_marques(conn)


@app.get("/api/opportunites")
def opportunites(spread_min: float = None, liq_min: int = None,
                 sort: str = "spread", marque: str = "", famille: str = "",
                 prix_max: float = None, q: str = ""):
    from .config import SPREAD_MIN_EUR, LIQUIDITY_MIN_LISTINGS
    with _conn() as conn:
        rows = db.get_opportunities(
            conn,
            spread_min=spread_min if spread_min is not None else SPREAD_MIN_EUR,
            liq_min=liq_min if liq_min is not None else LIQUIDITY_MIN_LISTINGS,
            sort=sort, marque=marque or None, famille=famille or None,
            prix_max=prix_max, q=q or None)
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
def toggle_favori(uid: str, request: Request):
    # En prod, le toggle lance du scraping (analyse dispo + EveryWatch) : réservé
    # aux connectés, sinon un anonyme peut marteler l'endpoint comme une collecte.
    if not config.LOCAL_ADMIN and _current_uid(request) is None:
        raise HTTPException(401, "connexion Telegram requise")
    with _conn() as conn:
        now_fav = db.toggle_favorite(conn, uid)
    # dès qu'une montre est mise en favori, on lance son analyse (comme une
    # opportunité) : vérif dispo + pricing EveryWatch. Non bloquant pour l'UI.
    if now_fav:
        threading.Thread(target=_analyze_favori_bg, args=(uid,), daemon=True).start()
    return {"favorite": now_fav}


@app.post("/api/collecte")
def collecte(request: Request, mode: str = "incremental"):
    # En prod, déclencher un scrape complet est réservé à l'ADMIN (le chat_id
    # configuré) : sinon n'importe quel visiteur brûle proxy + quota des boutiques.
    if not config.LOCAL_ADMIN:
        uid = _current_uid(request)
        if uid is None:
            raise HTTPException(401, "authentification requise")
        if str(uid) != str(config.TELEGRAM_CHAT_ID or ""):
            raise HTTPException(403, "réservé à l'administrateur")
    if not _collect_lock.acquire(blocking=False):
        raise HTTPException(409, "Une collecte est déjà en cours.")
    try:
        return pipeline.run(mode)
    finally:
        _collect_lock.release()


@app.post("/api/telegram/webhook")
def telegram_webhook(update: dict, request: Request):
    """Bot Telegram en mode WEBHOOK : Telegram POSTe ici chaque update.

    Alternative au long polling (`python -m backend.bot`), qui suppose un process
    allumé en permanence — impossible sur un hébergement gratuit qui s'endort.
    Ici c'est l'appel de Telegram qui réveille le service. Même logique métier
    dans les deux cas (`bot.executer_update`).

    On répond TOUJOURS 200, même si le traitement plante : Telegram rejoue un
    update tant qu'il n'a pas de 2xx, donc un update cassé bloquerait la file
    du bot indéfiniment. L'erreur est journalisée et l'update abandonné (même
    politique que la boucle de long polling)."""
    from . import bot, fx
    secret = config.TELEGRAM_WEBHOOK_SECRET
    if not secret:                       # mode polling : l'endpoint n'existe pas
        raise HTTPException(404, "webhook désactivé")
    recu = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not hmac.compare_digest(recu, secret):
        raise HTTPException(403, "secret de webhook invalide")
    try:
        with _conn() as conn:
            bot.executer_update(conn, update, fx.get_rate(), bot.Transport())
    except Exception as e:
        print(f"[webhook] update {update.get('update_id')} ignoré : "
              f"{bot._masquer(e)}", flush=True)
    return {"ok": True}


# Front buildé (optionnel : présent après `npm run build`)
_dist = BASE_DIR / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="front")
