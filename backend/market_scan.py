"""Backfill / rafraîchissement des prix marché par référence. REPRENABLE :
les réfs déjà fraîches (TTL) sont sautées, on peut interrompre à tout moment.

Usage :
  python -m backend.market_scan                  # candidates prioritaires
  python -m backend.market_scan --limit 100      # borne le nombre de réfs
  python -m backend.market_scan --refs 326.30.40.50.01.001,116610LN
"""
import random
import sys
import time

from . import config, db
from .matching import normalize_ref
from .market import Chrono24Source, EbaySoldSource, stats_from_prices

RESTART_EVERY = 12       # navigateur neuf toutes les N réfs (fingerprint frais)
FAIL_BACKOFF = 90        # pause (s) après un échec (probable challenge)
MAX_CONSECUTIVE_FAILS = 6  # au-delà : on est bloqué, inutile de brûler la liste


def candidate_refs(conn) -> list[tuple[str, str]]:
    """Réfs candidates (ref_norm, ref_brute) triées par intérêt :
    d'abord les réfs avec plusieurs exemplaires JP (liquidité côté achat),
    puis par prix détaxé décroissant, dans la bande configurée."""
    lo, hi = config.MARKET_BAND_EUR
    rows = conn.execute(
        """SELECT reference, COUNT(*) n, MAX(prix_detaxe_eur) px
           FROM watches WHERE status='dispo' AND reference != ''
             AND prix_detaxe_eur BETWEEN ? AND ?
           GROUP BY reference ORDER BY n DESC, px DESC""", (lo, hi))
    seen, out = set(), []
    for r in rows:
        rn = normalize_ref(r["reference"])
        if rn and rn not in seen:
            seen.add(rn)
            out.append((rn, r["reference"]))
    return out


def scan(refs: list[tuple[str, str]] | None = None, limit: int | None = None):
    conn = db.connect()
    db.init_db(conn)
    if refs is None:
        refs = candidate_refs(conn)
    fresh = db.fresh_market_refs(conn, config.MARKET_CACHE_DAYS)
    todo = [(rn, raw) for rn, raw in refs if rn not in fresh]
    if limit:
        todo = todo[:limit]
    print(f"{len(todo)} réf(s) à pricer (sur {len(refs)} candidates, "
          f"{len(fresh)} déjà fraîches)", flush=True)

    # curl_cffi (impersonation Safari) + proxy : pas de navigateur, pas de throttle
    sources = [Chrono24Source()]
    ok = ko = consecutive_fails = 0
    try:
        for i, (rn, raw) in enumerate(todo, 1):
            stats = None
            errs = []
            for src in sources:
                try:
                    if hasattr(src, "fetch"):
                        prices, total = src.fetch(raw)
                    else:
                        prices, total = src.fetch_prices(raw), None
                    stats = stats_from_prices(prices)
                    if stats:
                        if total:
                            stats["n_annonces"] = total   # total réel du site
                        stats["source"] = src.name
                        break
                except Exception as e:
                    errs.append(f"{src.name}:{type(e).__name__}")
                    try:
                        src.close()   # contexte possiblement marqué → navigateur neuf
                    except Exception:
                        pass
            if stats:
                db.upsert_market_price(conn, rn, stats)
                ok += 1
                consecutive_fails = 0
            elif errs:                       # échec technique (≠ zéro annonce)
                db.upsert_market_price(conn, rn, None, erreur=";".join(errs))
                ko += 1
                consecutive_fails += 1
                if consecutive_fails >= 15:  # anomalie réseau/proxy prolongée
                    print(f"ARRET: {consecutive_fails} échecs consécutifs — "
                          "proxy/réseau à vérifier, on réessaiera plus tard",
                          flush=True)
                    break
            else:                            # zéro annonce légitime
                db.upsert_market_price(conn, rn, None, erreur="aucune annonce")
                ko += 1
                consecutive_fails = 0
            if i % 10 == 0:
                print(f"  ... {i}/{len(todo)} (ok={ok}, sans_prix={ko})", flush=True)
            time.sleep(config.MARKET_DELAY + random.uniform(0, 4))
    finally:
        for src in sources:
            try:
                src.close()
            except Exception:
                pass
    enrich_watchcharts(conn)   # jours-pour-vendre + volatilité sur les opportunités
    enrich_everywatch(conn)    # prix VENDUS réels (référence de valeur des opportunités)
    try:
        from .notify import notifier_tout
        notifier_tout()   # alertes Discord si de nouvelles opportunités sont nées
    except Exception:
        pass
    print(f"RESULTAT market_scan ok={ok} sans_prix={ko}", flush=True)
    return {"ok": ok, "sans_prix": ko}


def enrich_watchcharts(conn, limit: int = 40) -> int:
    """Ajoute jours-pour-vendre + volatilité WatchCharts aux réfs des OPPORTUNITÉS.
    DDG n'est sollicité que pour une réf JAMAIS résolue (l'URL de fiche est mise
    en cache dans wc_model_url et réutilisée ensuite). Borné à `limit` réfs/run
    pour ne pas fâcher DDG → couverture étalée sur plusieurs passages (les réfs en
    échec ne sont pas marquées fraîches → retentées au passage suivant)."""
    from .market import WatchChartsSource
    from .matching import normalize_ref
    fresh = db.fresh_wc_refs(conn, config.MARKET_CACHE_DAYS)
    known = {r[0]: r[1] for r in conn.execute(
        "SELECT ref_norm, wc_model_url FROM market_prices "
        "WHERE wc_model_url IS NOT NULL")}
    refs, seen = [], set()
    for o in db.get_opportunities(conn, config.SPREAD_MIN_EUR,
                                  config.LIQUIDITY_MIN_LISTINGS):
        rn = normalize_ref(o["reference"])
        if rn and rn not in seen and rn not in fresh:
            seen.add(rn)
            refs.append((rn, o["reference"]))
    refs = refs[:limit]
    if not refs:
        return 0
    print(f"WatchCharts : {len(refs)} réf(s) à enrichir "
          f"(dont {sum(1 for rn,_ in refs if rn in known)} depuis le cache d'URL)",
          flush=True)
    wc = WatchChartsSource()
    n = 0
    for i, (rn, raw) in enumerate(refs, 1):
        try:
            s = wc.stats(raw, known_url=known.get(rn))
            if s:
                db.upsert_wc(conn, rn, s["days"], s["vol"], s["model_url"])
                n += 1
        except Exception as e:
            print(f"  WC {raw}: {type(e).__name__}", flush=True)
        # délai seulement si DDG a été appelé (réf non cachée)
        time.sleep((config.MARKET_DELAY if rn in known else 6) + random.uniform(0, 3))
        if i % 10 == 0:
            print(f"  ... WC {i}/{len(refs)} (ok={n})", flush=True)
    print(f"RESULTAT watchcharts enrichies={n}", flush=True)
    return n


def analyze_one(conn, uid: str) -> dict:
    """Analyse à la demande d'UNE montre (déclenchée au clic favori) : on vérifie
    d'abord qu'elle est toujours dispo, puis on price sa config sur EveryWatch
    (prix vendus réels + liquidité), exactement comme pour une opportunité. Idempotent
    et sûr à rappeler : si la config est déjà fraîche (TTL), on ne refait pas l'appel."""
    from .variants import normalize_dial, normalize_material
    from . import verify_dispo
    import json as _json

    w = conn.execute("SELECT * FROM watches WHERE uid=?", (uid,)).fetchone()
    if not w:
        return {"uid": uid, "erreur": "introuvable"}

    # 1) dispo ? (ne dégrade pas un statut connu vendu si le site ne répond pas)
    st = verify_dispo.check(w["boutique"], w["url"])
    if st and st != "dispo":
        conn.execute("UPDATE watches SET status=?, last_seen=? WHERE uid=?",
                     (st, db.now_iso(), uid))
        conn.commit()
        return {"uid": uid, "status": st, "ew": None}

    # 2) pricing EveryWatch de la config (réf + cadran + matière)
    try:
        raw = _json.loads(w["raw"] or "{}")
    except (TypeError, ValueError):
        raw = {}
    cadran, matiere = raw.get("cadran", ""), raw.get("matiere", "")
    key = (normalize_ref(w["reference"]), normalize_dial(cadran),
           normalize_material(matiere))
    if not key[0]:
        return {"uid": uid, "status": "dispo", "ew": None, "erreur": "sans référence"}

    # config déjà fraîche → on renvoie l'existant sans re-solliciter EveryWatch
    if key in db.fresh_ew_keys(conn, config.MARKET_CACHE_DAYS):
        return {"uid": uid, "status": "dispo", "ew": "déjà à jour"}

    imgs = w["images"]
    if isinstance(imgs, str):
        try:
            imgs = _json.loads(imgs or "[]")
        except ValueError:
            imgs = []
    img = (imgs or [None])[0]

    from .market_everywatch import EveryWatchSource
    try:
        s = EveryWatchSource().stats(w["reference"], cadran=cadran,
                                     matiere=matiere, image_url=img or "")
    except Exception:
        s = None
    db.upsert_ew_price(conn, *key, s, erreur="" if s else "aucune vente")
    return {"uid": uid, "status": "dispo",
            "ew": s["ew_median_eur"] if s else None}


def enrich_everywatch(conn, limit: int = 25, brands_only: bool = False) -> int:
    """Prix VENDUS réels EveryWatch, par CONFIG (réf + cadran + matière).

    Sans brands_only (défaut) : opportunités d'abord, puis marques multi-variantes.
    Avec brands_only=True  : uniquement les marques 3-5k (Omega, Tudor…) sans toucher
    aux opportunités — utile pour une passe dédiée quand les opps ont saturé le quota."""
    from .variants import normalize_dial, normalize_material
    import json as _json

    def _key(w):
        try:
            raw = _json.loads(w["raw"] or "{}")
        except (TypeError, ValueError):
            raw = {}
        return (normalize_ref(w["reference"]),
                normalize_dial(raw.get("cadran", "")),
                normalize_material(raw.get("matiere", ""))), raw

    fresh = db.fresh_ew_keys(conn, config.MARKET_CACHE_DAYS)
    todo, seen = [], set()

    # 1) les opportunités (toutes marques) — c'est LA valeur qu'on fiabilise
    opps = [] if brands_only else list(db.get_opportunities(
        conn, config.SPREAD_MIN_EUR, config.LIQUIDITY_MIN_LISTINGS))

    # 2) marques multi-variantes bien représentées sur EW : Rolex toutes gammes +
    #    Omega / Tudor / Breitling / Tag Heuer dans la bande 3-5k JP détaxé
    multi_brand = conn.execute(
        "SELECT * FROM watches WHERE status='dispo' AND reference != '' "
        "AND prix_detaxe_eur IS NOT NULL "
        "AND (marque='Rolex' OR (marque IN ('Omega','Tudor','Breitling','Tag Heuer') "
        "     AND prix_detaxe_eur BETWEEN 1500 AND 5000))")
    for w in list(opps) + list(multi_brand):
        key, raw = _key(w)
        if not key[0] or key in seen or key in fresh:
            continue
        seen.add(key)
        imgs = w["images"]
        if isinstance(imgs, str):                 # rows SQLite : images = JSON
            try:
                imgs = _json.loads(imgs or "[]")
            except ValueError:
                imgs = []
        todo.append((key, w["reference"], raw.get("cadran", ""),
                     raw.get("matiere", ""), (imgs or [None])[0]))
        if len(todo) >= limit:
            break
    if not todo:
        return 0
    print(f"EveryWatch : {len(todo)} config(s) à pricer", flush=True)
    from .market_everywatch import EveryWatchSource
    src = EveryWatchSource()
    n = 0
    for i, (key, ref, cadran, matiere, img) in enumerate(todo, 1):
        # RECYCLAGE DE SESSION : la session curl_cffi réutilisée se dégrade sur un
        # long batch (cookies/anti-bot périment) → on repart propre toutes les 15 réfs.
        # PAS d'arrêt-sur-échecs : la liste commence par des niches (Glashütte/Hublot)
        # qui échouent légitimement, un back-off tuerait le run avant les réfs valides.
        if i % 15 == 0:
            src = EveryWatchSource()
        try:
            s = src.stats(ref, cadran=cadran, matiere=matiere, image_url=img or "")
        except Exception:
            s = None
        db.upsert_ew_price(conn, *key, s, erreur="" if s else "aucune vente")
        n += bool(s)
        time.sleep(3 + random.uniform(0, 2))
        if i % 5 == 0:
            print(f"  ... EW {i}/{len(todo)} (ok={n})", flush=True)
    print(f"RESULTAT everywatch pricées={n}", flush=True)
    return n


def main():
    limit = None
    refs = None
    if "--ew" in sys.argv:                   # enrichissement EveryWatch seul
        conn = db.connect()
        db.init_db(conn)
        lim = 25
        if "--limit" in sys.argv:
            lim = int(sys.argv[sys.argv.index("--limit") + 1])
        brands_only = "--brands-only" in sys.argv
        enrich_everywatch(conn, limit=lim, brands_only=brands_only)
        return
    if "--wc" in sys.argv:                    # liquidité WatchCharts seule, en boucle
        conn = db.connect()
        db.init_db(conn)
        # plusieurs passes de 40 (cap DDG) : les réfs en échec ne sont pas marquées
        # fraîches → retentées ; on s'arrête quand une passe n'enrichit plus rien.
        for _ in range(8):
            if enrich_watchcharts(conn) == 0:
                break
        return
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    if "--refs" in sys.argv:
        raw = sys.argv[sys.argv.index("--refs") + 1]
        refs = [(normalize_ref(r), r.strip()) for r in raw.split(",") if r.strip()]
    scan(refs=refs, limit=limit)


if __name__ == "__main__":
    main()
