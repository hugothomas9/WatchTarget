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


def _observer_collecte(conn, mode: str, rapport: list) -> None:
    """OBSERVABILITÉ : journalise le rendement par boutique (collecte_runs) et
    alerte l'admin Telegram quand un connecteur est en panne — erreur levée, ou
    chute à 0 fiche en mode full (structure du site changée → « succès » vide).
    En incrémental, 0 fiche = pas de nouvel arrivage : normal, pas d'alerte."""
    ts = db.now_iso()
    problemes = []
    for boutique, n, erreur in rapport:
        if erreur:
            problemes.append(f"• {boutique} : en erreur ({erreur[:120]})")
        elif mode == "full" and n == 0:
            prev = conn.execute(
                "SELECT fetched FROM collecte_runs WHERE boutique=? AND mode='full' "
                "AND erreur IS NULL ORDER BY run_at DESC LIMIT 1",
                (boutique,)).fetchone()
            if prev and (prev["fetched"] or 0) > 0:
                problemes.append(f"• {boutique} : 0 fiche (précédent : "
                                 f"{prev['fetched']}) — sélecteur cassé ?")
        conn.execute(
            "INSERT INTO collecte_runs (run_at, mode, boutique, fetched, erreur) "
            "VALUES (?,?,?,?,?)", (ts, mode, boutique, n, erreur))
    conn.commit()
    if problemes:
        from . import telegram as tg
        tg.envoyer("⚠️ <b>Collecte : connecteur(s) en panne</b>\n"
                   + "\n".join(problemes))


def run(mode: str = "incremental", only: list | None = None) -> dict:
    """Collecte les boutiques du registre, enrichit, upsert en base.

    only : liste de clés connecteur à collecter (sinon toutes)."""
    targets = load_targets()
    rate = fx.get_rate()
    conn = db.connect()
    db.init_db(conn)
    debut = db.now_iso()   # borne pour les alertes de baisse (points de CE run)
    # UIDs déjà connus = table seen + montres déjà en base → sautés au re-scan
    # (reprise rapide : on n'ouvre pas les fiches déjà collectées).
    seen = db.load_seen_uids(conn)
    seen |= {r[0] for r in conn.execute("SELECT uid FROM watches")}

    fetched = new = 0
    rapport = []       # (boutique, fiches, erreur) → observabilité + alerte admin
    for entry in registry.BOUTIQUES:
        if only and entry["connector"] not in only:
            continue
        # ISOLATION PAR BOUTIQUE : un site en panne (WAF, down, structure changée)
        # ne doit JAMAIS empêcher la collecte des suivantes — avant ce garde-fou,
        # un simple 403 sur brands_to_scan() tuait le run entier.
        shop_count = 0
        try:
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
            try:
                for w in connector.collect(mode):
                    fetched += 1
                    shop_count += 1
                    w = enrich(w, targets, rate)
                    if db.upsert_watch(conn, w):
                        new += 1
                    if shop_count % 20 == 0:
                        print(f"  ... {entry['boutique']}: {shop_count} fiches "
                              "retenues", flush=True)
            finally:
                if buf:
                    try:
                        db.record_seen(conn, buf)  # flush du reliquat même interrompu
                    except Exception:
                        pass   # ne pas MASQUER l'erreur d'origine du connecteur
            rapport.append((entry["boutique"], shop_count, None))
        except Exception as e:
            print(f"  !! {entry['boutique']} en échec "
                  f"({type(e).__name__}: {e}) — boutique suivante", flush=True)
            # une erreur DB laisse la transaction PostgreSQL « aborted » : sans
            # rollback, TOUTES les boutiques suivantes échoueraient en
            # InFailedSqlTransaction (l'isolation ne servirait à rien)
            try:
                conn.rollback()
            except Exception:
                pass
            rapport.append((entry["boutique"], shop_count,
                            f"{type(e).__name__}: {e}"))
    try:
        _observer_collecte(conn, mode, rapport)
    except Exception:
        pass
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
    try:
        from .telegram import notifier_baisses
        notifier_baisses(conn, depuis=debut)   # 📉 anciennes offres devenues attractives
    except Exception:
        pass
    return {"fetched": fetched, "new": new}
