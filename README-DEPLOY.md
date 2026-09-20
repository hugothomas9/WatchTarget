# Déploiement — guide pas-à-pas (Neon + Render + GitHub Actions, gratuit)

Objectif : les 3 briques du projet sur des offres **gratuites**, sans que ton Mac
soit allumé.

| Brique | Où | Offre |
|---|---|---|
| Base PostgreSQL | **Neon** | 0,5 Go, ne s'endort jamais |
| Web (FastAPI + front React) **et bot Telegram** | **Render** | service web gratuit |
| Worker (scrapers, 1×/jour) | **GitHub Actions** | gratuit, illimité sur repo public |

> Historique : le projet tournait sur Railway (web + Postgres + worker + bot).
> L'essai Railway a expiré (tout est en pause), d'où cette bascule. Les concepts
> sont les mêmes ; si tu repasses un jour sur un PaaS payant, le `Dockerfile` et
> `backend/worker.py` n'ont pas bougé.

**Les deux différences de fond avec Railway :**

1. **Le service web s'endort** après 15 min sans visite et met ~1 min à se
   réveiller à la visite suivante. Normal sur une offre gratuite.
2. **Le bot n'a plus de service à lui.** Le long polling suppose un process
   allumé 24 h/24 ; à la place, le bot passe en **webhook** : Telegram appelle
   `POST /api/telegram/webhook` sur le service web, ce qui le réveille au
   passage. Aucune logique métier ne change (même `bot.executer_update`).

---

## Étape 1 — La base : Neon

1. [neon.tech](https://neon.tech) → *Sign up with GitHub* → *Create project*
   (région **Europe / Frankfurt**, proche de Render).
2. *Connection string* → choisir l'onglet **Pooled connection** et copier l'URL
   (elle contient `-pooler`). Elle ressemble à :
   `postgresql://user:pass@ep-xxx-pooler.eu-central-1.aws.neon.tech/neondb?sslmode=require`

   ⚠️ Prends bien la version **pooled** : le service web redémarre à chaque
   réveil et épuiserait sinon les connexions directes autorisées.
3. Garde cette URL sous la main : c'est le `DATABASE_URL` des étapes 2 et 3.

### Charger tes données
Depuis ton Mac, une fois :
```bash
DATABASE_URL="postgresql://...neon.tech/neondb?sslmode=require" \
  python -m scripts.migrate_sqlite_to_pg data/montres.db
```
Ça transfère les montres, prix, favoris et alertes de ta base locale vers Neon.

> Les données accumulées dans le Postgres **Railway** ne sont plus accessibles
> tant que le projet est en pause. Si tu y tiens, il faut réactiver Railway le
> temps d'un `pg_dump` — sinon on repart de la base locale.

---

## Étape 2 — Le web (+ le bot) : Render

1. [render.com](https://render.com) → *Sign up with GitHub*.
2. *New* → *Blueprint* → choisir le repo `WatchTarget`. Render lit `render.yaml`
   et crée le service web à partir du `Dockerfile` (front React buildé inclus).
3. Il demande les variables marquées `sync: false` :

   | Clé | Valeur |
   |---|---|
   | `DATABASE_URL` | l'URL Neon *pooled* de l'étape 1 |
   | `TELEGRAM_BOT_TOKEN` | ton token @BotFather |
   | `TELEGRAM_CHAT_ID` | ton id perso (via @userinfobot) — droits admin |
   | `TELEGRAM_WEBHOOK_SECRET` | `openssl rand -hex 32` → garde-le, il resservira |
   | `PROXY_URL` | ton proxy Chrono24, ou vide |

4. Premier déploiement (~5 min) → tu obtiens `https://watchtarget.onrender.com`.
5. Chez **@BotFather** → `/setdomain` → ce domaine (sinon le bouton
   « Connexion Telegram » du site ne s'affiche pas).

---

## Étape 3 — Brancher le bot en webhook

Une fois le service en ligne, depuis ton Mac :
```bash
TELEGRAM_BOT_TOKEN="123456:AA..." TELEGRAM_WEBHOOK_SECRET="<le même qu'à l'étape 2>" \
  python -m scripts.set_webhook https://watchtarget.onrender.com
```
→ `webhook déclaré : https://watchtarget.onrender.com/api/telegram/webhook`

Vérification : envoyer `/start` au bot, le menu doit s'afficher (compte quelques
secondes de plus si le service dormait).

**Pour revenir au long polling** (développement local) :
```bash
python -m scripts.set_webhook --delete   # puis : python -m backend.bot
```
⚠️ Les deux modes sont exclusifs : tant qu'un webhook est déclaré, `getUpdates`
répond 409.

---

## Étape 4 — Le worker : GitHub Actions

Le fichier `.github/workflows/worker.yml` est déjà dans le repo : une passe
complète (collecte + tri des vendues + pricing EveryWatch) chaque nuit à 01:00
UTC, plus un bouton pour la lancer à la main.

1. Repo GitHub → *Settings* → *Secrets and variables* → *Actions* → *New
   repository secret*, pour chacun :
   `DATABASE_URL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `PROXY_URL`.
2. Onglet *Actions* → workflow **worker** → *Run workflow* pour tester tout de
   suite. Les logs affichent `[worker] collecte : N nouvelles / M vues`.

À surveiller :
- Le `schedule` est **désactivé après 60 jours sans commit** sur le repo (mail
  d'avertissement de GitHub). Un commit, ou un clic de réactivation, relance.
- Les runners GitHub sortent par des IP de datacenter, plus facilement bloquées
  par les boutiques que ta connexion perso. Collecte qui revient vide = première
  piste à creuser (remède : renseigner `PROXY_URL`).

---

## Vérifier que tout est en place
- [ ] Ouvrir le domaine Render → le site s'affiche (1ère visite lente si le
      service dormait), le bouton **Connexion Telegram** apparaît.
- [ ] Se connecter → créer une alerte → elle est à ton nom.
- [ ] `/start` au bot → le menu répond ; l'alerte créée sur le site apparaît
      dans « Mes alertes ».
- [ ] Workflow **worker** lancé à la main → vert, et de nouvelles montres en base.

## Limites connues de cette pile gratuite
- **Réveil lent** : première visite après 15 min d'inactivité = ~1 min d'attente.
  Le bot aussi (Telegram réessaie si le réveil dépasse son délai).
- **Neon, 0,5 Go** : largement suffisant pour ~6 400 montres et leur historique,
  à surveiller si le stock grossit beaucoup.
- **Pas de scraping à la demande fiable** : `/api/collecte` reste admin, mais le
  service peut être coupé en cours de route par la mise en veille. Les passes
  longues doivent passer par GitHub Actions.
