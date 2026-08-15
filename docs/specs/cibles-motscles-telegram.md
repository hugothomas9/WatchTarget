# Cibles par mots-clés + alertes Telegram — PLAN (non implémenté)

> Statut : **préparé, pas encore codé.** Ce doc est le plan validé avant implémentation.

## Objectif
Permettre à n'importe qui de créer une **alerte par mots-clés** (ex « rolex daytona
126506A »). Dès qu'une montre collectée contient **tous** les mots-clés, elle :
1. apparaît dans l'onglet **Cibles**,
2. déclenche une **alerte Telegram** (une seule fois par cible).

## 1. Matching multilingue (le cœur)
Pour chaque montre, on construit un **texte de recherche** normalisé :
```
blob = marque + famille + traduire_nom(modele) + modele_original + reference + description
```
(tout en minuscules, réf normalisée sans espaces). On réutilise donc `familles.py`
(Daytona ↔ デイトナ) et `noms.py` (traduction) : « daytona » matche une デイトナ.

Une cible = une liste de mots-clés. **Match = TOUS les mots-clés présents dans le blob.**
- « 126506A » (réf) : normalisée, matche la référence.
- « rolex » : matche la marque.
- « daytona » : matche la famille/nom traduit.

Fichier concerné : nouveau `backend/cibles.py` → `blob_recherche(watch)` + `matche(cible, blob)`.

## 2. Stockage : table `cibles` (CRUD par l'utilisateur)
```sql
CREATE TABLE cibles (
  id         INTEGER PRIMARY KEY,
  mots_cles  TEXT NOT NULL,     -- « rolex daytona 126506A » (espace = ET)
  libelle    TEXT,              -- nom lisible optionnel
  actif      INTEGER DEFAULT 1,
  cree_le    TEXT
);
```
`targets.json` (tes cibles historiques avec fourchette de revente) reste en place et
cohabite ; les cibles mots-clés sont un second mécanisme.

## 3. Où le matching s'exécute
- **Vue Cibles (à la demande)** : `GET /api/cibles` = montres dispo dont le blob matche
  au moins une cible active, enrichies comme les opportunités (prix vendu EW + marge).
  → matching en Python au moment de la requête (souple, gère le multi-match, pas de
  colonne à maintenir sur `watches`).
- **Alerte à la collecte** : à la fin de `pipeline.run`, pour chaque montre NOUVELLE
  qui matche une cible et pas encore notifiée → push Telegram + marque `notified`.

Table `notified` : étendre la clé à `(uid, "cible:" + id)` pour une alerte par cible.

## 4. Alertes Telegram
Nouveau `backend/telegram.py` (ou extension de `notify.py`) :
```
POST https://api.telegram.org/bot<TOKEN>/sendMessage
     { chat_id: <CHAT_ID>, text: "<montre + prix EW + marge + lien>", parse_mode: "HTML" }
```
Config `.env` :
```
TELEGRAM_BOT_TOKEN=123456:ABC-...
TELEGRAM_CHAT_ID=987654321      # ou un id de groupe/canal
```
Sans token → no-op silencieux (comme Discord aujourd'hui).

## 5. UI (onglet Cibles)
- Formulaire : champ « mots-clés » + bouton **Ajouter une alerte** (POST /api/cibles).
- Liste des alertes actives avec suppression (DELETE /api/cibles/{id}).
- Le tableau des montres matchées réutilise `OppRow` (mêmes colonnes que les opportunités).

## 6. Découpage d'implémentation (quand on lancera)
1. `backend/cibles.py` : blob + match + tests (multilingue : « daytona » matche デイトナ).
2. Table `cibles` + CRUD `db.py` + endpoints `api.py`.
3. `GET /api/cibles` : montres matchées enrichies (réutilise `_enrich_watch`).
4. `backend/telegram.py` : envoi + anti-doublon, branché en fin de `pipeline.run`.
5. Front : formulaire + liste des alertes dans l'onglet Cibles.
6. Tests bout-en-bout.

---

## ⚙️ PRÉREQUIS À FAIRE PAR HUGO (pour l'implémentation)
Créer le bot Telegram et récupérer 2 valeurs :

1. Dans Telegram, ouvre **@BotFather** → `/newbot` → choisis un nom + un @username
   → il te donne le **TOKEN** (`123456:ABC-...`).
2. Récupère ton **CHAT_ID** :
   - écris un message à ton bot (n'importe quoi),
   - ouvre `https://api.telegram.org/bot<TON_TOKEN>/getUpdates` dans le navigateur,
   - copie le `chat.id` qui apparaît.
   *(ou pour un groupe : ajoute le bot au groupe, envoie un message, même méthode.)*
3. Donne-moi TOKEN + CHAT_ID (ou mets-les dans `.env`) → je branche l'envoi.

*(Rien d'autre : pas de SMTP, pas de serveur mail, pas d'abonnement.)*
