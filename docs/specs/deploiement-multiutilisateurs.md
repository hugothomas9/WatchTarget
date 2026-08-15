# Déploiement multi-utilisateurs — PLAN (à valider avant de coder)

> Statut : **préparé.** Décision d'accès prise : **accès libre en lecture, identité
> Telegram pour créer des alertes.** Reste à trancher : hébergement.

## 1. Principe d'accès
- **Navigation libre, sans compte** : opportunités, stock, cibles publiques → tout le
  monde voit sans se connecter.
- **Créer une alerte = se connecter via Telegram** (1 clic, pas de mot de passe).
  → identité = id Telegram ; canal d'alerte = le même bot @WatchTargetBot.
- Bénéfice admin : chaque alerte est attribuée à un id Telegram → **on sait qui a mis
  quoi**, et chacun reçoit SES notifications.

## 2. Connexion Telegram — mécanisme retenu : Login Widget
Bouton « Connexion Telegram » (widget officiel). L'utilisateur autorise → le front reçoit :
`{ id, first_name, last_name, username, photo_url, auth_date, hash }`.
- **Vérification obligatoire côté backend** : `secret = SHA256(bot_token)` ;
  recalculer `HMAC-SHA256(data_check_string, secret)` == `hash`. Sinon on rejette
  (empêche l'usurpation). auth_date récent (< 24h).
- `data-request-access="write"` → autorise le bot à écrire à l'utilisateur (livraison
  des alertes garantie).
- Pré-requis : `@BotFather → /setdomain` = le domaine de prod.
- Repli si pas de widget (mobile natif) : deep-link `t.me/WatchTargetBot?start=<code>`.

## 3. Modèle de données (nouvelles tables)
```sql
CREATE TABLE users (
  telegram_id   BIGINT PRIMARY KEY,
  first_name    TEXT,
  username      TEXT,
  cree_le       TIMESTAMPTZ,
  -- modèle « paiement avant voyage » : fenêtre d'accès premium (alertes) optionnelle
  acces_expire  TIMESTAMPTZ            -- NULL = illimité / gratuit
);

-- cibles : ajouter le propriétaire (NULL = cible publique/admin)
ALTER TABLE cibles ADD COLUMN telegram_id BIGINT;   -- FK users
```
- `GET /api/cibles` → filtré par l'utilisateur connecté (ses alertes) + éventuelles
  cibles publiques. Vue admin = toutes, groupées par user.
- Anti-spam alertes : inchangé (seed du stock existant à la création).

## 4. Base : SQLite → PostgreSQL (le vrai moteur du multi-utilisateurs)
SQLite verrouille toute la base en écriture → inadapté à plusieurs utilisateurs +
scrapers simultanés. **PostgreSQL = MVCC** : lecteurs et écrivains ne se bloquent pas,
écritures sur lignes différentes en parallèle. C'est ce qui supprime les files d'attente.
Travail :
- Abstraire l'accès DB (aujourd'hui `sqlite3` en dur dans `db.py`) derrière une couche
  qui accepte une **URL** (`DATABASE_URL`). Option pragmatique : **SQLAlchemy Core**
  (SQL proche de l'actuel, portable SQLite↔Postgres) OU `psycopg` + adaptation des
  requêtes (peu de SQL exotique ici → migration raisonnable).
- Types : `AUTOINCREMENT`→`SERIAL/IDENTITY`, `TEXT` dates → `TIMESTAMPTZ`, JSON `raw`
  → `JSONB` (bonus : requêtable).
- Connexion **pooling** (pgbouncer ou pool applicatif) pour servir N requêtes web.
- Migrations versionnées (Alembic) au lieu des `ALTER TABLE` maison de `init_db`.

## 5. Serveur web (prod)
- `uvicorn` seul = dev. En prod : **plusieurs workers** (`uvicorn --workers N` ou
  gunicorn+uvicorn) derrière HTTPS.
- Les **scrapers** ne tournent PAS dans le process web : ce sont des **jobs séparés**
  (cron/worker) qui écrivent dans Postgres. Le web ne fait que lire/servir → jamais
  bloqué par une collecte (grâce à MVCC).
- Idéal ensuite : une **file** (ex Redis/RQ) pour lisser les écritures des scrapers.

## 6. Hébergement — À TRANCHER
| Option | Pour | Contre |
|---|---|---|
| **PaaS managé** (Railway / Render / Fly.io) | push-to-deploy, Postgres managé, HTTPS auto, ~5-20€/mois | moins de contrôle, coût qui monte à l'échelle |
| **VPS** (Hetzner/OVH/DO) + Docker | pas cher, contrôle total | tu gères OS, Postgres, backups, nginx, TLS |
Reco pour un dev solo qui déploie vite : **PaaS managé** (web + Postgres + worker cron).

## 7. Secrets / config (.env → variables d'env de la plateforme)
`DATABASE_URL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (admin), `PROXY_URL`,
`DISCORD_WEBHOOK_URL`. Jamais commités ; injectés par la plateforme.

## 8. Checklist de migration (ordre)
1. ✅ **FAIT** — `DATABASE_URL` + couche DB portable (`backend/dbengine.py`, SQLAlchemy) :
   même code sur SQLite (local, défaut) et PostgreSQL (`DATABASE_URL` défini). Placeholders
   `?` traduits, `ON CONFLICT`/`RETURNING` portables, PRAGMA/AUTOINCREMENT gérés par dialecte.
   95 tests verts sur SQLite + test de parité PostgreSQL OK. Script de reprise des données :
   `scripts/migrate_sqlite_to_pg.py` (testé : 10 685 montres migrées, comptes identiques).
   **Déployer** : `pip install -r backend/requirements.txt`, définir `DATABASE_URL=postgresql://…`,
   puis `python -m scripts.migrate_sqlite_to_pg` une fois pour transférer l'existant.
2. ✅ **FAIT (backend)** — Table `users` (identité Telegram) + `cibles.telegram_id` +
   filtrage par utilisateur (`db.list_cibles/get_cibles_matches/delete_cible` acceptent
   `telegram_id`). Auth Login Widget vérifiée (`backend/auth_telegram.py` : signature
   HMAC + session cookie signé). Endpoints : `POST /api/auth/telegram`, `GET /api/me`,
   `POST /api/logout`, et `/api/cibles` `/api/alertes` scellés par utilisateur (repli
   « admin/local » sans login pour l'usage direct). Notifs Telegram envoyées au
   PROPRIÉTAIRE de l'alerte. 102 tests verts (dont isolation par user + flux auth).
   **RESTE (déploiement)** : bouton « Connexion Telegram » côté front (widget officiel)
   + `@BotFather /setdomain <domaine-prod>` — le widget ne fonctionne qu'avec un domaine
   HTTPS déclaré, donc à finaliser au déploiement.
4. Backend : endpoint `/api/auth/telegram` (vérif du hash) + session légère (cookie signé).
5. Front : bouton « Connexion Telegram » (widget) ; création d'alerte réservée aux connectés.
6. Scrapers en jobs séparés (cron worker) écrivant dans Postgres.
7. Déploiement PaaS : service web (N workers) + Postgres + worker cron + domaine + HTTPS + /setdomain.
8. Vue admin des alertes par utilisateur.

## Ce qui NE change pas
Toute la logique métier (matching cibles, pricing EW, connecteurs, traduction, filtres)
est indépendante du moteur DB → réutilisée telle quelle. La migration touche surtout
`db.py` (couche d'accès) + l'ajout de l'auth Telegram + le déploiement.
