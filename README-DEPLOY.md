# Déploiement — guide pas-à-pas (Railway)

Objectif : 3 briques sur Railway → **web** (FastAPI + front), **PostgreSQL managé**,
**worker cron** (scrapers). Ton Mac ne sera plus nécessaire.

> Railway = le plus simple pour démarrer. Les mêmes concepts marchent sur Render/Fly.

---

## Étape 0 — Mettre le code sur GitHub (une fois)
Depuis le dossier du projet, sur ton Mac (je te donnerai les commandes exactes) :
```
git init && git add -A && git commit -m "deploy"
# crée un repo vide sur github.com, puis :
git remote add origin https://github.com/<toi>/scrap-montres.git
git push -u origin main
```

## Étape 3 — Créer le projet + la base
1. Va sur **railway.app** → *New Project* → *Deploy from GitHub repo* → choisis `scrap-montres`.
   Railway détecte le `Dockerfile` et build le **service web** automatiquement.
2. Dans le projet → *New* → *Database* → **Add PostgreSQL**. (C'est ta base externe, managée.)

## Étape 4 — Variables d'environnement (service web)
Ouvre le service **web** → onglet *Variables* → ajoute :
| Clé | Valeur |
|---|---|
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` (référence la base Railway) |
| `TELEGRAM_BOT_TOKEN` | ton token @BotFather |
| `TELEGRAM_CHAT_ID` | ton id admin (via @userinfobot) |
| `PROXY_URL` | (optionnel) ton proxy Chrono24 |
Railway fournit `PORT` tout seul — ne pas y toucher.

## Étape 5 — Déclarer le domaine au bot
1. Service web → *Settings* → *Networking* → *Generate Domain* → tu obtiens
   `https://scrap-montres-production.up.railway.app` (exemple).
2. Dans Telegram, **@BotFather** → `/setdomain` → choisis ton bot → colle ce domaine.
   (Sans ça, le bouton « Connexion Telegram » du site ne s'affiche pas.)

## Étape 6 — Charger tes données existantes (migration, une fois)
Depuis ton Mac, avec l'URL Postgres de prod (Railway → Postgres → *Connect* → copie
l'URL publique) :
```
DATABASE_URL="postgresql://...railway..." \
  /opt/anaconda3/bin/python3 -m scripts.migrate_sqlite_to_pg data/montres.db
```
Ça transfère tes ~6 400 montres + prix + favoris + alertes vers la base cloud.

## Étape 7 — Le worker (scrapers automatiques)
Dans le projet Railway → *New* → *Empty Service* (ou duplique le repo) :
- **Start command** : `python -m backend.worker`
- Mêmes variables d'env que le web (surtout `DATABASE_URL`, `TELEGRAM_*`, `PROXY_URL`).
- Onglet *Settings* → *Cron Schedule* : `0 3 * * *` (tous les jours 3 h) ou
  `0 3,15 * * *` (2×/jour). Railway lance alors `backend.worker` à l'heure dite.

## Service `bot` (bot Telegram interactif)

Même image Docker que `web` et `worker`, commande surchargée :

    python -m backend.bot

- **Doit être always-on** (long polling) — pas d'instance qui s'endort.
- **Exactement une instance** : deux pollers sur le même token = erreur 409.
- Variables nécessaires : `TELEGRAM_BOT_TOKEN`, `DATABASE_URL`.
- Chez @BotFather : `/setcommands` →
      start - Menu principal
      aide - Comment ça marche
- Chez @BotFather : `/setjoingroups` → **Disable**. Le bot est PUBLIC et affiche des
  données privées par utilisateur (alertes, stock) dans le chat où on lui parle ;
  l'empêcher de rejoindre des groupes évite qu'un écran destiné à une personne
  s'affiche pour tout un groupe.
- Vérification après déploiement : envoyer `/start` au bot → le menu doit s'afficher.

---

## Vérifier
- Ouvre le domaine → l'appli s'affiche, le bouton **Connexion Telegram** apparaît.
- Connecte-toi → crée une alerte → elle est **à ton nom**, tu reçois les notifs.
- Le worker tourne à l'heure prévue → nouveaux arrivages + alertes automatiques.

## Notes
- Image **légère** (`requirements-deploy.txt`) : le matching-image (torch) est exclu →
  le pricing EveryWatch retombe sur l'agrégat (précision ±10 %, sans crash). Pour la
  précision variante-par-photo, ajouter torch/open_clip au worker plus tard.
- Coût de départ : ~5–10 €/mois (web + Postgres + worker) sur Railway.
- Secrets : jamais commités (`.env` est dans `.gitignore`/`.dockerignore`), injectés
  par Railway.
