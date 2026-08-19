# Bot Telegram interactif — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter un bot Telegram interactif (menu d'accueil, création d'alerte, gestion des alertes, consultation des montres correspondantes) par-dessus les alertes par mots-clés déjà en base.

**Architecture:** Deux modules. `backend/bot_ui.py` est **pur** (aucun réseau, aucune DB) : il transforme des données déjà lues en écrans `{"text", "keyboard", "photo"}` — c'est là que vivent presque tous les tests. `backend/bot.py` est un runtime mince : boucle `getUpdates` en long polling, `traiter_update(conn, update, rate)` qui **décide** (lit la DB, renvoie une liste d'actions sans rien envoyer), puis exécution des actions via l'API Telegram. `backend/telegram.py` (push) est aligné sur le même rendu sobre.

**Tech Stack:** Python 3.12, `requests` (déjà présent — aucune nouvelle dépendance), SQLite en local / PostgreSQL en prod via `backend/dbengine.py`, pytest.

**Spec:** `docs/specs/2026-08-17-bot-telegram-interactif.md`
**Journal de bord (à mettre à jour à chaque tâche) :** `docs/JOURNAL-BOT-TELEGRAM.md`

## Global Constraints

- **Bot générique : aucune notion d'admin.** Un seul jeu d'écrans, identique pour tous.
- **Aucune donnée EveryWatch, aucune marge, aucun prix détaxé** — nulle part : ni écran, ni notification push. Champs interdits en sortie : `prix_detaxe_eur`, `prix_detaxe_jpy`, `ew_median_eur`, `ew_n_sales`, `spread_eur`, `benef_min`, `benef_max`. Le bot ne **lit** même pas `ew_prices` / `market_prices`.
- **Prix affiché** = `prix_ttc` (yens) converti en € via `backend/fx.py`, arrondi à l'euro, en euros uniquement. `prix_ttc` absent → « prix sur demande ». **Jamais** de repli sur un champ détaxé.
- **Isolation par utilisateur** : tout appel DB du bot passe `telegram_id = update["...from"]["id"]`. Jamais `"__all__"`. Les alertes `telegram_id IS NULL` n'apparaissent chez personne.
- **Ligne de titre `Marque Modèle — Référence`** en tête de chaque bloc et de chaque push. Jamais sacrifiée à la troncature : ce sont les annonces qui passent en « …et N autres ».
- **Limites Telegram** : légende de photo ≤ **1024** caractères, message texte ≤ 4096, `callback_data` ≤ **64 octets**, 1 message/s par chat → une photo par référence (jamais par annonce).
- **`parse_mode=HTML`** (comme `telegram.envoyer`) → tout texte issu de la base passe par `html.escape`.
- **Constantes de rendu** : `REFS_PAR_PAGE = 3`, `ANNONCES_PAR_REF = 8`, `LIMITE_LEGENDE = 1024`.
- **Portabilité DB** : tout SQL passe par l'interface `dbengine` (placeholders `?`, `RETURNING id` — jamais `lastrowid`). Toute nouvelle table est ajoutée à `SCHEMA` dans `db.py` **et** à `_TABLES` dans `tests/conftest.py`.
- **Un seul poller par token** : `TELEGRAM_BOT_TOKEN_DEV` pour le développement local.
- Tous les tests tournent **sans réseau**.

---

### Task 1 : Tables `bot_state` / `bot_meta` et état de conversation

Le bot doit se souvenir qu'il attend une réponse texte (« envoie-moi tes mots-clés ») et de l'offset `getUpdates`. En base, pas en mémoire : un redéploiement ne doit pas laisser un utilisateur bloqué ni rejouer d'anciens updates.

**Files:**
- Modify: `backend/db.py` (constante `SCHEMA` vers la ligne 111, puis nouvelles fonctions à la fin du bloc « Cibles »)
- Modify: `tests/conftest.py:14-15` (liste `_TABLES`)
- Test: `tests/test_bot_db.py` (créer)

**Interfaces:**
- Consumes: `db.connect()`, `db.init_db(conn)`, `db.now_iso()` (existants)
- Produces:
  - `db.set_bot_etape(conn, telegram_id: int, etape: str, data: dict | None = None) -> None`
  - `db.get_bot_etape(conn, telegram_id: int) -> tuple[str, dict] | None`
  - `db.clear_bot_etape(conn, telegram_id: int) -> None`
  - `db.get_bot_meta(conn, cle: str) -> str | None`
  - `db.set_bot_meta(conn, cle: str, valeur: str) -> None`

- [ ] **Step 1 : Écrire le test qui échoue**

Créer `tests/test_bot_db.py` :

```python
"""Bot Telegram : état de conversation, méta (offset), et gestion des alertes."""
from backend import config, db


def _conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    conn = db.connect()
    db.init_db(conn)
    return conn


def test_etape_conversation_cycle_de_vie(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    assert db.get_bot_etape(conn, 111) is None
    db.set_bot_etape(conn, 111, "attente_mots_cles")
    assert db.get_bot_etape(conn, 111) == ("attente_mots_cles", {})
    # une nouvelle étape remplace la précédente (pas d'empilement)
    db.set_bot_etape(conn, 111, "attente_libelle", {"cible_id": 7})
    assert db.get_bot_etape(conn, 111) == ("attente_libelle", {"cible_id": 7})
    # les utilisateurs sont indépendants
    assert db.get_bot_etape(conn, 222) is None
    db.clear_bot_etape(conn, 111)
    assert db.get_bot_etape(conn, 111) is None


def test_meta_offset(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    assert db.get_bot_meta(conn, "offset") is None
    db.set_bot_meta(conn, "offset", "42")
    assert db.get_bot_meta(conn, "offset") == "42"
    db.set_bot_meta(conn, "offset", "43")        # upsert, pas d'insert en double
    assert db.get_bot_meta(conn, "offset") == "43"
```

- [ ] **Step 2 : Lancer le test pour vérifier qu'il échoue**

Run: `python -m pytest tests/test_bot_db.py -v`
Expected: FAIL — `AttributeError: module 'backend.db' has no attribute 'get_bot_etape'`

- [ ] **Step 3 : Ajouter les tables au schéma**

Dans `backend/db.py`, dans la chaîne `SCHEMA`, juste **avant** les deux `CREATE INDEX` finaux :

```sql
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
```

- [ ] **Step 4 : Écrire l'implémentation minimale**

À la fin de la section « Cibles par mots-clés » de `backend/db.py` (après `get_cibles_matches`) :

```python
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
```

Vérifier que `import json` est déjà en tête de `backend/db.py` ; l'ajouter sinon.

- [ ] **Step 5 : Déclarer les tables dans la fixture de parité PostgreSQL**

Dans `tests/conftest.py`, remplacer la liste `_TABLES` par :

```python
_TABLES = ["watches", "favorites", "seen", "cibles",
           "market_prices", "ew_prices", "notified", "bot_state", "bot_meta"]
```

- [ ] **Step 6 : Lancer les tests**

Run: `python -m pytest tests/test_bot_db.py -v`
Expected: PASS (2 tests)

Run: `python -m pytest -q`
Expected: toute la suite existante reste verte.

- [ ] **Step 7 : Commit**

```bash
git add backend/db.py tests/conftest.py tests/test_bot_db.py
git commit -m "feat(bot): tables bot_state/bot_meta + etat de conversation"
```

---

### Task 2 : Fonctions d'alerte manquantes (`get_cible`, `set_cible_actif`, `update_cible`)

La fiche alerte doit pouvoir lire une alerte, la mettre en pause, la renommer et changer ses mots-clés — en n'agissant **que** sur les alertes de leur propriétaire.

**Files:**
- Modify: `backend/db.py` (section « Cibles », après `delete_cible` vers la ligne 373)
- Test: `tests/test_bot_db.py` (compléter)

**Interfaces:**
- Consumes: `db.add_cible`, `db.list_cibles`, `db.now_iso` (existants)
- Produces:
  - `db.get_cible(conn, cible_id: int, telegram_id="__all__") -> row | None`
  - `db.set_cible_actif(conn, cible_id: int, actif: bool, telegram_id="__all__") -> None`
  - `db.update_cible(conn, cible_id: int, mots_cles=None, libelle=None, telegram_id="__all__") -> None`

`telegram_id` suit exactement la convention de `delete_cible` : `"__all__"` = pas de filtre (usage local/admin), sinon on n'agit que sur les lignes de cet utilisateur.

- [ ] **Step 1 : Écrire le test qui échoue**

Ajouter à `tests/test_bot_db.py` :

```python
def test_get_cible_respecte_le_proprietaire(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    cid = db.add_cible(conn, "rolex daytona", "Ma Daytona", telegram_id=111)
    assert db.get_cible(conn, cid, telegram_id=111)["libelle"] == "Ma Daytona"
    assert db.get_cible(conn, cid, telegram_id=222) is None      # pas la sienne
    assert db.get_cible(conn, 9999, telegram_id=111) is None     # inexistante


def test_pause_et_reactivation(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    cid = db.add_cible(conn, "rolex daytona", "Ma Daytona", telegram_id=111)
    assert db.get_cible(conn, cid, telegram_id=111)["actif"] == 1
    db.set_cible_actif(conn, cid, False, telegram_id=111)
    assert db.get_cible(conn, cid, telegram_id=111)["actif"] == 0
    # une alerte en pause disparaît des alertes actives (donc des notifications)
    assert db.list_cibles(conn, actives_only=True, telegram_id=111) == []
    db.set_cible_actif(conn, cid, True, telegram_id=111)
    assert len(db.list_cibles(conn, actives_only=True, telegram_id=111)) == 1


def test_update_cible_champs_independants_et_isolation(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    cid = db.add_cible(conn, "rolex daytona", "Ma Daytona", telegram_id=111)
    db.update_cible(conn, cid, libelle="Daytona acier", telegram_id=111)
    row = db.get_cible(conn, cid, telegram_id=111)
    assert row["libelle"] == "Daytona acier"
    assert row["mots_cles"] == "rolex daytona"      # inchangé
    db.update_cible(conn, cid, mots_cles="rolex daytona 126500LN", telegram_id=111)
    row = db.get_cible(conn, cid, telegram_id=111)
    assert row["mots_cles"] == "rolex daytona 126500LN"
    assert row["libelle"] == "Daytona acier"        # inchangé
    # un autre utilisateur ne peut rien modifier
    db.update_cible(conn, cid, libelle="pirate", telegram_id=222)
    db.set_cible_actif(conn, cid, False, telegram_id=222)
    row = db.get_cible(conn, cid, telegram_id=111)
    assert row["libelle"] == "Daytona acier" and row["actif"] == 1
```

- [ ] **Step 2 : Lancer le test pour vérifier qu'il échoue**

Run: `python -m pytest tests/test_bot_db.py -v -k "cible or pause"`
Expected: FAIL — `AttributeError: module 'backend.db' has no attribute 'get_cible'`

- [ ] **Step 3 : Écrire l'implémentation minimale**

Dans `backend/db.py`, juste après `delete_cible` :

```python
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
```

- [ ] **Step 4 : Lancer les tests**

Run: `python -m pytest tests/test_bot_db.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5 : Commit**

```bash
git add backend/db.py tests/test_bot_db.py
git commit -m "feat(bot): get_cible / set_cible_actif / update_cible avec isolation"
```

---

### Task 3 : `matches_pour_cible` — les montres d'UNE alerte, sans enrichissement

`get_cibles_matches` évalue **toutes** les alertes d'un coup et enrichit chaque montre avec `ew_prices` / `market_prices`. Le bot a besoin de l'inverse : une seule alerte, données brutes. On **factorise** la boucle de matching au lieu de la copier, et l'enrichissement reste au-dessus (réservé au site).

**Files:**
- Modify: `backend/db.py:376-400` (`get_cibles_matches` — extraire une boucle partagée)
- Test: `tests/test_bot_db.py` (compléter)

**Interfaces:**
- Consumes: `cibles.blob_recherche`, `cibles.matche`, `db.list_cibles` (existants)
- Produces:
  - `db._watches_matchant(conn, regles) -> list[tuple[row, list[row]]]` (interne : la montre et les alertes qu'elle satisfait)
  - `db.matches_pour_cible(conn, cible_id: int) -> list[dict]` — lignes brutes de `watches`, statut `dispo`, **sans** jointure `ew_prices`/`market_prices` ni `_enrich_watch`

- [ ] **Step 1 : Écrire le test qui échoue**

Ajouter à `tests/test_bot_db.py` :

```python
def _watch(uid, ref, prix_ttc, modele="デイトナ", marque="Rolex"):
    return {"uid": uid, "boutique": uid.split(":")[0], "reference": ref,
            "marque": marque, "modele": modele, "url": "https://ex/" + uid,
            "prix_ttc": prix_ttc, "prix_detaxe_eur": 26000.0, "etat": "中古A"}


def test_matches_pour_cible_ne_renvoie_que_cette_alerte(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    db.upsert_watch(conn, _watch("jackroad:126500LN:a", "126500LN", 3210000))
    db.upsert_watch(conn, _watch("cywatch:311.30:b", "311.30.42", 900000,
                                 modele="スピードマスター", marque="Omega"))
    daytona = db.add_cible(conn, "rolex daytona", "Ma Daytona", telegram_id=111)
    speed = db.add_cible(conn, "omega speedmaster", "Speed", telegram_id=111)

    res = db.matches_pour_cible(conn, daytona)
    assert [w["reference"] for w in res] == ["126500LN"]
    assert [w["reference"] for w in db.matches_pour_cible(conn, speed)] == ["311.30.42"]


def test_matches_pour_cible_sans_enrichissement(tmp_path, monkeypatch):
    """Le bot ne doit JAMAIS voir de donnée EveryWatch : elle n'est même pas chargée."""
    conn = _conn(tmp_path, monkeypatch)
    db.upsert_watch(conn, _watch("jackroad:126500LN:a", "126500LN", 3210000))
    db.upsert_ew_price(conn, "126500LN", "", "",
                       {"ew_median_eur": 27400, "ew_p25_eur": 26000,
                        "ew_p75_eur": 29000, "ew_n_sales": 57,
                        "ew_matched_by": "agregat", "ew_variant": ""})
    cid = db.add_cible(conn, "rolex daytona", "Ma Daytona", telegram_id=111)
    w = db.matches_pour_cible(conn, cid)[0]
    for interdit in ("ew_median_eur", "ew_n_sales", "spread_eur", "net_eur"):
        assert interdit not in w
    # le champ brut prix_ttc, lui, est bien là (c'est le prix affiché)
    assert w["prix_ttc"] == 3210000


def test_matches_pour_cible_ignore_les_vendues(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    w = _watch("jackroad:126500LN:a", "126500LN", 3210000)
    w["vendue"] = True
    db.upsert_watch(conn, w)
    cid = db.add_cible(conn, "rolex daytona", "Ma Daytona", telegram_id=111)
    assert db.matches_pour_cible(conn, cid) == []


def test_matches_pour_cible_alerte_inconnue(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    assert db.matches_pour_cible(conn, 4242) == []
```

Rappel : `upsert_ew_price(conn, ref_norm, dial, material, stats, erreur="")` attend un dict `stats` dont les clés portent le préfixe `ew_` (`backend/db.py:437-457`).

- [ ] **Step 2 : Lancer le test pour vérifier qu'il échoue**

Run: `python -m pytest tests/test_bot_db.py -v -k matches_pour_cible`
Expected: FAIL — `AttributeError: module 'backend.db' has no attribute 'matches_pour_cible'`

- [ ] **Step 3 : Factoriser la boucle de matching**

Dans `backend/db.py`, remplacer le corps de `get_cibles_matches` (lignes ~376-400) par cette version, qui délègue le matching à une fonction partagée :

```python
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
```

Note : `_watches_matchant` prend les règles telles que renvoyées par `list_cibles`/`get_cible` (accès par nom `c["mots_cles"]`), donc une seule alerte passe dans une liste d'un élément.

- [ ] **Step 4 : Lancer les tests**

Run: `python -m pytest tests/test_bot_db.py -v`
Expected: PASS (9 tests)

Run: `python -m pytest tests/test_users_cibles.py tests/test_cibles.py tests/test_api.py -v`
Expected: PASS — la factorisation ne change rien à la vue site.

Run: `python -m pytest -q`
Expected: toute la suite verte.

- [ ] **Step 5 : Commit**

```bash
git add backend/db.py tests/test_bot_db.py
git commit -m "refactor(db): boucle de matching partagee + matches_pour_cible (vue bot, brute)"
```

---

### Task 4 : `bot_ui` — annonces, blocs par référence, troncature

Cœur du rendu, entièrement pur. On construit ici les briques du bas : une ligne d'annonce, un bloc de référence avec sa légende de photo, la troncature qui protège le titre.

**Files:**
- Create: `backend/bot_ui.py`
- Test: `tests/test_bot_ui.py` (créer)

**Interfaces:**
- Consumes: rien du projet (module pur ; `html` de la stdlib)
- Produces:
  - `bot_ui.LIMITE_LEGENDE = 1024`, `bot_ui.REFS_PAR_PAGE = 3`, `bot_ui.ANNONCES_PAR_REF = 8`
  - `bot_ui.CHAMPS_INTERDITS: tuple[str, ...]`
  - `bot_ui.fmt_eur(montant: float | None) -> str`
  - `bot_ui.preparer_montres(rows: list[dict], rate: float) -> list[dict]` — ajoute `prix_eur` (converti depuis `prix_ttc`) et `image` (1re image), en ne gardant **que** les champs autorisés
  - `bot_ui.titre_bloc(w: dict) -> str`
  - `bot_ui.ligne_annonce(w: dict) -> str`
  - `bot_ui.grouper_par_reference(montres: list[dict]) -> list[dict]` — `[{"titre", "photo", "annonces"}]`, tri par prix croissant
  - `bot_ui.legende_bloc(bloc: dict) -> str`

- [ ] **Step 1 : Écrire le test qui échoue**

Créer `tests/test_bot_ui.py` :

```python
"""Rendu du bot Telegram — module PUR : aucun réseau, aucune DB."""
from backend import bot_ui

RATE = 0.0060      # 1 JPY = 0.006 EUR → 3 210 000 ¥ = 19 260 €


def w(uid="jackroad:126500LN:a", ref="126500LN", prix_ttc=3210000, etat="Occasion A",
      boutique="jackroad", marque="Rolex", modele="Daytona", images=None, **extra):
    d = {"uid": uid, "reference": ref, "prix_ttc": prix_ttc, "etat": etat,
         "boutique": boutique, "marque": marque, "modele": modele,
         "url": "https://ex/" + uid, "images": images or ["https://img/1.jpg"]}
    d.update(extra)
    return d


def test_fmt_eur_espace_milliers():
    assert bot_ui.fmt_eur(19260.0) == "19 260 €"
    assert bot_ui.fmt_eur(None) == "prix sur demande"


def test_preparer_montres_convertit_le_prix_boutique():
    m = bot_ui.preparer_montres([w()], RATE)[0]
    assert m["prix_eur"] == 19260
    assert m["image"] == "https://img/1.jpg"


def test_preparer_montres_accepte_les_images_en_json():
    """`watches.images` est stocké en JSON sérialisé : la photo doit être retrouvée."""
    m = bot_ui.preparer_montres([w(images='["https://img/9.jpg"]')], RATE)[0]
    assert m["image"] == "https://img/9.jpg"
    assert bot_ui.preparer_montres([w(images="pas du json")], RATE)[0]["image"] is None


def test_preparer_montres_prix_absent():
    m = bot_ui.preparer_montres([w(prix_ttc=None)], RATE)[0]
    assert m["prix_eur"] is None
    assert "prix sur demande" in bot_ui.ligne_annonce(m)


def test_preparer_montres_ne_retombe_jamais_sur_le_detaxe():
    """Un prix boutique manquant ne doit PAS être remplacé par un prix détaxé."""
    m = bot_ui.preparer_montres(
        [w(prix_ttc=None, prix_detaxe_eur=26000.0, prix_detaxe_jpy=4000000.0)], RATE)[0]
    assert m["prix_eur"] is None
    assert "26 000" not in bot_ui.ligne_annonce(m)


def test_preparer_montres_supprime_les_champs_interdits():
    m = bot_ui.preparer_montres(
        [w(prix_detaxe_eur=26000.0, ew_median_eur=27400.0, spread_eur=8100.0,
           benef_min=700.0)], RATE)[0]
    for interdit in bot_ui.CHAMPS_INTERDITS:
        assert interdit not in m


def test_titre_bloc_marque_modele_reference():
    assert bot_ui.titre_bloc(w()) == "Rolex Daytona — 126500LN"


def test_titre_bloc_sans_reference():
    assert bot_ui.titre_bloc(w(ref="")) == "Rolex Daytona"


def test_ligne_annonce_sobre():
    m = bot_ui.preparer_montres([w()], RATE)[0]
    ligne = bot_ui.ligne_annonce(m)
    assert "Occasion A" in ligne and "19 260 €" in ligne and "jackroad" in ligne
    assert 'href="https://ex/jackroad:126500LN:a"' in ligne


def test_ligne_annonce_echappe_le_html():
    m = bot_ui.preparer_montres([w(boutique="A & B <shop>")], RATE)[0]
    assert "A &amp; B &lt;shop&gt;" in bot_ui.ligne_annonce(m)


def test_grouper_par_reference_et_tri_prix_croissant():
    montres = bot_ui.preparer_montres([
        w(uid="a", ref="126500LN", prix_ttc=3500000),
        w(uid="b", ref="116500LN", prix_ttc=3000000),
        w(uid="c", ref="126500LN", prix_ttc=3210000),
    ], RATE)
    blocs = bot_ui.grouper_par_reference(montres)
    # blocs triés par prix mini croissant ; 116500LN (18 000 €) avant 126500LN (19 260 €)
    assert [b["titre"] for b in blocs] == ["Rolex Daytona — 116500LN",
                                           "Rolex Daytona — 126500LN"]
    # annonces triées par prix croissant à l'intérieur du bloc
    assert [a["prix_eur"] for a in blocs[1]["annonces"]] == [19260, 21000]


def test_grouper_montres_sans_prix_en_dernier():
    montres = bot_ui.preparer_montres([
        w(uid="a", ref="AAA", prix_ttc=None),
        w(uid="b", ref="BBB", prix_ttc=3000000),
    ], RATE)
    blocs = bot_ui.grouper_par_reference(montres)
    assert [b["titre"] for b in blocs] == ["Rolex Daytona — BBB", "Rolex Daytona — AAA"]


def test_legende_bloc_titre_puis_annonces():
    montres = bot_ui.preparer_montres([w(uid="a"), w(uid="b", prix_ttc=3500000)], RATE)
    legende = bot_ui.legende_bloc(bot_ui.grouper_par_reference(montres)[0])
    lignes = legende.split("\n")
    assert lignes[0] == "<b>Rolex Daytona — 126500LN</b>"
    assert len(lignes) == 3        # titre + 2 annonces


def test_legende_bloc_plafonne_les_annonces():
    montres = bot_ui.preparer_montres(
        [w(uid=f"u{i}", prix_ttc=3000000 + i) for i in range(40)], RATE)
    legende = bot_ui.legende_bloc(bot_ui.grouper_par_reference(montres)[0])
    assert legende.startswith("<b>Rolex Daytona — 126500LN</b>")   # titre préservé
    assert "…et 32 autres" in legende                             # 40 - 8
    assert len(legende) <= bot_ui.LIMITE_LEGENDE


def test_legende_bloc_titre_survit_aux_annonces_tres_longues():
    """Cas limite : des boutiques/états à rallonge feraient dépasser 1024 caractères.
    Le titre doit rester ; ce sont les annonces qui sont coupées."""
    montres = bot_ui.preparer_montres(
        [w(uid=f"u{i}", boutique="B" * 90, etat="E" * 90, prix_ttc=3000000 + i)
         for i in range(8)], RATE)
    legende = bot_ui.legende_bloc(bot_ui.grouper_par_reference(montres)[0])
    assert legende.startswith("<b>Rolex Daytona — 126500LN</b>")
    assert len(legende) <= bot_ui.LIMITE_LEGENDE


def test_aucun_champ_interdit_dans_le_rendu():
    """Barrière anti-régression : même nourri de données EveryWatch, le rendu n'en
    laisse rien passer."""
    montres = bot_ui.preparer_montres(
        [w(prix_detaxe_eur=26000.0, ew_median_eur=27400.0, ew_n_sales=57,
           spread_eur=8100.0, benef_min=700.0, benef_max=900.0)], RATE)
    legende = bot_ui.legende_bloc(bot_ui.grouper_par_reference(montres)[0])
    for valeur in ("26 000", "27 400", "8 100", "700", "57 ventes", "EveryWatch"):
        assert valeur not in legende
```

- [ ] **Step 2 : Lancer le test pour vérifier qu'il échoue**

Run: `python -m pytest tests/test_bot_ui.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.bot_ui'`

- [ ] **Step 3 : Écrire l'implémentation minimale**

Créer `backend/bot_ui.py` :

```python
"""Rendu du bot Telegram — module PUR : aucun réseau, aucune DB, aucun accès config.

Tout ce qui s'affiche dans le bot est construit ici, à partir de données déjà lues.
C'est ce qui rend le bot testable sans réseau (cf. `verify_dispo.status_from_html`).

RÈGLE DURE (spec 2026-08-17) : le bot est PUBLIC. Aucun prix détaxé, aucune donnée
EveryWatch, aucune marge — `preparer_montres` supprime ces champs à l'entrée et
`tests/test_bot_ui.py` interdit leur réapparition en sortie.
"""
import html
import json

LIMITE_LEGENDE = 1024      # légende d'une photo Telegram
LIMITE_TEXTE = 4096        # message texte Telegram
REFS_PAR_PAGE = 3          # blocs (= photos) par page
ANNONCES_PAR_REF = 8       # annonces listées par référence, puis « …et N autres »

# Champs qui ne doivent JAMAIS sortir du bot (edge d'arbitrage privé).
CHAMPS_INTERDITS = ("prix_detaxe_eur", "prix_detaxe_jpy", "prix_ht",
                    "ew_median_eur", "ew_p25_eur", "ew_p75_eur", "ew_n_sales",
                    "spread_eur", "spread_p25_eur", "net_eur",
                    "benef_min", "benef_max", "median_eur")


def _esc(s) -> str:
    return html.escape(str(s or ""))


def fmt_eur(montant) -> str:
    """« 19 260 € », ou « prix sur demande » si le prix est inconnu."""
    if montant is None:
        return "prix sur demande"
    return f"{round(montant):,} €".replace(",", " ")


def preparer_montres(rows: list[dict], rate: float) -> list[dict]:
    """Lignes brutes de `watches` → montres prêtes à afficher.

    `rate` = EUR pour 1 JPY (fourni par l'appelant : le module reste pur).
    Convertit le PRIX BOUTIQUE `prix_ttc` (yens) en euros — jamais un prix détaxé —
    et ne garde que les champs autorisés.
    """
    out = []
    for r in rows:
        prix_ttc = r.get("prix_ttc")
        # `watches.images` est stocké en JSON sérialisé (db.upsert_watch) ; les tests
        # passent parfois déjà une liste → on accepte les deux formes.
        images = r.get("images") or []
        if isinstance(images, str):
            try:
                images = json.loads(images)
            except (TypeError, ValueError):
                images = []
        if not isinstance(images, list):
            images = []
        out.append({
            "uid": r.get("uid", ""),
            "marque": r.get("marque", "") or "",
            "modele": r.get("modele", "") or "",
            "reference": r.get("reference", "") or "",
            "etat": r.get("etat", "") or "",
            "boutique": r.get("boutique", "") or "",
            "url": r.get("url", "") or "",
            "image": images[0] if images else None,
            "prix_eur": round(prix_ttc * rate) if prix_ttc else None,
        })
    return out


def titre_bloc(w: dict) -> str:
    """« Marque Modèle — Référence ». Ligne PRIORITAIRE : jamais tronquée."""
    gauche = " ".join(p for p in (w.get("marque"), w.get("modele")) if p).strip()
    ref = (w.get("reference") or "").strip()
    return f"{gauche} — {ref}" if ref else gauche


def ligne_annonce(w: dict) -> str:
    """« • Occasion A · 19 260 € · jackroad → Voir » (lien HTML)."""
    bouts = [p for p in (_esc(w.get("etat")), fmt_eur(w.get("prix_eur")),
                         _esc(w.get("boutique"))) if p]
    ligne = "• " + " · ".join(bouts)
    if w.get("url"):
        ligne += f' → <a href="{_esc(w["url"])}">Voir</a>'
    return ligne


def _prix_tri(m: dict):
    """Clé de tri : prix croissant, prix inconnu en dernier."""
    return (m.get("prix_eur") is None, m.get("prix_eur") or 0)


def grouper_par_reference(montres: list[dict]) -> list[dict]:
    """Regroupe par référence (à défaut par titre) : un bloc = une photo + ses annonces.
    Blocs triés par prix mini croissant, annonces triées par prix croissant."""
    blocs: dict = {}
    for m in montres:
        cle = (m.get("reference") or "").strip().lower() or titre_bloc(m).lower()
        b = blocs.setdefault(cle, {"titre": titre_bloc(m), "photo": None,
                                   "annonces": []})
        b["annonces"].append(m)
        if b["photo"] is None and m.get("image"):
            b["photo"] = m["image"]
    for b in blocs.values():
        b["annonces"].sort(key=_prix_tri)
    return sorted(blocs.values(), key=lambda b: _prix_tri(b["annonces"][0]))


def legende_bloc(bloc: dict) -> str:
    """Légende de la photo d'un bloc : titre puis annonces.

    Deux garde-fous : au plus ANNONCES_PAR_REF annonces, et si la légende dépasse
    LIMITE_LEGENDE on retire des annonces une par une — LE TITRE RESTE TOUJOURS.
    """
    titre = f"<b>{_esc(titre_bloc(bloc['annonces'][0]))}</b>"
    annonces = bloc["annonces"]
    n_max = min(len(annonces), ANNONCES_PAR_REF)
    while True:
        lignes = [titre] + [ligne_annonce(a) for a in annonces[:n_max]]
        reste = len(annonces) - n_max
        if reste > 0:
            lignes.append(f"…et {reste} autres")
        texte = "\n".join(lignes)
        if len(texte) <= LIMITE_LEGENDE or n_max == 0:
            return texte
        n_max -= 1
```

- [ ] **Step 4 : Lancer les tests**

Run: `python -m pytest tests/test_bot_ui.py -v`
Expected: PASS (16 tests)

- [ ] **Step 5 : Commit**

```bash
git add backend/bot_ui.py tests/test_bot_ui.py
git commit -m "feat(bot): rendu pur des annonces et des blocs par reference"
```

---

### Task 5 : `bot_ui` — écrans de menu et claviers

Accueil, liste des alertes, fiche alerte, confirmation de suppression, aide. Un écran est un dict `{"text", "keyboard", "photo"}` ; le `callback_data` de chaque bouton doit tenir dans 64 octets.

**Files:**
- Modify: `backend/bot_ui.py` (ajouter à la fin)
- Test: `tests/test_bot_ui.py` (compléter)

**Interfaces:**
- Consumes: `bot_ui._esc`, `bot_ui.LIMITE_TEXTE` (Task 4)
- Produces:
  - `bot_ui.ecran_accueil(nb_alertes: int) -> dict`
  - `bot_ui.ecran_alertes(alertes: list[dict]) -> dict` — chaque alerte : `{"id", "libelle", "mots_cles", "actif", "nb"}`
  - `bot_ui.ecran_alerte(alerte: dict, nb_montres: int, nb_refs: int) -> dict`
  - `bot_ui.ecran_confirm_suppression(alerte: dict) -> dict`
  - `bot_ui.ecran_aide() -> dict`
  - `bot_ui.ecran_demande_mots_cles() -> dict`, `bot_ui.ecran_demande_libelle(alerte: dict) -> dict`, `bot_ui.ecran_demande_kw(alerte: dict) -> dict`
  - Format d'écran : `{"text": str, "keyboard": list[list[dict]], "photo": None}` où un bouton est `{"text": str, "callback_data": str}`

- [ ] **Step 1 : Écrire le test qui échoue**

Ajouter à `tests/test_bot_ui.py` :

```python
def _cbs(ecran):
    return [b["callback_data"] for ligne in ecran["keyboard"] for b in ligne]


def test_ecran_accueil():
    e = bot_ui.ecran_accueil(3)
    assert "WatchTarget" in e["text"]
    assert "Mes alertes (3)" in str(e["keyboard"])
    assert "new" in _cbs(e) and "list" in _cbs(e) and "help" in _cbs(e)
    assert e["photo"] is None


def test_ecran_alertes_actives_et_en_pause():
    e = bot_ui.ecran_alertes([
        {"id": 1, "libelle": "Ma Daytona", "mots_cles": "rolex daytona",
         "actif": 1, "nb": 12},
        {"id": 2, "libelle": "", "mots_cles": "rolex submariner", "actif": 0, "nb": 41},
    ])
    libelles = [b["text"] for ligne in e["keyboard"] for b in ligne]
    assert "🟢 Ma Daytona — 12 montres" in libelles
    assert "⏸ rolex submariner — 41 montres" in libelles     # libellé vide → mots-clés
    assert "a:1" in _cbs(e) and "a:2" in _cbs(e)


def test_ecran_alertes_vide_invite_a_creer():
    e = bot_ui.ecran_alertes([])
    assert "aucune alerte" in e["text"].lower()
    assert "new" in _cbs(e)


def test_ecran_alerte_actions_et_pause():
    a = {"id": 7, "libelle": "Ma Daytona", "mots_cles": "rolex daytona",
         "actif": 1, "cree_le": "2026-08-16T10:00:00+00:00"}
    e = bot_ui.ecran_alerte(a, nb_montres=12, nb_refs=4)
    assert "Ma Daytona" in e["text"] and "rolex daytona" in e["text"]
    assert "12 montres" in e["text"] and "4 référence" in e["text"]
    for cb in ("v:7:1", "a:7:ren", "a:7:kw", "a:7:toggle", "a:7:del", "list"):
        assert cb in _cbs(e)
    assert "pause" in str(e["keyboard"]).lower()
    # alerte en pause → le bouton propose de réactiver
    e2 = bot_ui.ecran_alerte({**a, "actif": 0}, nb_montres=0, nb_refs=0)
    assert "réactiver" in str(e2["keyboard"]).lower()


def test_ecran_confirm_suppression():
    e = bot_ui.ecran_confirm_suppression({"id": 7, "libelle": "Ma Daytona",
                                          "mots_cles": "rolex daytona"})
    assert "définitive" in e["text"]
    assert "a:7:del!" in _cbs(e) and "a:7" in _cbs(e)


def test_callback_data_toujours_sous_64_octets():
    ecrans = [
        bot_ui.ecran_accueil(3),
        bot_ui.ecran_alertes([{"id": 999999, "libelle": "x" * 80,
                               "mots_cles": "y" * 80, "actif": 1, "nb": 3}]),
        bot_ui.ecran_alerte({"id": 999999, "libelle": "x" * 80, "mots_cles": "y" * 80,
                             "actif": 1, "cree_le": "2026-08-16T10:00:00+00:00"}, 5, 2),
        bot_ui.ecran_confirm_suppression({"id": 999999, "libelle": "x" * 80,
                                          "mots_cles": ""}),
        bot_ui.ecran_aide(),
    ]
    for e in ecrans:
        assert len(e["text"]) <= bot_ui.LIMITE_TEXTE
        for cb in _cbs(e):
            assert len(cb.encode()) <= 64, cb


def test_ecran_alerte_echappe_le_html():
    """Un libellé contenant du HTML ne doit pas être interprété par Telegram
    (parse_mode=HTML) : il est échappé."""
    e = bot_ui.ecran_alerte({"id": 1, "libelle": "<b>hack</b>", "mots_cles": "a & b",
                             "actif": 1, "cree_le": ""}, 0, 0)
    assert "&lt;b&gt;hack&lt;/b&gt;" in e["text"]
    assert "<b>hack</b>" not in e["text"]
    assert "a &amp; b" in e["text"]
```

- [ ] **Step 2 : Lancer le test pour vérifier qu'il échoue**

Run: `python -m pytest tests/test_bot_ui.py -v -k ecran`
Expected: FAIL — `AttributeError: module 'backend.bot_ui' has no attribute 'ecran_accueil'`

- [ ] **Step 3 : Écrire l'implémentation minimale**

Ajouter à la fin de `backend/bot_ui.py` :

```python
# --- Écrans -----------------------------------------------------------------
# Un écran = {"text", "keyboard", "photo"}. Un bouton = {"text", "callback_data"}.
# Format des callback_data (≤ 64 octets, cf. tests) :
#   home | list | new | help | noop
#   a:<id>            fiche alerte
#   a:<id>:ren        renommer      a:<id>:kw      changer les mots-clés
#   a:<id>:toggle     pause/reprise a:<id>:del     demander confirmation
#   a:<id>:del!       confirmer la suppression
#   v:<id>:<page>     voir les montres, page 1-indexée

def _b(text: str, cb: str) -> dict:
    return {"text": text, "callback_data": cb}


def _ecran(text: str, keyboard: list, photo=None) -> dict:
    return {"text": text, "keyboard": keyboard, "photo": photo}


def _nom(a: dict) -> str:
    """Nom affichable d'une alerte : son libellé, à défaut ses mots-clés."""
    return (a.get("libelle") or "").strip() or (a.get("mots_cles") or "").strip()


def ecran_accueil(nb_alertes: int) -> dict:
    texte = ("👋 <b>WatchTarget</b> — veille montres Japon\n\n"
             "Crée une alerte, reçois un message dès qu'une montre correspondante "
             "arrive en boutique.")
    return _ecran(texte, [
        [_b("🔔 Créer une alerte", "new")],
        [_b(f"📋 Mes alertes ({nb_alertes})", "list"), _b("❓ Aide", "help")],
    ])


def ecran_alertes(alertes: list[dict]) -> dict:
    if not alertes:
        return _ecran("Tu n'as aucune alerte pour l'instant.",
                      [[_b("🔔 Créer une alerte", "new")], [_b("◀ Menu", "home")]])
    clavier = [[_b(f"{'🟢' if a.get('actif') else '⏸'} {_nom(a)} — "
                   f"{a.get('nb', 0)} montres", f"a:{a['id']}")]
               for a in alertes]
    clavier.append([_b("🔔 Créer une alerte", "new"), _b("◀ Menu", "home")])
    return _ecran("Tes alertes :", clavier)


def ecran_alerte(alerte: dict, nb_montres: int, nb_refs: int) -> dict:
    actif = bool(alerte.get("actif"))
    jour = (alerte.get("cree_le") or "")[:10]
    texte = (f"{'🟢' if actif else '⏸'} <b>{_esc(_nom(alerte))}</b>\n"
             f"Mots-clés : {_esc(alerte.get('mots_cles'))}\n"
             f"{nb_montres} montres · {nb_refs} référence(s)")
    if jour:
        texte += f" · créée le {jour}"
    if not actif:
        texte += "\n\n⏸ En pause : plus aucune notification."
    cid = alerte["id"]
    return _ecran(texte, [
        [_b(f"👁 Voir les montres ({nb_montres})", f"v:{cid}:1")],
        [_b("✏️ Renommer", f"a:{cid}:ren"), _b("🔤 Mots-clés", f"a:{cid}:kw")],
        [_b("▶️ Réactiver" if not actif else "⏸ Mettre en pause", f"a:{cid}:toggle")],
        [_b("🗑 Supprimer", f"a:{cid}:del"), _b("◀ Mes alertes", "list")],
    ])


def ecran_confirm_suppression(alerte: dict) -> dict:
    texte = (f"Supprimer l'alerte « {_esc(_nom(alerte))} » ?\n"
             "Cette action est définitive.")
    return _ecran(texte, [[_b("✅ Oui, supprimer", f"a:{alerte['id']}:del!"),
                           _b("❌ Annuler", f"a:{alerte['id']}")]])


def ecran_aide() -> dict:
    texte = ("<b>Comment ça marche</b>\n\n"
             "1. « Créer une alerte » puis envoie des mots-clés, par exemple "
             "<code>rolex daytona 126500LN</code>.\n"
             "2. Une montre correspond si elle contient <b>tous</b> tes mots-clés — "
             "marque, modèle (même écrit en japonais) ou référence.\n"
             "3. Tu reçois un message dès qu'une montre correspondante arrive dans "
             "une boutique japonaise suivie.\n\n"
             "« Mes alertes » permet de consulter le stock actuel, mettre en pause "
             "ou supprimer une alerte.")
    return _ecran(texte, [[_b("🔔 Créer une alerte", "new")], [_b("◀ Menu", "home")]])


def ecran_demande_mots_cles() -> dict:
    texte = ("Envoie les mots-clés de ton alerte.\n\n"
             "Exemples :\n<code>rolex daytona</code>\n"
             "<code>omega speedmaster 3861</code>\n<code>126500LN</code>\n\n"
             "Une montre doit contenir <b>tous</b> les mots-clés pour correspondre.")
    return _ecran(texte, [[_b("◀ Annuler", "home")]])


def ecran_demande_libelle(alerte: dict) -> dict:
    return _ecran(f"Envoie le nouveau nom de l'alerte « {_esc(_nom(alerte))} ».",
                  [[_b("◀ Annuler", f"a:{alerte['id']}")]])


def ecran_demande_kw(alerte: dict) -> dict:
    return _ecran(f"Envoie les nouveaux mots-clés (actuels : "
                  f"<code>{_esc(alerte.get('mots_cles'))}</code>).",
                  [[_b("◀ Annuler", f"a:{alerte['id']}")]])
```

- [ ] **Step 4 : Lancer les tests**

Run: `python -m pytest tests/test_bot_ui.py -v`
Expected: PASS (23 tests)

- [ ] **Step 5 : Commit**

```bash
git add backend/bot_ui.py tests/test_bot_ui.py
git commit -m "feat(bot): ecrans de menu et claviers inline"
```

---

### Task 6 : `bot_ui` — pagination « voir les montres »

Une page = un en-tête (nom de l'alerte, compteurs, mention de fraîcheur), jusqu'à `REFS_PAR_PAGE` blocs-photo, et un clavier de navigation.

**Files:**
- Modify: `backend/bot_ui.py` (ajouter à la fin)
- Test: `tests/test_bot_ui.py` (compléter)

**Interfaces:**
- Consumes: `grouper_par_reference`, `legende_bloc`, `_b`, `_nom`, `REFS_PAR_PAGE` (Tasks 4-5)
- Produces:
  - `bot_ui.page_montres(alerte: dict, montres: list[dict], page: int) -> dict` renvoyant
    `{"entete": str, "blocs": [{"photo": str|None, "caption": str}], "keyboard": [[...]], "page": int, "pages": int}`
  - `bot_ui.ecran_alerte_vide(alerte: dict) -> dict`

- [ ] **Step 1 : Écrire le test qui échoue**

Ajouter à `tests/test_bot_ui.py` :

```python
ALERTE = {"id": 7, "libelle": "Ma Daytona", "mots_cles": "rolex daytona", "actif": 1}


def _stock(n_refs, par_ref=2):
    montres = []
    for i in range(n_refs):
        for j in range(par_ref):
            montres.append(w(uid=f"u{i}-{j}", ref=f"REF{i:03d}",
                             prix_ttc=3000000 + i * 100000 + j))
    return bot_ui.preparer_montres(montres, RATE)


def test_page_montres_entete_et_pagination():
    p = bot_ui.page_montres(ALERTE, _stock(7), page=1)
    assert "Ma Daytona" in p["entete"]
    assert "14 annonces" in p["entete"] and "7 réf" in p["entete"]
    assert "page 1/3" in p["entete"]                      # 7 réfs / 3 par page
    assert "vérifié quotidiennement" in p["entete"]
    assert len(p["blocs"]) == bot_ui.REFS_PAR_PAGE
    assert p["pages"] == 3


def test_page_montres_navigation_bornee():
    p1 = bot_ui.page_montres(ALERTE, _stock(7), page=1)
    cbs1 = [b["callback_data"] for l in p1["keyboard"] for b in l]
    assert "v:7:2" in cbs1 and "v:7:0" not in cbs1        # pas de « Préc » en page 1
    p3 = bot_ui.page_montres(ALERTE, _stock(7), page=3)
    cbs3 = [b["callback_data"] for l in p3["keyboard"] for b in l]
    assert "v:7:2" in cbs3 and "v:7:4" not in cbs3        # pas de « Suivant » en fin
    assert "a:7" in cbs3                                  # retour à l'alerte
    assert len(p3["blocs"]) == 1                          # 7 = 3 + 3 + 1


def test_page_montres_page_hors_bornes_est_ramenee():
    p = bot_ui.page_montres(ALERTE, _stock(2), page=99)
    assert p["page"] == 1 and p["pages"] == 1 and len(p["blocs"]) == 2


def test_page_montres_chaque_bloc_a_titre_et_legende_valide():
    p = bot_ui.page_montres(ALERTE, _stock(3), page=1)
    for bloc in p["blocs"]:
        assert bloc["caption"].startswith("<b>")
        assert len(bloc["caption"]) <= bot_ui.LIMITE_LEGENDE
        assert bloc["photo"] == "https://img/1.jpg"


def test_ecran_alerte_vide():
    e = bot_ui.ecran_alerte_vide(ALERTE)
    assert "Ma Daytona" in e["text"]
    assert "a:7" in [b["callback_data"] for l in e["keyboard"] for b in l]
```

- [ ] **Step 2 : Lancer le test pour vérifier qu'il échoue**

Run: `python -m pytest tests/test_bot_ui.py -v -k page_montres`
Expected: FAIL — `AttributeError: module 'backend.bot_ui' has no attribute 'page_montres'`

- [ ] **Step 3 : Écrire l'implémentation minimale**

Ajouter à la fin de `backend/bot_ui.py` :

```python
def ecran_alerte_vide(alerte: dict) -> dict:
    texte = (f"Aucune montre en stock ne correspond à « {_esc(_nom(alerte))} » "
             "pour l'instant.\nTu recevras un message dès qu'une arrive.")
    return _ecran(texte, [[_b("◀ Retour à l'alerte", f"a:{alerte['id']}")]])


def page_montres(alerte: dict, montres: list[dict], page: int) -> dict:
    """Une page de résultats : en-tête + jusqu'à REFS_PAR_PAGE blocs-photo + navigation.

    `page` est 1-indexée et ramenée dans les bornes (un vieux bouton ne doit pas
    provoquer une page vide).
    """
    blocs = grouper_par_reference(montres)
    pages = max(1, (len(blocs) + REFS_PAR_PAGE - 1) // REFS_PAR_PAGE)
    page = min(max(1, int(page or 1)), pages)
    debut = (page - 1) * REFS_PAR_PAGE
    visibles = blocs[debut:debut + REFS_PAR_PAGE]

    entete = (f"🎯 <b>{_esc(_nom(alerte))}</b> — {len(montres)} annonces · "
              f"{len(blocs)} réf. · page {page}/{pages}\n"
              "<i>(stock vérifié quotidiennement)</i>")

    nav = []
    if page > 1:
        nav.append(_b("◀ Préc", f"v:{alerte['id']}:{page - 1}"))
    if page < pages:
        nav.append(_b("Suivant ▶", f"v:{alerte['id']}:{page + 1}"))
    clavier = ([nav] if nav else []) + \
        [[_b("◀ Retour à l'alerte", f"a:{alerte['id']}")]]

    return {"entete": entete,
            "blocs": [{"photo": b["photo"], "caption": legende_bloc(b)}
                      for b in visibles],
            "keyboard": clavier, "page": page, "pages": pages}
```

- [ ] **Step 4 : Lancer les tests**

Run: `python -m pytest tests/test_bot_ui.py -v`
Expected: PASS (28 tests)

- [ ] **Step 5 : Commit**

```bash
git add backend/bot_ui.py tests/test_bot_ui.py
git commit -m "feat(bot): pagination des montres d'une alerte"
```

---

### Task 7 : `traiter_update` — dispatch pur (décide, n'envoie rien)

Le cœur logique du runtime : reçoit un update Telegram, lit la DB, renvoie la **liste des actions** à exécuter. Aucun appel réseau → testable intégralement.

**Files:**
- Create: `backend/bot.py`
- Test: `tests/test_bot_dispatch.py` (créer)

**Interfaces:**
- Consumes: toutes les fonctions `db` des Tasks 1-3, tous les écrans `bot_ui` des Tasks 4-6, `db.upsert_user`, `db.add_cible`, `db.delete_cible`, `db.list_cibles`
- Produces:
  - `bot.traiter_update(conn, update: dict, rate: float) -> list[dict]`
  - Types d'action : `{"type": "send", "chat_id", "text", "keyboard"}` · `{"type": "photo", "chat_id", "photo", "caption", "keyboard"}` · `{"type": "edit", "chat_id", "message_id", "text", "keyboard"}` · `{"type": "answer", "callback_id", "text"}`
  - `bot.MSG_ACCES` (texte d'erreur générique quand une alerte n'appartient pas au demandeur)

- [ ] **Step 1 : Écrire le test qui échoue**

Créer `tests/test_bot_dispatch.py` :

```python
"""Dispatch du bot Telegram : décision pure, aucun réseau."""
from backend import bot, config, db

RATE = 0.0060


def _conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    conn = db.connect()
    db.init_db(conn)
    return conn


def _msg(texte, uid=111, chat=111):
    return {"update_id": 1,
            "message": {"message_id": 10, "chat": {"id": chat},
                        "from": {"id": uid, "first_name": "Alice"}, "text": texte}}


def _cb(data, uid=111, chat=111):
    return {"update_id": 2,
            "callback_query": {"id": "cb1", "data": data,
                               "from": {"id": uid, "first_name": "Alice"},
                               "message": {"message_id": 10, "chat": {"id": chat}}}}


def _types(actions):
    return [a["type"] for a in actions]


def _textes(actions):
    return " ".join(str(a.get("text", "")) + str(a.get("caption", ""))
                    for a in actions)


def test_start_affiche_accueil_et_enregistre_l_utilisateur(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    actions = bot.traiter_update(conn, _msg("/start"), RATE)
    assert _types(actions) == ["send"]
    assert "WatchTarget" in actions[0]["text"]
    assert actions[0]["chat_id"] == 111
    assert db.get_user(conn, 111) is not None      # inscrit à la 1re interaction


def test_creation_alerte_en_deux_temps(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    # clic « Créer une alerte » → question + étape mémorisée
    actions = bot.traiter_update(conn, _cb("new"), RATE)
    assert "answer" in _types(actions) and "edit" in _types(actions)
    assert db.get_bot_etape(conn, 111)[0] == "attente_mots_cles"
    # le message texte suivant crée l'alerte
    actions = bot.traiter_update(conn, _msg("rolex daytona"), RATE)
    alertes = db.list_cibles(conn, telegram_id=111)
    assert len(alertes) == 1 and alertes[0]["mots_cles"] == "rolex daytona"
    assert db.get_bot_etape(conn, 111) is None      # conversation refermée
    assert "rolex daytona" in _textes(actions)


def test_texte_hors_conversation_renvoie_l_accueil(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    actions = bot.traiter_update(conn, _msg("bonjour"), RATE)
    assert "WatchTarget" in _textes(actions)
    assert db.list_cibles(conn, telegram_id=111) == []   # rien créé par accident


def test_mots_cles_vides_redemandent(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    bot.traiter_update(conn, _cb("new"), RATE)
    actions = bot.traiter_update(conn, _msg("   "), RATE)
    assert db.list_cibles(conn, telegram_id=111) == []
    assert db.get_bot_etape(conn, 111)[0] == "attente_mots_cles"   # toujours en cours
    assert "mots-clés" in _textes(actions)


def test_liste_puis_fiche_alerte(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    cid = db.add_cible(conn, "rolex daytona", "Ma Daytona", telegram_id=111)
    actions = bot.traiter_update(conn, _cb("list"), RATE)
    assert "Ma Daytona" in str(actions)
    actions = bot.traiter_update(conn, _cb(f"a:{cid}"), RATE)
    assert "Mots-clés" in _textes(actions)


def test_pause_et_reprise_depuis_le_bot(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    cid = db.add_cible(conn, "rolex daytona", "Ma Daytona", telegram_id=111)
    bot.traiter_update(conn, _cb(f"a:{cid}:toggle"), RATE)
    assert db.get_cible(conn, cid, telegram_id=111)["actif"] == 0
    bot.traiter_update(conn, _cb(f"a:{cid}:toggle"), RATE)
    assert db.get_cible(conn, cid, telegram_id=111)["actif"] == 1


def test_suppression_demande_confirmation(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    cid = db.add_cible(conn, "rolex daytona", "Ma Daytona", telegram_id=111)
    actions = bot.traiter_update(conn, _cb(f"a:{cid}:del"), RATE)
    assert "définitive" in _textes(actions)
    assert db.get_cible(conn, cid, telegram_id=111) is not None   # pas encore supprimée
    bot.traiter_update(conn, _cb(f"a:{cid}:del!"), RATE)
    assert db.get_cible(conn, cid, telegram_id=111) is None


def test_renommer_et_changer_les_mots_cles(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    cid = db.add_cible(conn, "rolex daytona", "Ma Daytona", telegram_id=111)
    bot.traiter_update(conn, _cb(f"a:{cid}:ren"), RATE)
    assert db.get_bot_etape(conn, 111) == ("attente_libelle", {"cible_id": cid})
    bot.traiter_update(conn, _msg("Daytona acier"), RATE)
    assert db.get_cible(conn, cid, telegram_id=111)["libelle"] == "Daytona acier"
    bot.traiter_update(conn, _cb(f"a:{cid}:kw"), RATE)
    bot.traiter_update(conn, _msg("rolex daytona 126500LN"), RATE)
    assert db.get_cible(conn, cid, telegram_id=111)["mots_cles"] == \
        "rolex daytona 126500LN"


def test_voir_les_montres_envoie_entete_puis_photos(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    for i in range(2):
        db.upsert_watch(conn, {
            "uid": f"jackroad:126500LN:{i}", "boutique": "jackroad",
            "reference": "126500LN", "marque": "Rolex", "modele": "Daytona",
            "url": f"https://ex/{i}", "prix_ttc": 3210000 + i, "etat": "中古A",
            "images": ["https://img/1.jpg"]})
    cid = db.add_cible(conn, "rolex daytona", "Ma Daytona", telegram_id=111)
    actions = bot.traiter_update(conn, _cb(f"v:{cid}:1"), RATE)
    assert _types(actions) == ["answer", "send", "photo", "send"]
    assert "Ma Daytona" in actions[1]["text"]        # en-tête
    assert actions[2]["photo"] == "https://img/1.jpg"
    assert "19 260 €" in actions[2]["caption"]       # prix boutique converti
    assert actions[-1]["keyboard"]                   # navigation


def test_voir_les_montres_alerte_vide(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    cid = db.add_cible(conn, "rolex introuvable", "Vide", telegram_id=111)
    actions = bot.traiter_update(conn, _cb(f"v:{cid}:1"), RATE)
    assert "Aucune montre" in _textes(actions)
    assert "photo" not in _types(actions)


def test_impossible_d_ouvrir_ou_supprimer_l_alerte_d_un_autre(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    cid = db.add_cible(conn, "rolex daytona", "Ma Daytona", telegram_id=111)
    for data in (f"a:{cid}", f"v:{cid}:1", f"a:{cid}:del!", f"a:{cid}:toggle",
                 f"a:{cid}:ren"):
        actions = bot.traiter_update(conn, _cb(data, uid=222), RATE)
        assert bot.MSG_ACCES in _textes(actions), data
    assert db.get_cible(conn, cid, telegram_id=111)["actif"] == 1   # intacte
    assert db.get_cible(conn, cid, telegram_id=111) is not None


def test_aucune_donnee_everywatch_dans_les_actions(tmp_path, monkeypatch):
    """Même avec un prix EveryWatch en base, rien n'en sort côté bot."""
    conn = _conn(tmp_path, monkeypatch)
    db.upsert_watch(conn, {
        "uid": "jackroad:126500LN:a", "boutique": "jackroad",
        "reference": "126500LN", "marque": "Rolex", "modele": "Daytona",
        "url": "https://ex/a", "prix_ttc": 3210000, "prix_detaxe_eur": 26000.0,
        "etat": "中古A", "images": ["https://img/1.jpg"]})
    db.upsert_ew_price(conn, "126500LN", "", "",
                       {"ew_median_eur": 27400, "ew_p25_eur": 26000,
                        "ew_p75_eur": 29000, "ew_n_sales": 57,
                        "ew_matched_by": "agregat", "ew_variant": ""})
    cid = db.add_cible(conn, "rolex daytona", "Ma Daytona", telegram_id=111)
    dump = str(bot.traiter_update(conn, _cb(f"v:{cid}:1"), RATE))
    for interdit in ("27 400", "26 000", "EveryWatch", "marge", "détaxé"):
        assert interdit not in dump


def test_update_inconnu_ne_casse_rien(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    assert bot.traiter_update(conn, {"update_id": 5}, RATE) == []
    assert bot.traiter_update(conn, _cb("nawak"), RATE)[0]["type"] == "answer"
```

- [ ] **Step 2 : Lancer le test pour vérifier qu'il échoue**

Run: `python -m pytest tests/test_bot_dispatch.py -v`
Expected: FAIL — `ImportError: cannot import name 'bot' from 'backend'`

- [ ] **Step 3 : Écrire l'implémentation minimale**

Créer `backend/bot.py` (partie dispatch ; le runtime réseau vient en Task 8) :

```python
"""Bot Telegram interactif — menu, création et gestion des alertes.

Deux couches :
  * `traiter_update(conn, update, rate)` DÉCIDE : il lit la base et renvoie une liste
    d'actions, sans jamais appeler le réseau → testable intégralement (tests/test_bot_dispatch.py).
  * la boucle `run()` EXÉCUTE : long polling getUpdates puis envoi des actions.

Ce découpage rend un passage en webhook possible sans réécriture : un endpoint FastAPI
n'aurait qu'à appeler `traiter_update` puis `executer`.

RÈGLE DURE : le bot est PUBLIC. Aucun prix détaxé, aucune donnée EveryWatch, aucune
marge (voir docs/specs/2026-08-17-bot-telegram-interactif.md).

Lancer :  python -m backend.bot
"""
import sys
import time

from . import bot_ui, config, db

MSG_ACCES = "Cette alerte n'existe pas ou n'est pas la tienne."
POLL_TIMEOUT = 25          # long polling : secondes d'attente côté Telegram
PAUSE_ERREUR = 5           # pause avant de réessayer après une erreur réseau


# --- actions (structures inertes ; l'exécution réseau est plus bas) ---
def _send(chat_id, ecran) -> dict:
    return {"type": "send", "chat_id": chat_id, "text": ecran["text"],
            "keyboard": ecran["keyboard"]}


def _edit(chat_id, message_id, ecran) -> dict:
    return {"type": "edit", "chat_id": chat_id, "message_id": message_id,
            "text": ecran["text"], "keyboard": ecran["keyboard"]}


def _answer(callback_id, text="") -> dict:
    return {"type": "answer", "callback_id": callback_id, "text": text}


# --- écrans qui ont besoin de la base ---
def _accueil(conn, uid, chat_id, message_id=None):
    nb = len(db.list_cibles(conn, telegram_id=uid))
    ecran = bot_ui.ecran_accueil(nb)
    return [_edit(chat_id, message_id, ecran) if message_id
            else _send(chat_id, ecran)]


def _liste_alertes(conn, uid, chat_id, message_id=None):
    alertes = []
    for c in db.list_cibles(conn, telegram_id=uid):
        d = dict(c)
        d["nb"] = len(db.matches_pour_cible(conn, d["id"]))
        alertes.append(d)
    ecran = bot_ui.ecran_alertes(alertes)
    return [_edit(chat_id, message_id, ecran) if message_id
            else _send(chat_id, ecran)]


def _fiche_alerte(conn, uid, chat_id, cible_id, message_id=None):
    cible = db.get_cible(conn, cible_id, telegram_id=uid)
    if not cible:
        return [_send(chat_id, {"text": MSG_ACCES, "keyboard": []})]
    montres = bot_ui.preparer_montres(db.matches_pour_cible(conn, cible_id), 1.0)
    nb_refs = len(bot_ui.grouper_par_reference(montres))
    ecran = bot_ui.ecran_alerte(dict(cible), len(montres), nb_refs)
    return [_edit(chat_id, message_id, ecran) if message_id
            else _send(chat_id, ecran)]


def _voir_montres(conn, uid, chat_id, cible_id, page, rate):
    cible = db.get_cible(conn, cible_id, telegram_id=uid)
    if not cible:
        return [_send(chat_id, {"text": MSG_ACCES, "keyboard": []})]
    montres = bot_ui.preparer_montres(db.matches_pour_cible(conn, cible_id), rate)
    if not montres:
        return [_send(chat_id, bot_ui.ecran_alerte_vide(dict(cible)))]
    p = bot_ui.page_montres(dict(cible), montres, page)
    actions = [{"type": "send", "chat_id": chat_id, "text": p["entete"],
                "keyboard": []}]
    for bloc in p["blocs"]:
        if bloc["photo"]:
            actions.append({"type": "photo", "chat_id": chat_id,
                            "photo": bloc["photo"], "caption": bloc["caption"],
                            "keyboard": []})
        else:      # pas d'image en base → on envoie le bloc en texte
            actions.append({"type": "send", "chat_id": chat_id,
                            "text": bloc["caption"], "keyboard": []})
    actions.append({"type": "send", "chat_id": chat_id,
                    "text": f"Page {p['page']}/{p['pages']}",
                    "keyboard": p["keyboard"]})
    return actions


# --- dispatch ---
def _traiter_texte(conn, uid, chat_id, texte):
    """Message texte : réponse à une question en cours, sinon retour à l'accueil."""
    etat = db.get_bot_etape(conn, uid)
    if not etat:
        return _accueil(conn, uid, chat_id)
    etape, data = etat
    valeur = (texte or "").strip()

    if etape == "attente_mots_cles":
        if not valeur:
            return [_send(chat_id, bot_ui.ecran_demande_mots_cles())]
        cid = db.add_cible(conn, valeur, "", telegram_id=uid)
        db.clear_bot_etape(conn, uid)
        return _fiche_alerte(conn, uid, chat_id, cid)

    cible_id = data.get("cible_id")
    cible = db.get_cible(conn, cible_id, telegram_id=uid) if cible_id else None
    if not cible:
        db.clear_bot_etape(conn, uid)
        return [_send(chat_id, {"text": MSG_ACCES, "keyboard": []})]

    if etape == "attente_libelle":
        if not valeur:
            return [_send(chat_id, bot_ui.ecran_demande_libelle(dict(cible)))]
        db.update_cible(conn, cible_id, libelle=valeur, telegram_id=uid)
    elif etape == "attente_kw":
        if not valeur:
            return [_send(chat_id, bot_ui.ecran_demande_kw(dict(cible)))]
        db.update_cible(conn, cible_id, mots_cles=valeur, telegram_id=uid)
    db.clear_bot_etape(conn, uid)
    return _fiche_alerte(conn, uid, chat_id, cible_id)


def _traiter_callback(conn, uid, chat_id, message_id, data, rate):
    if data == "home":
        return _accueil(conn, uid, chat_id, message_id)
    if data == "list":
        return _liste_alertes(conn, uid, chat_id, message_id)
    if data == "help":
        return [_edit(chat_id, message_id, bot_ui.ecran_aide())]
    if data == "new":
        db.set_bot_etape(conn, uid, "attente_mots_cles")
        return [_edit(chat_id, message_id, bot_ui.ecran_demande_mots_cles())]

    bouts = data.split(":")
    if bouts[0] == "v" and len(bouts) == 3:
        return _voir_montres(conn, uid, chat_id, int(bouts[1]), int(bouts[2]), rate)

    if bouts[0] == "a" and len(bouts) >= 2:
        cible_id = int(bouts[1])
        action = bouts[2] if len(bouts) > 2 else ""
        cible = db.get_cible(conn, cible_id, telegram_id=uid)
        if not cible:
            return [_send(chat_id, {"text": MSG_ACCES, "keyboard": []})]
        if action == "":
            return _fiche_alerte(conn, uid, chat_id, cible_id, message_id)
        if action == "toggle":
            db.set_cible_actif(conn, cible_id, not cible["actif"], telegram_id=uid)
            return _fiche_alerte(conn, uid, chat_id, cible_id, message_id)
        if action == "del":
            return [_edit(chat_id, message_id,
                          bot_ui.ecran_confirm_suppression(dict(cible)))]
        if action == "del!":
            db.delete_cible(conn, cible_id, telegram_id=uid)
            return _liste_alertes(conn, uid, chat_id, message_id)
        if action == "ren":
            db.set_bot_etape(conn, uid, "attente_libelle", {"cible_id": cible_id})
            return [_edit(chat_id, message_id,
                          bot_ui.ecran_demande_libelle(dict(cible)))]
        if action == "kw":
            db.set_bot_etape(conn, uid, "attente_kw", {"cible_id": cible_id})
            return [_edit(chat_id, message_id, bot_ui.ecran_demande_kw(dict(cible)))]
    return []


def traiter_update(conn, update: dict, rate: float) -> list[dict]:
    """DÉCIDE quoi répondre à un update Telegram. Ne fait AUCUN envoi.
    Renvoie une liste d'actions (voir `executer`)."""
    cb = update.get("callback_query")
    msg = update.get("message")
    src = cb or msg
    if not src:
        return []
    expediteur = src.get("from") or {}
    uid = expediteur.get("id")
    chat_id = ((cb.get("message", {}) if cb else msg).get("chat", {}) or {}).get("id")
    if uid is None or chat_id is None:
        return []
    db.upsert_user(conn, uid, expediteur.get("first_name", "") or "",
                   expediteur.get("username", "") or "")

    if cb:
        actions = _traiter_callback(conn, uid, chat_id,
                                   cb.get("message", {}).get("message_id"),
                                   cb.get("data", "") or "", rate)
        return [_answer(cb.get("id"))] + actions

    texte = (msg.get("text") or "").strip()
    if texte.startswith("/aide") or texte.startswith("/help"):
        return [_send(chat_id, bot_ui.ecran_aide())]
    if texte.startswith("/start") or texte.startswith("/menu"):
        db.clear_bot_etape(conn, uid)
        return _accueil(conn, uid, chat_id)
    return _traiter_texte(conn, uid, chat_id, texte)
```

Note d'implémentation : `_fiche_alerte` n'a pas besoin du taux de change (elle ne fait que compter) — d'où le `1.0` passé à `preparer_montres`.

- [ ] **Step 4 : Lancer les tests**

Run: `python -m pytest tests/test_bot_dispatch.py -v`
Expected: PASS (13 tests)

Run: `python -m pytest -q`
Expected: toute la suite verte.

- [ ] **Step 5 : Commit**

```bash
git add backend/bot.py tests/test_bot_dispatch.py
git commit -m "feat(bot): dispatch pur des updates (menu, alertes, pagination)"
```

---

### Task 8 : Runtime — exécution des actions et boucle de long polling

**Files:**
- Modify: `backend/bot.py` (ajouter à la fin)
- Test: `tests/test_bot_runtime.py` (créer)

**Interfaces:**
- Consumes: `telegram._api`, `bot.traiter_update` (Task 7), `db.get_bot_meta` / `db.set_bot_meta` (Task 1)
- Produces:
  - `bot.executer(action: dict) -> bool` — traduit une action en appel API
  - `bot.boucle(conn, rate_getter, transport, max_tours=None) -> int` — un « tour » = un `getUpdates` + exécution ; `transport` est injectable pour les tests
  - `bot.Transport` — classe minimale avec `get_updates(offset)` et `envoyer(action)`
  - `bot.main()` — point d'entrée `python -m backend.bot`

- [ ] **Step 1 : Écrire le test qui échoue**

Créer `tests/test_bot_runtime.py` :

```python
"""Boucle du bot : offset persisté, actions exécutées — avec un transport factice."""
from backend import bot, config, db


def _conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    conn = db.connect()
    db.init_db(conn)
    return conn


class FauxTransport:
    """Remplace l'API Telegram : sert des updates scriptés, enregistre les envois."""
    def __init__(self, tours):
        self.tours = list(tours)      # une liste d'updates par tour
        self.offsets = []
        self.envoyes = []

    def get_updates(self, offset):
        self.offsets.append(offset)
        return self.tours.pop(0) if self.tours else []

    def envoyer(self, action):
        self.envoyes.append(action)
        return True


def _msg(update_id, texte, uid=111):
    return {"update_id": update_id,
            "message": {"message_id": 10, "chat": {"id": uid},
                        "from": {"id": uid, "first_name": "Alice"}, "text": texte}}


def test_boucle_execute_et_persiste_l_offset(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    t = FauxTransport([[_msg(100, "/start")], [_msg(101, "/aide")]])
    n = bot.boucle(conn, lambda: 0.006, t, max_tours=2)
    assert n == 2                                  # 2 updates traités
    assert t.offsets == [None, 101]                # offset = dernier id + 1 au tour 2
    assert db.get_bot_meta(conn, "offset") == "102"
    assert any("WatchTarget" in str(a.get("text")) for a in t.envoyes)


def test_boucle_reprend_l_offset_persiste(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    db.set_bot_meta(conn, "offset", "500")
    t = FauxTransport([[]])
    bot.boucle(conn, lambda: 0.006, t, max_tours=1)
    assert t.offsets == [500]                      # pas de rejeu des anciens updates


def test_boucle_survit_a_un_update_qui_plante(tmp_path, monkeypatch):
    """Un update malformé ne doit pas tuer le bot ni bloquer l'offset."""
    conn = _conn(tmp_path, monkeypatch)
    casse = {"update_id": 200, "message": {"chat": {"id": 111},
                                           "from": {"id": 111}, "text": None}}
    t = FauxTransport([[casse, _msg(201, "/start")]])
    bot.boucle(conn, lambda: 0.006, t, max_tours=1)
    assert db.get_bot_meta(conn, "offset") == "202"
    assert any("WatchTarget" in str(a.get("text")) for a in t.envoyes)


def test_executer_construit_les_bons_appels(monkeypatch):
    """`executer` traduit chaque type d'action en méthode d'API Telegram."""
    appels = []

    def faux_post(url, data=None, timeout=None):
        appels.append((url.rsplit("/", 1)[-1], data))

        class R:
            ok = True

            @staticmethod
            def json():
                return {"ok": True}
        return R()

    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "123:TEST")
    monkeypatch.setattr(bot.requests, "post", faux_post)
    bot.executer({"type": "send", "chat_id": 1, "text": "hello", "keyboard": []})
    bot.executer({"type": "photo", "chat_id": 1, "photo": "u", "caption": "c",
                  "keyboard": []})
    bot.executer({"type": "edit", "chat_id": 1, "message_id": 2, "text": "t",
                  "keyboard": [[{"text": "b", "callback_data": "home"}]]})
    bot.executer({"type": "answer", "callback_id": "cb1", "text": ""})
    assert [a[0] for a in appels] == ["sendMessage", "sendPhoto", "editMessageText",
                                      "answerCallbackQuery"]
    # le clavier part en JSON sous reply_markup
    assert "callback_data" in appels[2][1]["reply_markup"]
```

- [ ] **Step 2 : Lancer le test pour vérifier qu'il échoue**

Run: `python -m pytest tests/test_bot_runtime.py -v`
Expected: FAIL — `AttributeError: module 'backend.bot' has no attribute 'boucle'`

- [ ] **Step 3 : Écrire l'implémentation minimale**

D'abord compléter les imports **en tête** de `backend/bot.py` (l'en-tête créé en Task 7 devient) :

```python
import json
import sys
import time

import requests

from . import bot_ui, config, db
```

Puis ajouter à la fin du fichier :

```python
# --- exécution réseau -------------------------------------------------------
def _markup(keyboard):
    """Clavier inline → paramètre reply_markup (JSON)."""
    if not keyboard:
        return None
    return json.dumps({"inline_keyboard": keyboard})


def executer(action: dict) -> bool:
    """Exécute UNE action décidée par `traiter_update`. False si l'appel échoue."""
    from .telegram import _api
    typ = action.get("type")
    if typ == "send":
        methode, data = "sendMessage", {
            "chat_id": action["chat_id"], "text": action["text"],
            "parse_mode": "HTML", "disable_web_page_preview": "true"}
    elif typ == "photo":
        methode, data = "sendPhoto", {
            "chat_id": action["chat_id"], "photo": action["photo"],
            "caption": action["caption"], "parse_mode": "HTML"}
    elif typ == "edit":
        methode, data = "editMessageText", {
            "chat_id": action["chat_id"], "message_id": action["message_id"],
            "text": action["text"], "parse_mode": "HTML",
            "disable_web_page_preview": "true"}
    elif typ == "answer":
        methode, data = "answerCallbackQuery", {
            "callback_query_id": action["callback_id"],
            "text": action.get("text", "")}
    else:
        return False
    markup = _markup(action.get("keyboard"))
    if markup:
        data["reply_markup"] = markup
    try:
        r = requests.post(_api(methode), data=data, timeout=30)
        return bool(r.ok and r.json().get("ok"))
    except requests.RequestException:
        return False


class Transport:
    """Accès réel à l'API Telegram (injectable pour les tests)."""

    def get_updates(self, offset):
        from .telegram import _api
        params = {"timeout": POLL_TIMEOUT}
        if offset is not None:
            params["offset"] = offset
        r = requests.get(_api("getUpdates"), params=params,
                         timeout=POLL_TIMEOUT + 10)
        r.raise_for_status()
        return r.json().get("result", []) or []

    def envoyer(self, action):
        return executer(action)


def boucle(conn, rate_getter, transport, max_tours=None) -> int:
    """Long polling : un tour = un getUpdates + exécution des actions décidées.

    `rate_getter` est appelé une fois par tour (un seul appel de change par lot).
    `max_tours=None` = tourner indéfiniment ; les tests passent un entier.
    Un update qui plante est journalisé et SAUTÉ : l'offset avance quand même,
    sinon le bot rejouerait éternellement le même update cassé.
    """
    tours, traites = 0, 0
    offset = db.get_bot_meta(conn, "offset")
    offset = int(offset) if offset else None
    while max_tours is None or tours < max_tours:
        tours += 1
        try:
            updates = transport.get_updates(offset)
        except Exception as e:                       # réseau : on réessaie
            print(f"[bot] getUpdates KO : {e}", flush=True)
            time.sleep(PAUSE_ERREUR)
            continue
        if not updates:
            continue
        rate = rate_getter()
        for up in updates:
            offset = max(offset or 0, up.get("update_id", 0) + 1)
            try:
                for action in traiter_update(conn, up, rate):
                    transport.envoyer(action)
                traites += 1
            except Exception as e:
                print(f"[bot] update {up.get('update_id')} ignoré : {e}", flush=True)
        db.set_bot_meta(conn, "offset", str(offset))
    return traites


def main():
    if not config.TELEGRAM_BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN absent : rien à faire.")
        return 1
    from . import fx
    conn = db.connect()
    db.init_db(conn)
    print("[bot] démarré (long polling)", flush=True)
    try:
        boucle(conn, fx.get_rate, Transport())
    except KeyboardInterrupt:
        print("[bot] arrêt", flush=True)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4 : Lancer les tests**

Run: `python -m pytest tests/test_bot_runtime.py -v`
Expected: PASS (4 tests)

Run: `python -m pytest -q`
Expected: toute la suite verte.

- [ ] **Step 5 : Vérifier le lancement à vide (sans token)**

Run: `TELEGRAM_BOT_TOKEN= python -m backend.bot`
Expected: affiche « TELEGRAM_BOT_TOKEN absent : rien à faire. » et sort — aucun appel réseau.

- [ ] **Step 6 : Commit**

```bash
git add backend/bot.py tests/test_bot_runtime.py
git commit -m "feat(bot): runtime long polling + execution des actions"
```

---

### Task 9 : Aligner la notification push sur le rendu sobre

`telegram.py::_message` affiche encore prix détaxé, prix vendu EveryWatch et marge. Le bot étant public, ce message doit adopter le même rendu — sinon l'edge fuit par la notification. **Bloquant pour la mise en ligne.**

**Files:**
- Modify: `backend/telegram.py:37-56` (`_message`)
- Test: `tests/test_telegram_push.py` (créer)

**Interfaces:**
- Consumes: `bot_ui.titre_bloc`, `bot_ui.ligne_annonce`, `bot_ui.preparer_montres`, `bot_ui.CHAMPS_INTERDITS` (Task 4)
- Produces: `telegram._message(w: dict, libelles: list[str], rate: float | None = None) -> str` (paramètre `rate` ajouté ; `None` → le taux est lu via `fx.get_rate()`)

- [ ] **Step 1 : Écrire le test qui échoue**

Créer `tests/test_telegram_push.py` :

```python
"""Le message push doit être aussi sobre que le bot (aucune fuite de l'edge)."""
from backend import telegram

RATE = 0.0060


def _w(**extra):
    w = {"uid": "jackroad:126500LN:a", "boutique": "jackroad",
         "reference": "126500LN", "marque": "Rolex", "modele": "Daytona",
         "etat": "Occasion A", "prix_ttc": 3210000, "url": "https://ex/a"}
    w.update(extra)
    return w


def test_message_push_titre_puis_annonce_puis_alerte():
    txt = telegram._message(_w(), ["Ma Daytona"], rate=RATE)
    lignes = [l for l in txt.split("\n") if l.strip()]
    assert "Rolex Daytona — 126500LN" in lignes[0]     # titre EN PREMIER
    assert "Occasion A" in txt and "19 260 €" in txt and "jackroad" in txt
    assert "Ma Daytona" in txt                          # quelle alerte a déclenché
    assert "https://ex/a" in txt


def test_message_push_sans_donnee_everywatch_ni_marge():
    txt = telegram._message(
        _w(prix_detaxe_eur=26000.0, ew_median_eur=27400.0, ew_n_sales=57,
           spread_eur=8100.0, benef_min=700.0), ["Ma Daytona"], rate=RATE)
    for interdit in ("26 000", "27 400", "8 100", "Vendu réel", "marge", "détaxé"):
        assert interdit not in txt


def test_message_push_prix_absent():
    txt = telegram._message(_w(prix_ttc=None), ["Ma Daytona"], rate=RATE)
    assert "prix sur demande" in txt
```

- [ ] **Step 2 : Lancer le test pour vérifier qu'il échoue**

Run: `python -m pytest tests/test_telegram_push.py -v`
Expected: FAIL — `TypeError: _message() got an unexpected keyword argument 'rate'`

- [ ] **Step 3 : Écrire l'implémentation minimale**

Dans `backend/telegram.py`, remplacer entièrement `_message` (lignes 37-56) par :

```python
def _message(w: dict, libelles: list[str], rate: float | None = None) -> str:
    """Message d'alerte, MÊME RENDU SOBRE que le bot : titre (marque modèle — réf),
    l'annonce, l'alerte déclenchée, le lien.

    Aucun prix détaxé, aucune donnée EveryWatch, aucune marge : les notifications
    partent à des utilisateurs publics (spec 2026-08-17, §9).
    """
    from . import bot_ui
    if rate is None:
        from . import fx
        rate = fx.get_rate()
    m = bot_ui.preparer_montres([w], rate)[0]
    lignes = [f"🎯 <b>{bot_ui.titre_bloc(m)}</b>",
              bot_ui.ligne_annonce(m).lstrip("• ")]
    if libelles:
        lignes.append("Alerte : " + ", ".join(libelles))
    if m.get("url"):
        lignes.append(m["url"])
    return "\n".join(lignes)
```

Puis, dans `notifier_cibles`, calculer le taux **une fois** avant la boucle et le passer :

```python
    if regles and config.TELEGRAM_BOT_TOKEN:
        from . import fx, verify_dispo
        rate = fx.get_rate()
        matches = db.get_cibles_matches(conn)
```

et à l'appel d'envoi :

```python
                if envoyer(_message(w, [c["libelle"] or c["mots_cles"]], rate=rate),
                           chat_id=dest):
```

- [ ] **Step 4 : Lancer les tests**

Run: `python -m pytest tests/test_telegram_push.py -v`
Expected: PASS (3 tests)

Run: `python -m pytest -q`
Expected: toute la suite verte (vérifier en particulier les tests existants qui touchent `telegram`/`notify`).

- [ ] **Step 5 : Commit**

```bash
git add backend/telegram.py tests/test_telegram_push.py
git commit -m "fix(telegram): push sobre (plus de detaxe ni EveryWatch) aligne sur le bot"
```

---

### Task 10 : Déploiement, configuration et documentation

**Files:**
- Modify: `.env.example`
- Modify: `README-DEPLOY.md`
- Modify: `docs/ROADMAP.md` (section « Fait récemment »)
- Modify: `docs/JOURNAL-BOT-TELEGRAM.md` (§6 Avancement, §8 Historique)

**Interfaces:**
- Consumes: `python -m backend.bot` (Task 8)
- Produces: aucune interface de code — configuration et documentation

- [ ] **Step 1 : Ajouter la variable de développement à `.env.example`**

```
# Bot Telegram. TELEGRAM_BOT_TOKEN = bot de PROD (via @BotFather).
# ⚠️ UN SEUL process peut faire du long polling sur un token : deux pollers = erreur
# 409 et updates volés au hasard. Pour développer pendant que la prod tourne, créer un
# SECOND bot chez @BotFather et mettre son token ici, puis lancer :
#   TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN_DEV python -m backend.bot
TELEGRAM_BOT_TOKEN_DEV=
```

- [ ] **Step 2 : Documenter le troisième service dans `README-DEPLOY.md`**

Ajouter une section :

```markdown
## Service `bot` (bot Telegram interactif)

Même image Docker que `web` et `worker`, commande surchargée :

    python -m backend.bot

- **Doit être always-on** (long polling) — pas d'instance qui s'endort.
- **Exactement une instance** : deux pollers sur le même token = erreur 409.
- Variables nécessaires : `TELEGRAM_BOT_TOKEN`, `DATABASE_URL`.
- Chez @BotFather : `/setcommands` →
      start - Menu principal
      aide - Comment ça marche
- Vérification après déploiement : envoyer `/start` au bot → le menu doit s'afficher.
```

- [ ] **Step 3 : Mettre la roadmap à jour**

Dans `docs/ROADMAP.md`, section « Fait récemment », ajouter en tête :

```markdown
- **Bot Telegram interactif** — menu d'accueil, création d'alerte par mots-clés,
  gestion des alertes (voir / renommer / mots-clés / pause / supprimer), consultation
  des montres correspondantes groupées par référence et paginées. Bot **public et
  générique** : rendu sobre (état · prix boutique € · boutique · lien), aucune donnée
  EveryWatch ni marge — le push a été aligné en conséquence. Spec :
  `docs/specs/2026-08-17-bot-telegram-interactif.md`.
```

- [ ] **Step 4 : Mettre le journal de bord à jour**

Dans `docs/JOURNAL-BOT-TELEGRAM.md` : passer le statut global à « implémenté, X tests verts », cocher les cases de la §6 Avancement, et ajouter une entrée en §8 Historique résumant ce qui a été livré et les écarts éventuels par rapport à la spec.

- [ ] **Step 5 : Vérification finale**

Run: `python -m pytest -q`
Expected: toute la suite verte (compter les tests et noter le total dans le journal).

Run: `python -m pytest tests/test_bot_ui.py tests/test_bot_dispatch.py tests/test_bot_runtime.py tests/test_bot_db.py tests/test_telegram_push.py -q`
Expected: PASS.

Test manuel avec le bot de dev (nécessite un token) :

```bash
TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN_DEV python -m backend.bot
```

Dans Telegram : `/start` → menu ; « Créer une alerte » → envoyer `rolex daytona` →
la fiche s'affiche ; « Voir les montres » → photo + annonces ; « Suivant ▶ » →
page 2 ; « Mettre en pause » → l'icône passe à ⏸ ; « Supprimer » → confirmation.

- [ ] **Step 6 : Commit**

```bash
git add .env.example README-DEPLOY.md docs/ROADMAP.md docs/JOURNAL-BOT-TELEGRAM.md
git commit -m "docs(bot): service de deploiement, token de dev, journal et roadmap"
```

---

## Notes pour l'exécutant

- **Ne jamais** ajouter un champ de prix détaxé, de marge ou EveryWatch dans un rendu du bot : trois tests l'interdisent explicitement (`test_aucun_champ_interdit_dans_le_rendu`, `test_aucune_donnee_everywatch_dans_les_actions`, `test_message_push_sans_donnee_everywatch_ni_marge`). S'ils cassent, c'est une régression fonctionnelle, pas un test à ajuster.
- **Ne jamais** appeler la DB du bot avec `telegram_id="__all__"` : chaque utilisateur ne voit que ses alertes. Exception assumée : `matches_pour_cible(conn, cible_id)` ne filtre pas par propriétaire (elle répond « quelles montres matchent cette alerte »). La vérification d'appartenance se fait **avant**, dans `bot.py`, via `db.get_cible(..., telegram_id=uid)` — ne jamais appeler `matches_pour_cible` sans ce contrôle en amont.
- **Coût des compteurs** : `_liste_alertes` appelle `matches_pour_cible` une fois par alerte, et chaque appel balaie les montres `dispo` (quelques milliers de lignes en mémoire). C'est de l'ordre de la milliseconde par alerte et personne n'a 50 alertes — ne pas optimiser prématurément, mais si la liste devient lente, mettre en cache le comptage plutôt que de recalculer par écran.
- Après chaque tâche, mettre à jour `docs/JOURNAL-BOT-TELEGRAM.md` (c'est le fil de continuité entre sessions).
- Parité PostgreSQL (optionnelle mais recommandée avant déploiement) :
  `TEST_DATABASE_URL=postgresql://user@localhost:5432/scrapmontres python -m pytest -q`
