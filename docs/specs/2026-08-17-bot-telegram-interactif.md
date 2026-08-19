# Bot Telegram interactif — SPEC (à valider avant de coder)

> Statut : **spec écrite, en attente de validation.** Journal de bord tenu à jour :
> `docs/JOURNAL-BOT-TELEGRAM.md` (décisions, craintes, avancement).
> Date : 2026-08-17.

## 1. Objectif

Le bot Telegram actuel (`backend/telegram.py`) ne fait que **pousser** des messages.
Cette spec ajoute un **bot interactif** : menu d'accueil, création d'alerte, gestion
des alertes, et consultation des montres de la base qui correspondent à une alerte.

Périmètre : **un bot générique, identique pour tous les utilisateurs**. Pas de rôle
admin, pas de vue privilégiée (un bot personnel plus riche pourra être fait plus tard,
hors de cette spec).

## 2. Ce qui existe déjà et qu'on réutilise

| Brique | Rôle dans le bot |
|---|---|
| `backend/cibles.py` | Moteur de mots-clés multilingue (`blob_recherche`, `matche`) — **inchangé** |
| `backend/db.py` — table `cibles` | Alertes, déjà rattachées à un `telegram_id`, avec `actif` et `libelle` |
| `backend/db.py` — table `users` | `upsert_user` / `get_user` |
| `backend/telegram.py` | `_api()` et `envoyer()` réutilisés par le runtime — **inchangé sauf §8** |
| `backend/dbengine.py` | Portabilité SQLite (local) / PostgreSQL (prod) |
| `Dockerfile` | Image unique à commande surchargeable (`web`, `worker`, désormais `bot`) |

**Bénéfice acquis sans code** : le site (Login Widget Telegram) et le bot écrivent dans
la **même table `cibles` avec la même clé `telegram_id`**. Une alerte créée dans le bot
apparaît sur le site et inversement, sans synchronisation.

## 3. Décisions produit

1. **Création d'alerte = texte libre en une étape.** Le bot demande les mots-clés,
   l'utilisateur répond en un message (« rolex daytona 126506A »). Pas de wizard.
2. **Affichage groupé par référence** : pour chaque référence, une photo puis ses
   annonces en lignes. Pagination par blocs de références.
3. **Contenu sobre d'une annonce** : `état · prix boutique en € · boutique · lien`.
   **Aucune donnée EveryWatch, aucune marge, aucun prix détaxé** — nulle part dans le
   bot, ni à l'affichage ni dans les notifications. L'edge d'arbitrage reste sur le
   site (protégé par le login). Le bot ne **charge même pas** ces données : voir §8.
4. **Cinq actions** sur une alerte : voir les montres, renommer, modifier les
   mots-clés, activer/désactiver (pause), supprimer (avec confirmation).
5. **Pas de vérification de dispo en direct** à l'ouverture d'une alerte (N requêtes
   HTTP = trop lent). On affiche l'état de la base, avec la mention « stock vérifié
   quotidiennement ».
6. **Pagination sans plafond dur**, références triées par **prix croissant**.

## 4. Runtime : long polling (et pourquoi pas un webhook)

`python -m backend.bot` — process séparé qui boucle sur `getUpdates`.

- Pas d'URL publique, pas de certificat, pas de `setWebhook` à re-pointer à chaque
  déploiement.
- Fonctionne **en local comme en prod** (le développement se fait en local).
- Zéro nouvelle dépendance : `requests` est déjà là ; le repo est 100 % synchrone
  (une bibliothèque asyncio jurerait avec `db` et `requests` bloquants).
- **Migration webhook possible sans réécriture** : le dispatch est une fonction pure
  `traiter_update(conn, update) -> list[actions]`, appelable depuis un endpoint FastAPI.

⚠️ **Un seul process peut poller un token à la fois** (sinon erreur 409 et updates volés
au hasard). → `TELEGRAM_BOT_TOKEN_DEV` dans `.env.example` : token de dev ≠ token de prod.
⚠️ Le service bot doit être **always-on** (pas d'instance qui s'endort).

## 5. Architecture

```
backend/bot_ui.py    LOGIQUE PURE — zéro réseau, zéro DB. Tous les tests sont ici.
                     Entrée : données déjà lues (alertes, montres) + page demandée.
                     Sortie : {"text": str, "keyboard": [[...]], "photo": url|None}
                     Contient : menu, groupement par référence, pagination,
                     troncature aux limites Telegram, formatage des prix.

backend/bot.py       RUNTIME MINCE
                     - boucle getUpdates (offset persisté en base)
                     - traiter_update(conn, update) -> list[actions]  (décision pure :
                       lit la DB, ne fait aucun envoi)
                     - exécution des actions : sendMessage / sendPhoto /
                       editMessageText / answerCallbackQuery

backend/telegram.py  INCHANGÉ (push). bot.py réutilise _api() et envoyer().
```

## 6. Écrans

Règle de navigation : les **menus s'éditent sur place** (`editMessageText`) pour ne pas
polluer le fil ; la **liste des montres arrive en nouveaux messages** (une photo ne
s'édite pas proprement en texte).

```
ACCUEIL  (/start, ou « ◀ Menu »)
  👋 WatchTarget — veille montres Japon
  Crée une alerte, reçois un message dès qu'une montre correspondante
  arrive en boutique.
  [ 🔔 Créer une alerte ]
  [ 📋 Mes alertes (3) ]      [ ❓ Aide ]

MES ALERTES
  [ 🟢 Ma Daytona — 12 montres ]
  [ 🟢 speedmaster 3861 — 3 montres ]
  [ ⏸ rolex submariner — 41 montres ]
  [ 🔔 Créer une alerte ]     [ ◀ Menu ]

FICHE ALERTE
  🟢 Ma Daytona · rolex daytona
  12 montres · 4 références · créée le 16/08
  [ 👁 Voir les montres (12) ]
  [ ✏️ Renommer ]  [ 🔤 Mots-clés ]
  [ ⏸ Mettre en pause ]  [ 🗑 Supprimer ]
  [ ◀ Mes alertes ]

CONFIRMATION SUPPRESSION
  Supprimer l'alerte « Ma Daytona » ? Cette action est définitive.
  [ ✅ Oui, supprimer ]   [ ❌ Annuler ]

VOIR LES MONTRES
  🎯 Ma Daytona — 12 annonces · 4 réfs · page 1/2
  (stock vérifié quotidiennement)

  [PHOTO] Rolex Daytona — 126500LN
          • Occasion A · 20 900 € · Jack Road → Voir
          • Neuf · 22 400 € · Kame-Kichi     → Voir

  [PHOTO] Rolex Daytona — 116500LN
          • …

  [ ◀ Préc ]  [ Suivant ▶ ]  [ ◀ Retour à l'alerte ]

ALERTE VIDE
  Aucune montre en stock ne correspond à « Ma Daytona » pour l'instant.
  Tu recevras un message dès qu'une arrive.
  [ ◀ Retour à l'alerte ]
```

**Ligne de titre obligatoire** : chaque bloc s'ouvre sur `Marque Modèle — Référence`
(ex. `Rolex Daytona — 126500LN`). Elle est **prioritaire sur tout le reste** : si la
légende dépasse 1024 caractères, ce sont les annonces qui passent en « …et N autres »,
jamais le titre. Référence absente → `Marque Modèle` seul. L'en-tête de page rappelle
en plus le nom de l'alerte, pour qu'un utilisateur ayant plusieurs alertes sache
immédiatement laquelle il consulte.

**Prix affiché** = `prix_ttc` (en yens) converti en € via `backend/fx.py` = le prix payé
en vitrine, arrondi à l'euro. **En euros uniquement** (le yen mangerait la place de la
légende). Prix absent en base → la ligne affiche « prix sur demande ».

**Conversations** (création, renommage, modification des mots-clés) : le bot pose la
question, écrit l'étape dans `bot_state`, et le **prochain message texte** de cet
utilisateur est consommé comme réponse. Un message texte reçu **hors conversation**
renvoie l'accueil.

## 7. Contraintes d'API Telegram encodées dans le rendu

| Limite | Traitement |
|---|---|
| Légende d'une photo = **1024 caractères** | 3 références par page, 8 annonces par référence puis « …et N autres » |
| Message texte = 4096 caractères | En-tête et menus largement en dessous |
| `callback_data` = **64 octets** | Format compact : `v:<id_alerte>:<page>`, `a:<id>`, `a:<id>:del`. Jamais d'uid de montre en clair |
| ~30 msg/s global, **1 msg/s par chat** | Une photo par référence (pas par annonce) + pagination |

## 8. Modèle de données

**Nouvelle table** (portable SQLite/PostgreSQL via `dbengine`) :

```sql
CREATE TABLE IF NOT EXISTS bot_state (
    telegram_id  BIGINT PRIMARY KEY,
    etape        TEXT,        -- 'attente_mots_cles' | 'attente_libelle' | ...
    data         TEXT,        -- JSON (ex. {"cible_id": 12})
    maj_le       TEXT
);
```

État **en base et non en mémoire** : un redéploiement en plein « envoie-moi tes
mots-clés » ne doit pas laisser l'utilisateur bloqué. L'offset `getUpdates` est
persisté de la même façon (clé dédiée), pour ne pas rejouer les updates au redémarrage.

**Nouvelles fonctions `db.py`** :

- `get_cible(conn, cible_id)`
- `set_cible_actif(conn, cible_id, actif, telegram_id)`
- `update_cible(conn, cible_id, mots_cles=None, libelle=None, telegram_id=…)`
- `matches_pour_cible(conn, cible_id)` — **factorisation** de `get_cibles_matches`
  (qui évalue aujourd'hui toutes les alertes d'un bloc), pas une copie.
  **Sans enrichissement** : `get_cibles_matches` charge `ew_prices` + `market_prices`
  et passe chaque montre dans `_enrich_watch` ; la version du bot renvoie les lignes
  brutes de `watches`. Plus rapide, et une donnée jamais chargée ne peut pas fuiter.
  La factorisation isole donc l'étape « quelles montres matchent cette alerte » ;
  l'enrichissement reste au-dessus, réservé au site.

Toutes prennent le `telegram_id` du propriétaire et ne modifient que ses lignes.

**À la première interaction**, `upsert_user` enregistre l'utilisateur : le bot devient
un second chemin d'inscription, à parité avec le Login Widget du site.

## 9. Permissions

Chaque utilisateur ne voit **que** `telegram_id = le sien` — le `from.id` de l'update.
Aucun appel DB du bot n'utilise `"__all__"`. Conséquences :

- Les **alertes orphelines** (`telegram_id NULL`, créées avant l'authentification)
  n'apparaissent chez personne dans le bot ; elles restent gérables depuis le site en
  local.
- Aucune variable d'environnement ne décide qui voit quoi → rien à mal configurer au
  déploiement.

**Alignement du push (à faire dans le même chantier)** : `telegram.py::_message`
affiche encore prix détaxé et prix vendu EveryWatch + marge. Le bot étant public, ce
message adopte le **même rendu sobre**, dans cet ordre :

```
🎯 Rolex Daytona — 126500LN
Occasion A · 20 900 € · Jack Road
Alerte : Ma Daytona
<lien>
```

Marque/modèle/référence **en premier**, puis l'annonce, puis le nom de l'alerte qui a
déclenché le message — c'est ce qui permet de s'y retrouver quand plusieurs alertes
tournent en parallèle. Sans ce changement, l'edge fuit par la notification et le
déploiement public est bloqué.

## 10. Tests (tous sans réseau)

**`bot_ui` (pur, l'essentiel du travail)**
- rendu de chaque écran : accueil, liste d'alertes, fiche, confirmation, alerte vide ;
- groupement par référence et tri par prix croissant ;
- bornes : 0 montre, 1 référence, 200 références, annonce sans photo, prix manquant ;
- troncature : légende ≤ 1024 caractères, « …et N autres » correct, et **la ligne de
  titre `Marque Modèle — Réf` survit toujours** (cas limite : une réf avec 40 annonces) ;
- le nom de l'alerte apparaît dans l'en-tête de page et dans le message push ;
- longueur de chaque `callback_data` ≤ 64 octets ;
- **test d'interdiction** : aucune sortie ne contient `prix_detaxe_eur`,
  `ew_median_eur`, `ew_n_sales` ni `spread_eur` — même en leur donnant en entrée une
  montre qui porte ces champs. Barrière explicite contre une régression future.
  Le même test couvre le message push de `telegram.py`.

**`traiter_update` (décision pure, DB de test)**
- clic sur chaque bouton → actions attendues ;
- message texte pendant une étape de conversation → alerte créée / renommée ;
- message texte hors conversation → accueil ;
- un utilisateur ne peut pas ouvrir ni supprimer l'alerte d'un autre (callback forgé).

**`db`** : les 4 nouvelles fonctions, sur les deux moteurs, comme le reste du repo.

## 11. Déploiement

- Troisième service sur l'image Docker existante, commande `python -m backend.bot`
  (à côté de `web` = uvicorn et `worker` = `python -m backend.worker`).
- `.env.example` : `TELEGRAM_BOT_TOKEN_DEV` + note « un seul poller par token ».
- `@BotFather` : `/setcommands` pour `/start` et `/aide`.
- En local, lancer le bot avec le token de dev pendant que la prod tourne.

## 12. Hors périmètre

- Bot personnel enrichi (marges, opportunités, favoris) — plus tard si besoin.
- Webhook (le design le permet sans réécriture, mais on ne le fait pas maintenant).
- Recherche libre dans le stock depuis le bot (le bot ne sert que les alertes).
- Paiement / accès premium (voir `docs/specs/deploiement-multiutilisateurs.md`).
