"""Couche SQLite : schéma watches + favorites, upsert, requêtes."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone

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

-- Utilisateurs (identité Telegram, sans mot de passe). acces_expire : fenêtre
-- d'accès premium pour le modèle « paiement avant le voyage » (NULL = illimité).
CREATE TABLE IF NOT EXISTS users (
    telegram_id  BIGINT PRIMARY KEY,
    first_name   TEXT,
    username     TEXT,
    cree_le      TEXT,
    acces_expire TEXT
);

-- Cibles par MOTS-CLÉS : une alerte utilisateur (« rolex daytona 126506A »).
-- Une montre matche si son blob de recherche contient TOUS les mots-clés (cibles.py).
-- telegram_id = propriétaire de l'alerte (NULL = cible publique/admin).
CREATE TABLE IF NOT EXISTS cibles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    mots_cles   TEXT NOT NULL,
    libelle     TEXT,
    actif       INTEGER DEFAULT 1,
    cree_le     TEXT,
    telegram_id BIGINT
);

-- Prix marché (Chrono24) par référence normalisée : cache de l'auto-pricing.
-- Colonnes wc_* = enrichissement WatchCharts (jours-pour-vendre + volatilité).
CREATE TABLE IF NOT EXISTS market_prices (
    ref_norm    TEXT PRIMARY KEY,   -- référence normalisée (matching.normalize_ref)
    median_eur  REAL,
    p25_eur     REAL,
    p75_eur     REAL,
    n_annonces  INTEGER,
    fetched_at  TEXT,
    source      TEXT DEFAULT 'chrono24',
    erreur      TEXT,               -- non NULL si la requête a échoué (retenté après TTL)
    wc_days_on_market REAL,         -- WatchCharts : médiane jours-pour-vendre (liquidité)
    wc_volatility_pct REAL,         -- WatchCharts : volatilité du prix (dans le temps)
    wc_model_url      TEXT,
    wc_fetched_at     TEXT
);

-- Prix RÉELLEMENT VENDUS (EveryWatch). Clé composite : contrairement à
-- market_prices (par réf), le prix vendu dépend de la CONFIG — deux montres de
-- même réf avec cadrans différents (silver vs turquoise) ont des valeurs
-- différentes. dial/material = valeurs normalisées EN (variants.py), '' si inconnu.
CREATE TABLE IF NOT EXISTS ew_prices (
    ref_norm      TEXT NOT NULL,
    dial          TEXT NOT NULL DEFAULT '',
    material      TEXT NOT NULL DEFAULT '',
    ew_median_eur REAL,
    ew_p25_eur    REAL,
    ew_p75_eur    REAL,
    ew_n_sales    INTEGER,
    ew_matched_by TEXT,              -- 'variant-image' | 'dial+material' | 'ref'
    ew_variant    TEXT,              -- sous-réf exacte si matchée (ex 279384RBR-0009)
    ew_last_eur   REAL,              -- DERNIÈRE vente réelle (la donnée fraîche)
    ew_last_sale  TEXT,              -- sa date (« Apr 2026 »)
    ew_sales_12m  INTEGER,           -- LIQUIDITÉ : nb de ventes réelles sur 12 mois
    fetched_at    TEXT,
    erreur        TEXT,
    PRIMARY KEY (ref_norm, dial, material)
);

-- Historique de prix : un point par CHANGEMENT de prix (pas un par passage de
-- collecte) — matière première des tendances, sparklines et alertes de baisse.
CREATE TABLE IF NOT EXISTS price_history (
    uid             TEXT NOT NULL,
    prix_ttc        REAL,
    prix_detaxe_eur REAL,
    seen_at         TEXT
);
CREATE INDEX IF NOT EXISTS idx_price_history_uid ON price_history(uid);

-- Observabilité : rendement de chaque run de collecte, par boutique. Une boutique
-- en erreur ou tombée à 0 en full déclenche une alerte Telegram admin — sans ça,
-- un connecteur cassé collecterait 0 fiche en silence pendant des semaines.
CREATE TABLE IF NOT EXISTS collecte_runs (
    run_at   TEXT NOT NULL,
    mode     TEXT,
    boutique TEXT NOT NULL,
    fetched  INTEGER,
    erreur   TEXT
);
CREATE INDEX IF NOT EXISTS idx_collecte_runs_btq ON collecte_runs(boutique, run_at);

-- Anti-doublon des alertes (Discord/Telegram) : une alerte par (uid, type).
CREATE TABLE IF NOT EXISTS notified (
    uid   TEXT NOT NULL,
    type  TEXT NOT NULL,        -- 'cible' | 'opportunite' | 'cible:<id>'
    at    TEXT,
    PRIMARY KEY (uid, type)
);

-- Bot Telegram : état de conversation (le bot attend une réponse texte).
-- En base et non en mémoire : un redéploiement ne doit pas bloquer un utilisateur.
CREATE TABLE IF NOT EXISTS bot_state (
    telegram_id  BIGINT PRIMARY KEY,
    etape        TEXT,        -- 'attente_mots_cles' | 'attente_libelle' | 'attente_kw'
    data         TEXT,        -- JSON, ex. {"cible_id": 7}
    maj_le       TEXT
);

-- Bot Telegram : petites valeurs de service (offset getUpdates…).
CREATE TABLE IF NOT EXISTS bot_meta (
    cle     TEXT PRIMARY KEY,
    valeur  TEXT
);

CREATE INDEX IF NOT EXISTS idx_watches_target ON watches(target_id);
CREATE INDEX IF NOT EXISTS idx_watches_boutique ON watches(boutique);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def iso_ago(days: float) -> str:
    """Instant « il y a N jours », même format que now_iso(). Tous les timestamps
    étant stockés en ISO-8601 UTC uniforme, la comparaison de CHAÎNES suffit —
    et elle est PORTABLE : datetime('now', ?) n'existe qu'en SQLite, pas en
    PostgreSQL (bug de prod détecté en revue)."""
    return (datetime.now(timezone.utc)
            - timedelta(days=days)).isoformat(timespec="seconds")


def connect():
    """Connexion portable SQLite (local) ou PostgreSQL (config.DATABASE_URL)."""
    from .dbengine import make_conn
    url = config.DATABASE_URL
    if not url:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        url = "sqlite:///" + str(config.DB_PATH)
    return make_conn(url)


def _columns(conn, table: str) -> set:
    """Colonnes existantes d'une table (introspection portable)."""
    if conn.dialect == "postgresql":
        return {r[0] for r in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name=?", (table,))}
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def init_db(conn):
    schema = SCHEMA
    if conn.dialect == "postgresql":
        # AUTOINCREMENT (SQLite) → SERIAL (PostgreSQL) pour la clé auto de `cibles`
        schema = schema.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
    conn.executescript(schema)
    # migrations légères (base existante) — introspection dialecte-aware
    cols = _columns(conn, "watches")
    if "famille" not in cols:
        conn.execute("ALTER TABLE watches ADD COLUMN famille TEXT DEFAULT ''")
    mcols = _columns(conn, "market_prices")
    for c in ("wc_days_on_market REAL", "wc_volatility_pct REAL",
              "wc_model_url TEXT", "wc_fetched_at TEXT"):
        if c.split()[0] not in mcols:
            conn.execute(f"ALTER TABLE market_prices ADD COLUMN {c}")
    ecols = _columns(conn, "ew_prices")
    for c in ("ew_last_eur REAL", "ew_last_sale TEXT", "ew_sales_12m INTEGER"):
        if ecols and c.split()[0] not in ecols:
            conn.execute(f"ALTER TABLE ew_prices ADD COLUMN {c}")
    ccols = _columns(conn, "cibles")
    if ccols and "telegram_id" not in ccols:   # alertes par utilisateur (étape 2)
        conn.execute("ALTER TABLE cibles ADD COLUMN telegram_id BIGINT")
    # adoption des alertes « orphelines » (telegram_id NULL, créées en local avant
    # le multi-utilisateurs) par l'ADMIN : sans ça, en prod elles seraient
    # invisibles et insupprimables via l'API, mais continueraient de notifier à vie.
    admin = str(config.TELEGRAM_CHAT_ID or "").strip()
    if admin.isdigit():
        conn.execute("UPDATE cibles SET telegram_id=? WHERE telegram_id IS NULL",
                     (int(admin),))
    conn.commit()


def upsert_watch(conn, w: dict) -> bool:
    """Insère une montre ou met à jour last_seen/prix si elle existe. True si nouvelle.
    Enregistre au passage l'HISTORIQUE : un point à l'arrivée puis un point par
    changement de prix (jamais un point par simple passage de collecte)."""
    ts = now_iso()
    status = "vendue" if w.get("vendue") else "dispo"
    exists = conn.execute("SELECT prix_ttc FROM watches WHERE uid = ?",
                          (w["uid"],)).fetchone()
    if exists:
        if w.get("prix_ttc") is None and w.get("prix_ht") is None:
            # Scrape sans prix (sélecteur cassé, page anti-bot…) : on ne fait
            # confiance qu'au statut — on n'écrase JAMAIS un prix valide par NULL.
            conn.execute("UPDATE watches SET last_seen=?, status=? WHERE uid=?",
                         (ts, status, w["uid"]))
        else:
            if (w.get("prix_ttc") is not None
                    and w.get("prix_ttc") != exists["prix_ttc"]):
                _add_price_point(conn, w, ts)     # le prix a bougé → un point
            conn.execute(
                """UPDATE watches SET last_seen=?, prix_ttc=?, prix_ht=?,
                   prix_detaxe_jpy=?, prix_detaxe_eur=?, benef_min=?, benef_max=?,
                   target_id=?, status=?,
                   reference = CASE WHEN ?!='' THEN ? ELSE reference END,
                   marque    = CASE WHEN ?!='' THEN ? ELSE marque END,
                   modele    = CASE WHEN ?!='' THEN ? ELSE modele END,
                   etat      = CASE WHEN ?!='' THEN ? ELSE etat END,
                   famille   = CASE WHEN ?!='' THEN ? ELSE famille END
                   WHERE uid=?""",
                (ts, w.get("prix_ttc"), w.get("prix_ht"), w.get("prix_detaxe_jpy"),
                 w.get("prix_detaxe_eur"), w.get("benef_min"), w.get("benef_max"),
                 w.get("target_id"), status,
                 w.get("reference", ""), w.get("reference", ""),
                 w.get("marque", ""), w.get("marque", ""),
                 w.get("modele", ""), w.get("modele", ""),
                 w.get("etat", ""), w.get("etat", ""),
                 w.get("famille", ""), w.get("famille", ""),
                 w["uid"]),
            )
        conn.commit()
        return False
    conn.execute(
        """INSERT INTO watches
           (uid, boutique, reference, marque, famille, modele, prix_ttc, prix_ht,
            prix_detaxe_jpy, prix_detaxe_eur, benef_min, benef_max, target_id,
            etat, annee, date_ajout_site, description, url, images, status,
            first_seen, last_seen, raw)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (w["uid"], w["boutique"], w.get("reference"), w.get("marque"),
         w.get("famille", ""),
         w.get("modele"), w.get("prix_ttc"), w.get("prix_ht"),
         w.get("prix_detaxe_jpy"), w.get("prix_detaxe_eur"), w.get("benef_min"),
         w.get("benef_max"), w.get("target_id"), w.get("etat"), w.get("annee"),
         w.get("date_ajout_site"), w.get("description"), w.get("url"),
         json.dumps(w.get("images", []), ensure_ascii=False), status, ts, ts,
         json.dumps(w.get("raw", {}), ensure_ascii=False)),
    )
    if w.get("prix_ttc") is not None:
        _add_price_point(conn, w, ts)             # point initial à l'arrivée
    conn.commit()
    return True


def _add_price_point(conn, w: dict, ts: str):
    conn.execute(
        "INSERT INTO price_history (uid, prix_ttc, prix_detaxe_eur, seen_at) "
        "VALUES (?,?,?,?)",
        (w["uid"], w.get("prix_ttc"), w.get("prix_detaxe_eur"), ts))


def get_price_history(conn, uid: str) -> list:
    """Points de prix d'une montre, du plus ancien au plus récent."""
    conn.row_factory = sqlite3.Row
    return conn.execute(
        "SELECT prix_ttc, prix_detaxe_eur, seen_at FROM price_history "
        "WHERE uid=? ORDER BY seen_at", (uid,)).fetchall()


SORTS = {
    "benef": "(benef_max IS NULL), benef_max DESC, first_seen DESC",
    "date":  "(date_ajout_site = '' OR date_ajout_site IS NULL), "
             "date_ajout_site DESC, first_seen DESC",
    "prix":  "(prix_detaxe_eur IS NULL), prix_detaxe_eur ASC",
    "prix_desc": "(prix_detaxe_eur IS NULL), prix_detaxe_eur DESC",
}


def get_watches(conn, only_targets=False, only_dispo=False, marque=None,
                famille=None, sort="benef", limit=2000, q=None,
                prix_min=None, prix_max=None):
    """`prix_min`/`prix_max` : fourchette sur le prix d'ACHAT détaxé en euros —
    ce que coûte la montre, pas ce qu'elle vaut. Le front s'en sert pour ses
    tranches de budget (< 1 k€, 1–5 k€, 5–10 k€, > 10 k€) ; bornes inclusives en
    bas, exclusives en haut, pour qu'une montre pile à 5 000 € tombe dans une
    seule tranche."""
    sql = "SELECT * FROM watches"
    cond, args = [], []
    if prix_min is not None:
        cond.append("prix_detaxe_eur >= ?")
        args.append(prix_min)
    if prix_max is not None:
        cond.append("prix_detaxe_eur < ?")
        args.append(prix_max)
    if only_targets:
        cond.append("target_id IS NOT NULL")
    if only_dispo:
        cond.append("status = 'dispo'")
    if marque:
        cond.append("marque LIKE ?")
        args.append(f"%{marque}%")
    if famille:
        cond.append("famille = ?")
        args.append(famille)
    conds, cargs = _clause_recherche(q)   # recherche texte multilingue
    cond.extend(conds)
    args.extend(cargs)
    if cond:
        sql += " WHERE " + " AND ".join(cond)
    sql += " ORDER BY " + SORTS.get(sort, SORTS["benef"]) + " LIMIT ?"
    args.append(limit)
    return conn.execute(sql, args).fetchall()


def list_marques(conn):
    """Marques distinctes présentes en base (pour le filtre du front)."""
    return [r[0] for r in conn.execute(
        "SELECT marque, COUNT(*) c FROM watches WHERE marque != '' "
        "GROUP BY marque ORDER BY c DESC") if r[0]]


def list_familles(conn, marque: str):
    """Familles (lignes) disponibles pour une marque — filtre cascade du front."""
    return [r[0] for r in conn.execute(
        "SELECT famille, COUNT(*) c FROM watches "
        "WHERE marque LIKE ? AND famille != '' "
        "GROUP BY famille ORDER BY c DESC", (f"%{marque}%",)) if r[0]]


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


def get_favorites(conn, sort="spread"):
    """Favoris ENRICHIS avec les mêmes données que les opportunités (prix vendu EW,
    marge, liquidité). Aucun filtre : un favori s'affiche toujours, même sans donnée
    marché (champs à None). Trié comme les opportunités (les None en dernier)."""
    conn.row_factory = sqlite3.Row
    ew = {(r["ref_norm"], r["dial"], r["material"]): r for r in conn.execute(
        "SELECT * FROM ew_prices WHERE ew_median_eur IS NOT NULL")}
    market = {r["ref_norm"]: r for r in conn.execute(
        "SELECT * FROM market_prices WHERE median_eur IS NOT NULL")}
    rows = conn.execute(
        """SELECT w.* FROM favorites f JOIN watches w ON w.uid = f.uid
           ORDER BY f.added_at DESC""").fetchall()
    out = [_enrich_watch(w, ew, market)[0] for w in rows]
    if sort == "net":
        out.sort(key=lambda d: (d["marge_nette_eur"] is None, -(d["marge_nette_eur"] or 0)))
    elif sort == "liquidite":
        out.sort(key=lambda d: (d["ew_sales_12m"] is None, -(d["ew_sales_12m"] or 0)))
    elif sort == "volatilite":
        out.sort(key=lambda d: (d["wc_volatility_pct"] is None, d["wc_volatility_pct"] or 999))
    else:  # spread brut décroissant (défaut)
        out.sort(key=lambda d: (d["spread_eur"] is None, -(d["spread_eur"] or 0)))
    return out


# --- Utilisateurs (identité Telegram) ---
def upsert_user(conn, telegram_id: int, first_name: str = "", username: str = ""):
    conn.execute(
        "INSERT INTO users (telegram_id, first_name, username, cree_le) "
        "VALUES (?,?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET "
        "first_name=excluded.first_name, username=excluded.username",
        (telegram_id, first_name, username, now_iso()))
    conn.commit()


def get_user(conn, telegram_id: int):
    conn.row_factory = sqlite3.Row
    return conn.execute("SELECT * FROM users WHERE telegram_id=?",
                        (telegram_id,)).fetchone()


# --- Cibles par mots-clés (alertes) ---
def add_cible(conn, mots_cles: str, libelle: str = "", telegram_id=None) -> int:
    # RETURNING id : portable SQLite (≥3.35) et PostgreSQL (lastrowid absent en PG)
    cur = conn.execute(
        "INSERT INTO cibles (mots_cles, libelle, actif, cree_le, telegram_id) "
        "VALUES (?,?,1,?,?) RETURNING id",
        (mots_cles.strip(), (libelle or "").strip(), now_iso(), telegram_id))
    cid = cur.fetchone()[0]
    conn.commit()
    # ANTI-SPAM : le stock DÉJÀ présent qui matche est marqué « déjà notifié » pour
    # cette cible → il apparaît dans la vue Cibles mais ne déclenche PAS d'alerte
    # Telegram. Seules les montres collectées APRÈS la création alerteront.
    from . import cibles as _cibles
    conn.executescript(
        "CREATE TABLE IF NOT EXISTS notified (uid TEXT, type TEXT, at TEXT, "
        "PRIMARY KEY (uid, type));")
    typ = f"cible:{cid}"
    ts = now_iso()
    for w in conn.execute("SELECT * FROM watches WHERE status='dispo'"):
        if _cibles.matche(mots_cles, _cibles.blob_recherche(dict(w))):
            conn.execute("INSERT INTO notified (uid, type, at) VALUES (?,?,?) ON CONFLICT DO NOTHING",
                         (w["uid"], typ, ts))
    conn.commit()
    return cid


def list_cibles(conn, actives_only=False, telegram_id="__all__"):
    """Alertes. Par défaut toutes (usage admin/local). Avec `telegram_id`, seulement
    celles de cet utilisateur (None = les cibles publiques sans propriétaire)."""
    conn.row_factory = sqlite3.Row
    q, args = "SELECT * FROM cibles", []
    conds = []
    if actives_only:
        conds.append("actif=1")
    if telegram_id != "__all__":
        if telegram_id is None:
            conds.append("telegram_id IS NULL")
        else:
            conds.append("telegram_id=?")
            args.append(telegram_id)
    if conds:
        q += " WHERE " + " AND ".join(conds)
    return conn.execute(q + " ORDER BY cree_le DESC", args).fetchall()


def delete_cible(conn, cible_id: int, telegram_id="__all__") -> bool:
    """Supprime une alerte. Avec `telegram_id`, seulement si elle appartient à cet
    utilisateur (empêche de supprimer l'alerte d'un autre). Renvoie True si une
    ligne a réellement été supprimée (False = inexistante ou pas à lui)."""
    if telegram_id != "__all__":
        cur = conn.execute("DELETE FROM cibles WHERE id=? AND telegram_id=?",
                           (cible_id, telegram_id))
    else:
        cur = conn.execute("DELETE FROM cibles WHERE id=?", (cible_id,))
    conn.commit()
    return (cur.rowcount or 0) > 0


def _clause_proprietaire(telegram_id):
    """Fragment SQL + arg pour restreindre une écriture au propriétaire de l'alerte.
    `"__all__"` = pas de restriction (usage local/admin), comme delete_cible."""
    if telegram_id == "__all__":
        return "", []
    if telegram_id is None:
        return " AND telegram_id IS NULL", []
    return " AND telegram_id=?", [telegram_id]


def get_cible(conn, cible_id: int, telegram_id="__all__"):
    """Une alerte, ou None si elle n'existe pas / n'appartient pas à cet utilisateur."""
    conn.row_factory = sqlite3.Row
    cond, args = _clause_proprietaire(telegram_id)
    return conn.execute(f"SELECT * FROM cibles WHERE id=?{cond}",
                        [cible_id] + args).fetchone()


def set_cible_actif(conn, cible_id: int, actif: bool, telegram_id="__all__") -> None:
    """Met une alerte en pause (actif=0) ou la réactive. En pause, elle reste visible
    mais n'apparaît plus dans `list_cibles(actives_only=True)` → plus de notification."""
    cond, args = _clause_proprietaire(telegram_id)
    conn.execute(f"UPDATE cibles SET actif=? WHERE id=?{cond}",
                 [1 if actif else 0, cible_id] + args)
    conn.commit()


def update_cible(conn, cible_id: int, mots_cles=None, libelle=None,
                 telegram_id="__all__") -> None:
    """Modifie les mots-clés et/ou le libellé. Un champ à None n'est pas touché."""
    sets, vals = [], []
    if mots_cles is not None:
        sets.append("mots_cles=?")
        vals.append(mots_cles.strip())
    if libelle is not None:
        sets.append("libelle=?")
        vals.append(libelle.strip())
    if not sets:
        return
    cond, args = _clause_proprietaire(telegram_id)
    conn.execute(f"UPDATE cibles SET {', '.join(sets)} WHERE id=?{cond}",
                 vals + [cible_id] + args)
    conn.commit()


def _watches_matchant(conn, regles):
    """Boucle de matching partagée : pour chaque montre DISPO, les alertes qu'elle
    satisfait. Aucune donnée de prix marché n'est chargée ici."""
    from . import cibles as _cibles
    conn.row_factory = sqlite3.Row
    out = []
    if not regles:
        return out
    for w in conn.execute("SELECT * FROM watches WHERE status='dispo'"):
        blob = _cibles.blob_recherche(dict(w))
        hits = [c for c in regles if _cibles.matche(c["mots_cles"], blob)]
        if hits:
            out.append((w, hits))
    return out


def get_cibles_matches(conn, telegram_id="__all__"):
    """Montres DISPO qui matchent au moins une cible active, enrichies comme les
    opportunités (prix vendu EW + marge). Chaque montre porte `cibles_match` = la
    liste des libellés/mots-clés de cibles qu'elle satisfait. Triée par marge.
    Avec `telegram_id` : uniquement les alertes de cet utilisateur.
    ⚠️ Vue SITE (enrichie). Le bot Telegram utilise `matches_pour_cible` (brut)."""
    regles = list_cibles(conn, actives_only=True, telegram_id=telegram_id)
    paires = _watches_matchant(conn, regles)
    if not paires:
        return []
    ew = {(r["ref_norm"], r["dial"], r["material"]): r for r in conn.execute(
        "SELECT * FROM ew_prices WHERE ew_median_eur IS NOT NULL")}
    market = {r["ref_norm"]: r for r in conn.execute(
        "SELECT * FROM market_prices WHERE median_eur IS NOT NULL")}
    out = []
    for w, hits in paires:
        d = _enrich_watch(w, ew, market)[0]
        d["cibles_match"] = [c["libelle"] or c["mots_cles"] for c in hits]
        out.append(d)
    out.sort(key=lambda d: (d["spread_eur"] is None, -(d["spread_eur"] or 0)))
    return out


def matches_pour_cible(conn, cible_id: int) -> list[dict]:
    """Montres DISPO qui matchent UNE alerte — vue BOT : lignes brutes de `watches`,
    SANS jointure ew_prices/market_prices ni enrichissement. Une donnée jamais
    chargée ne peut pas fuiter (voir la spec du bot, §3 et §8)."""
    cible = get_cible(conn, cible_id)
    if not cible:
        return []
    return [dict(w) for w, _ in _watches_matchant(conn, [cible])]


# --- Bot Telegram : état de conversation et méta ---
def set_bot_etape(conn, telegram_id: int, etape: str, data: dict | None = None) -> None:
    """Mémorise que le bot attend une réponse de cet utilisateur. Remplace l'étape
    précédente (une seule conversation en cours par personne)."""
    conn.execute(
        "INSERT INTO bot_state (telegram_id, etape, data, maj_le) VALUES (?,?,?,?) "
        "ON CONFLICT(telegram_id) DO UPDATE SET etape=excluded.etape, "
        "data=excluded.data, maj_le=excluded.maj_le",
        (telegram_id, etape, json.dumps(data or {}), now_iso()))
    conn.commit()


def get_bot_etape(conn, telegram_id: int):
    """(etape, data) si une conversation est en cours, sinon None."""
    row = conn.execute("SELECT etape, data FROM bot_state WHERE telegram_id=?",
                       (telegram_id,)).fetchone()
    if not row or not row["etape"]:
        return None
    try:
        data = json.loads(row["data"] or "{}")
    except (TypeError, ValueError):
        data = {}
    return row["etape"], data


def clear_bot_etape(conn, telegram_id: int) -> None:
    conn.execute("DELETE FROM bot_state WHERE telegram_id=?", (telegram_id,))
    conn.commit()


def get_bot_meta(conn, cle: str):
    row = conn.execute("SELECT valeur FROM bot_meta WHERE cle=?", (cle,)).fetchone()
    return row["valeur"] if row else None


def set_bot_meta(conn, cle: str, valeur: str) -> None:
    conn.execute(
        "INSERT INTO bot_meta (cle, valeur) VALUES (?,?) "
        "ON CONFLICT(cle) DO UPDATE SET valeur=excluded.valeur", (cle, str(valeur)))
    conn.commit()


def upsert_market_price(conn, ref_norm: str, stats: dict | None, erreur: str = ""):
    """Enregistre le prix marché d'une réf (ou l'échec, pour retenter après TTL)."""
    s = stats or {}
    conn.execute(
        """INSERT INTO market_prices
           (ref_norm, median_eur, p25_eur, p75_eur, n_annonces, fetched_at, erreur)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(ref_norm) DO UPDATE SET
             median_eur=excluded.median_eur, p25_eur=excluded.p25_eur,
             p75_eur=excluded.p75_eur, n_annonces=excluded.n_annonces,
             fetched_at=excluded.fetched_at, erreur=excluded.erreur""",
        (ref_norm, s.get("median_eur"), s.get("p25_eur"), s.get("p75_eur"),
         s.get("n_annonces"), now_iso(), erreur or None),
    )
    conn.commit()


def upsert_wc(conn, ref_norm: str, days, vol, model_url: str):
    """Enregistre l'enrichissement WatchCharts d'une réf (déjà présente en base)."""
    conn.execute(
        """UPDATE market_prices SET wc_days_on_market=?, wc_volatility_pct=?,
           wc_model_url=?, wc_fetched_at=? WHERE ref_norm=?""",
        (days, vol, model_url, now_iso(), ref_norm))
    conn.commit()


def fresh_wc_refs(conn, max_age_days: int) -> set:
    """Réfs déjà enrichies WatchCharts récemment (à ne pas re-résoudre)."""
    return {r[0] for r in conn.execute(
        "SELECT ref_norm FROM market_prices WHERE wc_fetched_at IS NOT NULL "
        "AND wc_fetched_at > ?",
        (iso_ago(max_age_days),))}


def upsert_ew_price(conn, ref_norm: str, dial: str, material: str,
                    stats: dict | None, erreur: str = ""):
    """Enregistre le prix vendu réel EveryWatch d'une config (ou l'échec)."""
    s = stats or {}
    conn.execute(
        """INSERT INTO ew_prices
           (ref_norm, dial, material, ew_median_eur, ew_p25_eur, ew_p75_eur,
            ew_n_sales, ew_matched_by, ew_variant, ew_last_eur, ew_last_sale,
            ew_sales_12m, fetched_at, erreur)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(ref_norm, dial, material) DO UPDATE SET
             ew_median_eur=excluded.ew_median_eur, ew_p25_eur=excluded.ew_p25_eur,
             ew_p75_eur=excluded.ew_p75_eur, ew_n_sales=excluded.ew_n_sales,
             ew_matched_by=excluded.ew_matched_by, ew_variant=excluded.ew_variant,
             ew_last_eur=excluded.ew_last_eur, ew_last_sale=excluded.ew_last_sale,
             ew_sales_12m=excluded.ew_sales_12m,
             fetched_at=excluded.fetched_at, erreur=excluded.erreur""",
        (ref_norm, dial or "", material or "", s.get("ew_median_eur"),
         s.get("ew_p25_eur"), s.get("ew_p75_eur"), s.get("ew_n_sales"),
         s.get("ew_matched_by"), s.get("ew_variant"), s.get("ew_last_eur"),
         s.get("ew_last_sale"), s.get("ew_sales_12m"), now_iso(), erreur or None))
    conn.commit()


def fresh_ew_keys(conn, max_age_days: int) -> set:
    """Configs (ref, dial, material) à ne pas re-requêter : succès frais (TTL plein),
    échecs frais 2 jours seulement (même logique que fresh_market_refs)."""
    rows = conn.execute(
        """SELECT ref_norm, dial, material FROM ew_prices
           WHERE (ew_median_eur IS NOT NULL AND fetched_at > ?)
              OR (ew_median_eur IS NULL AND fetched_at > ?)""",
        (iso_ago(max_age_days), iso_ago(2)))
    return {(r[0], r[1], r[2]) for r in rows}


def fresh_market_refs(conn, max_age_days: int) -> set:
    """Réfs à ne PAS re-requêter : succès frais (TTL plein) — les ÉCHECS ne
    restent frais que 2 jours, pour être retentés rapidement (un timeout ne
    doit pas geler une réf pendant un mois)."""
    rows = conn.execute(
        """SELECT ref_norm FROM market_prices
           WHERE (median_eur IS NOT NULL AND fetched_at > ?)
              OR (median_eur IS NULL AND fetched_at > ?)""",
        (iso_ago(max_age_days), iso_ago(2)))
    return {r[0] for r in rows}


def _enrich_watch(w, ew, market):
    """Enrichit une fiche montre avec ses données de valeur (prix vendu EW, marge,
    liquidité, Chrono24 en secours). Renvoie le dict enrichi, TOUJOURS — les champs
    marché sont None si aucune donnée. `spread_eur` = None quand on ne peut pas
    calculer de marge (pas de référence de prix). Partagé entre opportunités
    (qui filtrent ensuite) et favoris (qui affichent tout)."""
    from .matching import normalize_ref
    from .variants import normalize_dial, normalize_material
    from .pricing import marge_nette_import, liquidity_score
    rn = normalize_ref(w["reference"])
    m = market.get(rn)
    try:
        raw = json.loads(w["raw"] or "{}")
    except (TypeError, ValueError):
        raw = {}
    dial = normalize_dial(raw.get("cadran", ""))
    mat = normalize_material(raw.get("matiere", ""))
    e = ew.get((rn, dial, mat)) or ew.get((rn, "", ""))
    ew_12m = (e["ew_sales_12m"] if e is not None
              and "ew_sales_12m" in e.keys() else None)
    # référence de valeur : prix VENDU réel EveryWatch (priorité), Chrono24 secours
    if e is not None:
        ref_median, ref_p25 = e["ew_median_eur"], e["ew_p25_eur"]
        prix_ref_source = "everywatch"
    elif m is not None:
        ref_median, ref_p25 = m["median_eur"], m["p25_eur"]
        prix_ref_source = "chrono24"
    else:
        ref_median = ref_p25 = None
        prix_ref_source = None
    px = w["prix_detaxe_eur"]
    spread = (ref_median - px) if (ref_median is not None and px is not None) else None
    net = (marge_nette_import(px, ref_median)
           if (ref_median is not None and px is not None)
           else {"marge_nette_eur": None, "couts_import_eur": None})
    wc_days = (m["wc_days_on_market"] if m is not None
               and "wc_days_on_market" in m.keys() else None)
    vol = (round(100 * (m["p75_eur"] - m["p25_eur"]) / m["median_eur"], 1)
           if m is not None and m["p75_eur"] and m["p25_eur"] and m["median_eur"]
           else None)
    d = dict(w)
    d.update({"median_eur": m["median_eur"] if m is not None else None,
              "p25_eur": m["p25_eur"] if m is not None else None,
              "p75_eur": m["p75_eur"] if m is not None else None,
              "n_annonces": m["n_annonces"] if m is not None else None,
              "prix_ref_source": prix_ref_source,
              "ew_median_eur": e["ew_median_eur"] if e is not None else None,
              "ew_p25_eur": e["ew_p25_eur"] if e is not None else None,
              "ew_p75_eur": e["ew_p75_eur"] if e is not None else None,
              "ew_n_sales": e["ew_n_sales"] if e is not None else None,
              "ew_matched_by": e["ew_matched_by"] if e is not None else None,
              "ew_variant": e["ew_variant"] if e is not None else None,
              "ew_last_eur": e["ew_last_eur"]
              if e is not None and "ew_last_eur" in e.keys() else None,
              "ew_last_sale": e["ew_last_sale"]
              if e is not None and "ew_last_sale" in e.keys() else None,
              "ew_sales_12m": ew_12m,
              "ew_liquidity": min(10, ew_12m) if ew_12m is not None else None,
              "spread_eur": round(spread, 2) if spread is not None else None,
              "spread_p25_eur": round(ref_p25 - px, 2)
              if (ref_p25 is not None and px is not None) else None,
              "marge_nette_eur": net["marge_nette_eur"],
              "couts_import_eur": net["couts_import_eur"],
              "volatilite_pct": vol,
              "wc_days_on_market": wc_days,
              "wc_volatility_pct": m["wc_volatility_pct"] if m is not None
              and "wc_volatility_pct" in m.keys() else None,
              "liquidity_score": liquidity_score(wc_days)})
    return d, e, m, ref_median, spread


def _clause_recherche(q: str):
    """Clauses LIKE portables (une par mot-clé, TOUTES requises) sur les champs
    textuels + la famille. La famille étant déjà normalisée en LATIN à la
    collecte, « daytona » matche une montre dont le modèle est en katakana —
    recherche multilingue sans coût Python."""
    conds, args = [], []
    for tok in (q or "").lower().split():
        conds.append(
            "LOWER(COALESCE(marque,'') || ' ' || COALESCE(modele,'') || ' ' "
            "|| COALESCE(reference,'') || ' ' || COALESCE(famille,'') || ' ' "
            "|| COALESCE(description,'')) LIKE ?")
        args.append(f"%{tok}%")
    return conds, args


def get_opportunities(conn, spread_min: float, liq_min: int, sort="spread",
                      marque=None, limit=500, famille=None, prix_max=None,
                      q=None, prix_min=None):
    """Montres dispo dont la médiane marché (Chrono24) dépasse le prix détaxé
    d'au moins spread_min €, avec liquidité suffisante (n_annonces ≥ liq_min).
    Jointure en Python par référence normalisée (robuste, même logique que
    le matching). Filtres optionnels : `marque`, `famille` (modèle générique),
    `prix_max` (prix d'achat détaxé maxi), `q` (recherche texte multilingue)."""
    conn.row_factory = sqlite3.Row   # robuste même si l'appelant ne l'a pas fait
    # EveryWatch (prix VENDUS réels) = référence de valeur. Chrono24 = secours
    # optionnel (plus requis) : une montre avec données EW mais sans Chrono24
    # apparaît quand même. Le filtre de liquidité s'applique par source (cf. boucle).
    ew = {(r["ref_norm"], r["dial"], r["material"]): r for r in conn.execute(
        "SELECT * FROM ew_prices WHERE ew_median_eur IS NOT NULL")}
    market = {r["ref_norm"]: r for r in conn.execute(
        "SELECT * FROM market_prices WHERE median_eur IS NOT NULL")}
    out = []
    sql = ("SELECT * FROM watches WHERE status='dispo' "
           "AND prix_detaxe_eur IS NOT NULL AND reference != ''")
    args = []
    if marque:
        sql += " AND marque LIKE ?"
        args.append(f"%{marque}%")
    if famille:
        sql += " AND famille = ?"
        args.append(famille)
    if prix_min is not None:
        sql += " AND prix_detaxe_eur >= ?"
        args.append(prix_min)
    if prix_max is not None:
        # borne haute EXCLUSIVE, comme get_watches : les tranches de budget du
        # front (< 1 k€, 1–5 k€, 5–10 k€, > 10 k€) ne doivent pas se chevaucher.
        sql += " AND prix_detaxe_eur < ?"
        args.append(prix_max)
    conds, cargs = _clause_recherche(q)
    for c in conds:
        sql += " AND " + c
    args.extend(cargs)
    rows = conn.execute(sql, args)
    for w in rows:
        d, e, m, ref_median, spread = _enrich_watch(w, ew, market)
        # filtre de liquidité par source : assez de ventes réelles (EW) OU
        # d'annonces actives (C24). Ni l'un ni l'autre → pas d'opportunité fiable.
        liquide = ((e is not None and (e["ew_n_sales"] or 0) >= liq_min) or
                   (m is not None and (m["n_annonces"] or 0) >= liq_min))
        if not liquide or spread is None or spread < spread_min:
            continue
        out.append(d)
    if sort == "liquidite":
        # plus liquide d'abord : d'abord la fréquence de ventes réelles EveryWatch
        # (décroissante), puis les jours-pour-vendre WatchCharts en secours
        out.sort(key=lambda d: (d.get("ew_sales_12m") is None and d["wc_days_on_market"] is None,
                                -(d.get("ew_sales_12m") or 0),
                                d["wc_days_on_market"] or 999))
    elif sort == "net":
        out.sort(key=lambda d: d["marge_nette_eur"], reverse=True)
    elif sort == "volatilite":
        out.sort(key=lambda d: (d["wc_volatility_pct"] is None,
                                d["wc_volatility_pct"] or 999))
    else:  # spread brut décroissant (défaut)
        out.sort(key=lambda d: d["spread_eur"], reverse=True)
    return out[:limit]


def load_seen_uids(conn) -> set:
    return {r["uid"] for r in conn.execute("SELECT uid FROM seen")}


def record_seen(conn, uids):
    ts = now_iso()
    conn.executemany(
        "INSERT INTO seen (uid, last_seen) VALUES (?, ?) "
        "ON CONFLICT(uid) DO UPDATE SET last_seen=excluded.last_seen",
        [(u, ts) for u in uids])
    conn.commit()
