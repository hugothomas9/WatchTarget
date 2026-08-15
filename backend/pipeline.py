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


def run(mode: str = "incremental", only: list | None = None) -> dict:
    """Collecte les boutiques du registre, enrichit, upsert en base.

    only : liste de clés connecteur à collecter (sinon toutes)."""
    targets = load_targets()
    rate = fx.get_rate()
    conn = db.connect()
    db.init_db(conn)
    # UIDs déjà connus = table seen + montres déjà en base → sautés au re-scan
    # (reprise rapide : on n'ouvre pas les fiches déjà collectées).
    seen = db.load_seen_uids(conn)
    seen |= {r[0] for r in conn.execute("SELECT uid FROM watches")}

    fetched = new = 0
    for entry in registry.BOUTIQUES:
        if only and entry["connector"] not in only:
            continue
        cls = registry.CONNECTORS[entry["connector"]]
        connector = cls(entry)
        connector.seen_uids = set(seen)
        # persiste chaque montre EXAMINÉE (même écartée) → reprise instantanée.
        # Bufferisé par 50 : un commit par item = des milliers de fsync inutiles.
        buf = []

        def sink(uid, _buf=buf):
            _buf.append(uid)
            if len(_buf) >= 50:
                db.record_seen(conn, _buf)
                _buf.clear()

        connector.seen_sink = sink
        shop_count = 0
        try:
            for w in connector.collect(mode):
                fetched += 1
                shop_count += 1
                w = enrich(w, targets, rate)
                if db.upsert_watch(conn, w):
                    new += 1
                if shop_count % 20 == 0:
                    print(f"  ... {entry['boutique']}: {shop_count} fiches retenues",
                          flush=True)
        finally:
            if buf:
                db.record_seen(conn, buf)   # flush du reliquat même sur interruption
    try:
        from .notify import notifier_tout
        notifier_tout()   # alertes Discord (no-op sans webhook configuré)
    except Exception:
        pass
    try:
        from .telegram import notifier_cibles
        notifier_cibles(conn)   # alertes Telegram des cibles mots-clés (no-op sans token)
    except Exception:
        pass
    return {"fetched": fetched, "new": new}
