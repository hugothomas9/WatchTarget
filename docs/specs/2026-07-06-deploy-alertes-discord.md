# Spec — Déploiement : outil admin + service d'alertes Discord

**Date :** 2026-07-06 · **Statut :** spec à valider (rien codé)

## 1. Vision

Deux produits sur la même base de données :
- **Admin (Hugo)** : l'outil actuel complet — stock, cibles, **Opportunités + pricing
  marché + marges** (l'avantage concurrentiel, jamais exposé).
- **Public (membres Discord)** : ils créent des **alertes** (« préviens-moi quand
  telle montre / tel modèle apparaît dispo full-set au Japon sous tel prix ») et
  sont notifiés sur Discord. Ils ne voient NI les opportunités, NI les prix marché,
  NI les marges.

Bénéfice caché pour Hugo : toutes les alertes sont stockées côté serveur → **radar
de la demande** (quelles réfs sont les plus attendues = ce qui est chaud).

## 2. Rôles : admin vs user

L'admin garde TOUT. Le user est une version **réduite**. Ce qui est RETIRÉ côté user :

| Fonction | Admin | User |
|---|---|---|
| Onglet **Opportunités** (spread, médiane marché, marge nette) | ✅ | ❌ retiré |
| **Prix marché** Chrono24 / WatchCharts / volatilité / liquidité | ✅ | ❌ retiré |
| **Marges** (bénéfice, détaxé, net) | ✅ | ❌ retiré |
| Navigation **stock complet** (5 boutiques, ~milliers) | ✅ | ❌ retiré (ou très limité) |
| **Prix d'achat détaxé** Japon (chiffre calculé) | ✅ | ❌ **non montré** (décision Hugo) |
| « Sous ton prix cible » + **lien boutique** | — | ✅ (il clique pour voir le prix public) |
| Créer / gérer **ses propres alertes** | ✅ | ✅ |
| **Recevoir les notifs** (nouvelle montre matchant son alerte) | ✅ | ✅ |
| Voir les alertes **des autres** / radar demande | ✅ | ❌ |
| Lancer collectes / pricing / config | ✅ | ❌ |

En clair : le user ne voit **que** ses alertes et reçoit ses pings. Il ne « browse »
pas le catalogue et ne voit aucune donnée de prix/marge. Le cœur de valeur (où
acheter, à quelle marge) reste 100% admin.

## 3. Pourquoi un serveur est OBLIGATOIRE

Confirmé : oui, dans tous les cas. Si le user ferme son navigateur, la notification
doit quand même partir → il faut :
- les **alertes stockées côté serveur** (pas dans le navigateur),
- les **scrapers qui tournent en continu côté serveur** (via le proxy),
- l'**envoi des notifs côté serveur** (bot Discord).
Le navigateur du user n'est qu'une interface d'écriture d'alertes ; tout le reste
vit sur le serveur. L'app locale actuelle (Mac + SQLite + launchd) doit donc être
portée sur un serveur hébergé toujours allumé.

## 3bis. Brique bot Discord (réutilisable)

Décision : on construit un **module bot Discord autonome et réutilisable** (Hugo
peu familier de Discord → on encapsule tout dedans). MVP le plus simple :
- **1 serveur Discord à toi** ; les membres le rejoignent via un lien d'invitation
  (1 clic). Un bot ne peut envoyer un DM qu'à un membre avec qui il partage un
  serveur → ce serveur sert de « point d'ancrage ».
- Le bot **envoie les notifs en DM** (privé, simple, adapté à un service payant).
- Interaction : commandes slash (`/alerte add|list|remove`, `/suggerer`) OU une
  page web « Se connecter avec Discord » qui écrit dans la table `alertes`.
- Plus tard (option) : poster aussi dans un **salon** (viralité/preuve sociale), et
  éventuellement rendre le bot **installable sur LES serveurs des membres** (bot
  public multi-serveurs) — plus complexe, phase ultérieure, à décider.

La brique est réutilisable pour tes autres projets (tu utilises déjà des webhooks
Discord pour tes propres alertes). Fichier prévu : `backend/discord_bot.py`.

## 4. Identité Discord-first

Choix retenu : **Discord d'abord**. L'**ID Discord suffit** comme identité ET comme
canal de notification — pas besoin d'email.
- Connexion via **Discord OAuth** (« Se connecter avec Discord ») → on récupère son
  `discord_user_id` + pseudo. C'est son identifiant unique et son adresse de ping.
- On envoie les alertes soit en **DM** (le bot lui écrit en privé), soit dans un
  **salon** dédié du serveur.
- Aucun mot de passe à gérer, aucune donnée email → RGPD allégé (juste l'ID Discord).

Email = optionnel plus tard, pour ouvrir au grand public hors Discord. Pas pour le v1.

## 5. Modèle d'alerte

Une alerte = ce qu'un membre veut acheter. Table `alertes` :

```
alertes(
  id, discord_user_id, discord_username,
  reference     TEXT,     -- réf précise (ex 116610LN) OU vide
  marque        TEXT,     -- ex Rolex (si pas de réf précise)
  famille       TEXT,     -- ex Submariner (filtre modèle)
  prix_max_eur  REAL,     -- ne me prévenir que sous ce prix détaxé
  etat_min      TEXT,     -- full-set déjà garanti par la collecte
  actif         INTEGER,
  created_at, last_notified_at
)
```

**Matching** (à chaque collecte, sur les nouvelles montres dispo full-set) : pour
chaque montre neuve, on cherche les alertes qui matchent (réf normalisée, ou
marque+famille, sous `prix_max_eur`) → on ping le user, une fois par montre (table
anti-doublon comme `notified`). On réutilise `matching.py`, `familles.py`, le prix
détaxé — tout existe déjà.

**Radar demande (admin)** : un écran admin agrège `alertes` → « top 20 des réfs/
modèles les plus demandés », nombre de membres par réf, etc. C'est ton signal
« qu'est-ce qui est chaud ».

## 6. Monétisation (abonnement mensuel)

Objectif Hugo : se faire rémunérer mensuellement si le service aide les membres.
- **Gating** : X alertes gratuites (ex 1-2) puis **abonnement** pour alertes
  illimitées / notifs prioritaires / accès plus tôt.
- **Paiement** : **Stripe** (abonnement récurrent, checkout hébergé, ~1,5%+0,25€
  par transaction, zéro frais fixe). Le webhook Stripe met à jour le statut
  `premium` de l'utilisateur.
- **Crypto (roadmap, gardé en option)** : décision Hugo — possible plus tard, MAIS
  via un **processeur** (Coinbase Commerce / NOWPayments / BTCPay), **jamais un
  wallet brut** (risque de hack/drain qu'il a lui-même relevé). Stripe reste le
  canal principal ; la crypto est un ajout ultérieur pour les membres qui préfèrent.
- Alternative de démarrage : paiement manuel (virement/PayPal) + activation à la
  main — ok pour 5-10 premiers clients, pas scalable.

Modèle simple suggéré : **gratuit = 1 alerte**, **premium ~5-10€/mois = illimité +
priorité**. À affiner selon la valeur perçue (tarif = question ouverte).

## 7. Hébergement — recommandation

Notre stack est déjà **cron + SQLite + scripts + navigateur (curl_cffi/Playwright) +
proxy**. Le plus naturel et le moins cher pour du **toujours-allumé** :

| Option | Prix | Pour nous |
|---|---|---|
| **VPS (Hetzner / DigitalOcean / Contabo)** ⭐ | **4-6 €/mois** | Idéal : on porte launchd→cron/systemd tel quel, SQLite sur disque, contrôle total des deps (curl_cffi, Playwright), proxy facile. Le plus économique en always-on. |
| Railway | usage, ~5-20 $/mo | Très bon DX, déploiement git, mais coût monte avec l'always-on. |
| Fly.io | ~3-10 $/mo | Bon pour always-on + volume persistant, un peu plus technique. |
| Render | free (s'endort ❌) / 7 $+/mo web + disque payant | Pratique mais le plan gratuit s'endort (incompatible avec un bot/scraper permanent) ; le worker + disque persistant payants font grimper. |

**Reco : petit VPS Hetzner (~4,5 €/mois)** — on y met l'app web (admin+user), le bot
Discord, les scrapers (cron), le proxy. Migration quasi directe de l'existant.
Render/Railway possibles si tu préfères le « git push = déployé », mais moins adaptés
à du scraping permanent + Playwright + disque.

Note DB : SQLite tient largement à cette échelle (qq milliers de montres, qq
centaines d'users). Passage à Postgres seulement si ça grossit beaucoup.

## 8. Architecture cible (schéma)

```
[VPS Hetzner]
 ├─ scrapers (cron) ──proxy──> boutiques JP + Chrono24 + WatchCharts   → SQLite
 ├─ moteur d'alertes (après chaque collecte) ──> matching ──> pings Discord
 ├─ bot Discord (OAuth login, /alerte add|list|remove, DM de notif)
 ├─ web app : /admin (tout) + /app (user : ses alertes)   [rôle admin|user]
 └─ Stripe webhook (statut premium)
```

## 9. Légal / éthique (pour un service payant public)

- Stocker `discord_user_id` + ce qu'ils cherchent = données personnelles → **CGU +
  mention de confidentialité** courtes à afficher à l'inscription.
- Utiliser les alertes agrégées pour orienter tes achats = veille concurrentielle,
  OK si mentionné dans les CGU.
- Service payant = tu es un « vendeur » → penser mentions légales / statut (auto-
  entrepreneur) selon les revenus. À voir plus tard, non bloquant pour un MVP.

## 10. Plan par phases

- **Phase 0 — Portage serveur** : déplacer l'existant (scrapers, SQLite, launchd→cron,
  proxy) sur le VPS. L'admin tourne pareil, mais hébergé.
- **Phase 1 — Bot Discord + alertes** : OAuth Discord, table `alertes`, commandes
  `/alerte`, moteur de matching sur collectes, DM de notif. (Discord-only, gratuit.)
- **Phase 2 — Radar demande (admin)** : écran d'agrégation des alertes.
- **Phase 3 — Monétisation** : Stripe, gating premium.
- **Phase 4 (option)** : canal email pour ouvrir hors Discord + rôle user web.

## 11. Questions ouvertes — statut

1. Prix montré au user → **TRANCHÉ** : on NE montre PAS le prix détaxé calculé. La
   notif dit « une montre correspond, **sous ton prix cible**, voici le lien
   boutique » — il clique et voit le prix public de la boutique lui-même. Bon
   compromis : il a le lead, mais pas le deal instantané pré-mâché ni ta marge.
2. DM vs salon → **TRANCHÉ (MVP)** : **DM du bot**. Salon = option viralité plus tard.
3. `/suggerer <ref>` → **retenu en option** ; de toute façon le radar (agrégat des
   alertes) donne déjà le ressenti global automatiquement. Hugo teste d'autres pistes.
4. **RESTE À TRANCHER** : gratuit = combien d'alertes (1 ? 3 ?) et prix premium
   (~5-10€/mois ?). À caler selon la valeur perçue une fois quelques membres testés.
