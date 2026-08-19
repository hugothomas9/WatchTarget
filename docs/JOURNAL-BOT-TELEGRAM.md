# Journal de bord — Bot Telegram interactif

> **À quoi sert ce fichier.** Suivre l'avancement du bot Telegram d'une session à
> l'autre : décisions prises (et pourquoi), craintes/pièges connus, ce qui est fait,
> ce qui reste. À relire en début de session et à mettre à jour à chaque étape.
>
> Dernière mise à jour : **2026-08-17**
> Statut global : **spec validée + plan écrit — prêt à coder, aucun code écrit**
> Spec : `docs/specs/2026-08-17-bot-telegram-interactif.md`
> Plan : `docs/superpowers/plans/2026-08-17-bot-telegram-interactif.md`

---

## 1. Objectif

Transformer le bot Telegram (aujourd'hui **push uniquement**) en **bot interactif**
avec un menu d'accueil :

- 🔔 **Créer une alerte**
- 📋 **Mes alertes** → gérer ses alertes
- clic sur une alerte → **toutes les montres de la base qui matchent cette alerte**

Cible : déploiement en ligne, où les utilisateurs se servent **du bot et du site**
indifféremment.

---

## 2. État du code au démarrage (2026-08-16)

- `backend/telegram.py` — **push seulement** : `envoyer()`, `notifier_cibles()`.
  Aucune boucle d'updates, aucune commande, aucun bouton. Anti-lien-mort : vérifie
  la dispo en direct avant d'alerter.
- `backend/cibles.py` — moteur de mots-clés multilingue (`blob_recherche`, `matche`).
  **Réutilisé tel quel** par le bot.
- `backend/db.py` — tables `cibles` (avec `telegram_id`, `actif`, `libelle`) et
  `users`. Fonctions existantes : `add_cible`, `list_cibles`, `delete_cible`,
  `get_cibles_matches`, `upsert_user`, `get_user`.
- `backend/auth_telegram.py` + `api.py` — le **site** authentifie déjà par Telegram
  Login Widget ; les alertes sont rattachées au `telegram_id`.
- `backend/dbengine.py` — SQLite en local, PostgreSQL en prod (`DATABASE_URL`).
- `Dockerfile` — image unique, commande surchargeable (`web` = uvicorn,
  `worker` = `python -m backend.worker`).

---

## 3. Décisions produit (validées par Hugo, 2026-08-16)

| Sujet | Décision |
|---|---|
| **Création d'alerte** | **Texte libre en une étape** : le bot demande les mots-clés, l'utilisateur répond en un message (« rolex daytona 126506A »). Réutilise `cibles.matche`. Pas de wizard par boutons. |
| **Affichage des montres** | **Photo en tête, annonces en lignes** dessous : état · prix · boutique · lien. |
| **Regroupement** | **Un bloc par référence**, paginé (3-5 blocs par page) : photo + titre de la réf, puis toutes ses annonces en lignes. Boutons « Suivant ▶ / ◀ Retour ». |
| **Accès** | **Ouvert à tous, bot GÉNÉRIQUE — pas de notion d'admin** (décidé 2026-08-16, révision). Un seul écran pour tout le monde. Un bot perso/plus riche pourra venir plus tard si besoin. |
| **Contenu d'une annonce** | **Sobre** : état · prix de vente converti en € · boutique · lien. **Ni prix détaxé, ni prix de revente EveryWatch, ni marge** — l'edge d'arbitrage reste privé, visible uniquement sur le site (protégé par le login Telegram). |
| **EveryWatch — RÈGLE DURE (confirmée 2026-08-17)** | **Aucune donnée EveryWatch nulle part dans le bot**, ni affichage ni notification. Le bot ne les **charge même pas** : `matches_pour_cible` renvoie les lignes brutes de `watches`, sans `_enrich_watch` ni jointure `ew_prices`/`market_prices`. Une donnée jamais chargée ne peut pas fuiter. |
| **Actions sur une alerte** | Les 4 : **voir les montres**, **supprimer** (avec confirmation), **activer/désactiver (pause)**, **modifier les mots-clés / renommer**. |
| **Runtime** | **Long polling maison avec `requests`** (approche A), process séparé `python -m backend.bot`. |

### Pourquoi le long polling et pas un webhook

- Aucune URL publique / certificat / `setWebhook` à re-pointer à chaque déploiement.
- Marche **en local comme en prod** (Hugo développe en local).
- Zéro nouvelle dépendance : `requests` est déjà utilisé ; le repo est 100 % synchrone
  (une lib asyncio type `python-telegram-bot` jurerait avec `db`/`requests` bloquants).
- **Porte ouverte au webhook** plus tard sans réécriture : le dispatch sera une
  fonction pure `traiter_update(conn, update) -> list[actions]` qu'un endpoint FastAPI
  pourra appeler tel quel.

---

## 4. ⚠️ Craintes et pièges identifiés (à ne pas réapprendre à ses dépens)

1. **Un seul process peut poller un token à la fois.** Deux pollers sur le même token
   = erreur **409** et updates volés au hasard entre les deux. → **token de prod ≠
   token de dev** : prévoir `TELEGRAM_BOT_TOKEN_DEV` dans `.env.example` + note.
2. **Le service bot doit être always-on** — pas d'instance PaaS qui s'endort. Sur le
   VPS Hetzner prévu, OK.
3. **Alertes orphelines** : les alertes créées avant l'auth ont `telegram_id NULL`.
   Le bot ne les affiche à **personne** (chaque utilisateur ne voit que
   `telegram_id = le sien`) — sinon elles apparaîtraient chez tout le monde. Elles
   restent gérables depuis le site en local.
4. **Limites d'API Telegram** à respecter dans le rendu :
   - légende d'une photo = **1024 caractères** (message texte = 4096) ;
   - `callback_data` = **64 octets** → format compact (`a:<id>:<page>`), jamais d'uid
     de montre en clair ;
   - ~**30 messages/seconde** global, **1 message/seconde** par chat → paginer, ne pas
     envoyer une photo par annonce.
5. **Fuite de l'edge d'arbitrage** : le bot est public. `bot_ui` ne doit **jamais**
   rendre `prix_detaxe_eur`, `ew_median_eur` ni `spread_eur` — un test dédié vérifie
   qu'aucun de ces champs n'apparaît dans la sortie, pour que personne ne les
   rajoute par inadvertance plus tard.
6. **État de conversation** : en **table DB**, pas en mémoire — sinon un redéploiement
   en plein « envoie-moi tes mots-clés » laisse l'utilisateur bloqué.
7. **Liens morts** : `get_cibles_matches` renvoie le stock connu ; une montre peut
   avoir été vendue depuis. Le push fait déjà une vérif live (`verify_dispo.check`) —
   à l'affichage à la demande, une vérif live de N montres serait trop lente.
   **Décision à prendre** (voir §7).
8. **Portabilité SQLite/PostgreSQL** : tout SQL nouveau passe par `dbengine`
   (`RETURNING id` déjà utilisé pour cette raison, pas de `lastrowid`).

---

## 5. Architecture retenue

```
backend/bot_ui.py    ← LOGIQUE PURE (zéro réseau, zéro DB) — tous les tests ici
                       menu, groupement par réf, pagination, troncature,
                       filtrage admin/user  →  {"text", "keyboard", "photo"}

backend/bot.py       ← RUNTIME MINCE
                       boucle getUpdates (offset persisté)
                       traiter_update(conn, update) -> list[actions]   (décision pure)
                       exécution : sendMessage / sendPhoto / editMessageText /
                                   answerCallbackQuery

backend/telegram.py  ← INCHANGÉ (push). bot.py réutilise envoyer() / _api().
```

**Extensions `db.py` prévues** : `get_cible(conn, id)`,
`set_cible_actif(conn, id, actif, telegram_id)`,
`update_cible(conn, id, mots_cles, libelle, telegram_id)`,
`matches_pour_cible(conn, cible_id)` — `get_cibles_matches` évalue aujourd'hui
**toutes** les alertes d'un coup ; à **factoriser** (pas dupliquer) pour le scoper à
une seule alerte.

**Nouvelle table** : `bot_state(telegram_id PK, etape, data, maj_le)`.

**Déploiement** : troisième service sur la même image Docker →
`python -m backend.bot` (à côté de `web` et `worker`).

**Bonus déjà acquis** : bot et site partagent la table `cibles` avec la même clé
`telegram_id` → une alerte créée dans le bot apparaît sur le site et inversement,
**sans code de synchronisation**.

---

## 6. Avancement

- [x] Contexte du code exploré
- [x] Questions produit tranchées (§3)
- [x] Approche runtime choisie (long polling, §3)
- [x] Section design 1 — architecture et modules **validée**
- [x] Section design 2 — écrans et navigation **validée**
- [x] Section design 3 — données, permissions, tests **validée**
- [x] Spec écrite : `docs/specs/2026-08-17-bot-telegram-interactif.md`
      (convention du projet = `docs/specs/`, **pas** `docs/superpowers/specs/`)
- [x] Spec validée par Hugo (« niquel », 2026-08-17)
- [x] Plan d'implémentation écrit : `docs/superpowers/plans/2026-08-17-bot-telegram-interactif.md`
      (10 tâches TDD ; les plans du projet vivent dans `docs/superpowers/plans/`,
      les specs dans `docs/specs/`)
- [ ] Implémentation (TDD)
- [ ] Déploiement du service `bot`

---

## 7. Questions ouvertes

1. ~~Vérif dispo à l'affichage~~ — **TRANCHÉ 2026-08-17** : pas de vérification live
   (trop lent) ; on affiche la base avec la mention « stock vérifié quotidiennement ».
2. ~~Contenu du push~~ — **TRANCHÉ 2026-08-17** : `telegram.py::_message` sera aligné
   sur le rendu sobre (plus de détaxé ni de marge) **dans le même chantier** (Task 9
   du plan). Bloquant pour le déploiement public.
3. **Volume** — *proposé* : pagination sans plafond dur, références triées par **prix
   croissant**. Écrit tel quel dans la spec ; à contester si ça gêne à l'usage.
4. **Notifications push** : le bot doit-il permettre de couper *toutes* ses
   notifications d'un coup, ou la pause par alerte suffit-elle ? (non bloquant)

---

## 8. Historique des sessions

### 2026-08-16 — Cadrage
Exploration du code existant, 5 questions produit tranchées, approche runtime choisie
(long polling), architecture en 2 modules validée (`bot_ui` pur + `bot` runtime).
Aucun code écrit. Création de ce journal.

**Révision en fin de séance** : abandon de la distinction admin/utilisateur. Le bot
devient **générique pour tous**, avec un rendu **sobre** (état · prix · boutique ·
lien). Un bot perso plus riche pourra être fait plus tard. Conséquences : plus de
filtrage conditionnel dans `bot_ui`, un seul jeu d'écrans, et un test qui interdit
l'apparition des champs marge/détaxé/EveryWatch dans la sortie.

### 2026-08-17 (suite) — Plan d'implémentation
10 tâches TDD dans `docs/superpowers/plans/2026-08-17-bot-telegram-interactif.md` :
(1) tables `bot_state`/`bot_meta` + état de conversation, (2) `get_cible` /
`set_cible_actif` / `update_cible`, (3) `matches_pour_cible` par factorisation de
`get_cibles_matches` **sans enrichissement**, (4) rendu pur des annonces et blocs par
référence, (5) écrans de menu, (6) pagination, (7) `traiter_update` (dispatch pur),
(8) runtime long polling, (9) alignement du push sobre, (10) déploiement + docs.

**Piège attrapé pendant la rédaction du plan** : `watches.images` est stocké en **JSON
sérialisé** (`db.upsert_watch` fait `json.dumps`), pas en liste. Une première version
de `preparer_montres` jetait donc toutes les photos. Corrigé + test dédié
(`test_preparer_montres_accepte_les_images_en_json`).

**Autre point noté** : `matches_pour_cible` ne filtre pas par propriétaire (elle répond
« quelles montres matchent cette alerte »). Le contrôle d'appartenance se fait AVANT,
dans `bot.py`, via `db.get_cible(..., telegram_id=uid)`. Ne jamais l'appeler sans ce
contrôle en amont.

### 2026-08-17 — Spec écrite
Écrans et navigation validés (accueil / mes alertes / fiche alerte / confirmation /
voir les montres / alerte vide), données et permissions validées, plan de tests validé.
Deux points tranchés : pas de vérif dispo live à l'affichage, et **alignement du
message push sur le rendu sobre dans le même chantier** (bloquant pour la mise en
ligne, sinon l'edge fuit par la notification).
Spec écrite dans **`docs/specs/`** — convention du projet, pas `docs/superpowers/specs/`
(qui n'est que le dossier par défaut du skill et ne contient qu'un vieux plan).
Rien n'est commité : le dépôt est laissé tel quel tant que Hugo n'a pas demandé.

**Précision de Hugo en fin de séance** : *aucune* indication EveryWatch ni marge dans
le bot, on laisse ça de côté. Traduit en règle d'architecture : le bot ne lit pas les
tables `ew_prices`/`market_prices` du tout (§8 de la spec), et le test d'interdiction
couvre aussi le message push.

**Deuxième précision** : `Marque Modèle — Référence` doit apparaître **en tête** de
chaque bloc et de chaque notification (« si on a plusieurs alertes on sait direct c'est
laquelle »). Devenu une règle dure : cette ligne de titre n'est jamais sacrifiée à la
troncature, ce sont les annonces qui sont coupées. Le nom de l'alerte figure dans
l'en-tête de page et dans le push.
