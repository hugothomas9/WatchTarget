# Infra & proxy — passer le scraping à l'échelle (guide + plan)

> Document de référence, **pas encore implémenté**. À faire quand on décide
> d'industrialiser le pricing Chrono24 (et de blinder la collecte contre les
> throttles). Le système actuel marche sans ça (drip gratuit, plus lent).

## Le problème en une phrase

Chrono24 (via Cloudflare) **bloque notre IP** après ~140 requêtes/jour.
Ce n'est pas un bug : IP fraîche = ça marche (8 réfs → 24 opportunités le 2026-07-04),
IP « chaude » = challenge anti-bot sur toutes les requêtes.

## L'idée reçue à éviter

**Héberger le scraper sur un VPS ne donne PAS « plein d'IP ».** Un serveur =
**une** IP *datacenter*, et Cloudflare classe les IP datacenter comme robot **par
défaut** → bloqué encore plus vite que depuis la box maison. Le VPS sert à
l'hébergement 24/7, jamais à contourner le blocage.

## La vraie solution : proxy résidentiel (loué, pas construit)

Un service de proxy résidentiel route nos requêtes à travers de **vraies IP de
particuliers**, avec **rotation par requête**. Cloudflare les voit comme humaines.
On ne construit rien : on loue un accès, on pointe le scraper sur la passerelle.

**Réutilisable sur TOUS les projets de scrap** (montres JP, alternance, futurs) :
un seul abonnement, une variable d'env, tous les scrapers en profitent.

### Setup « industriel » complet (optionnel)
`petit VPS toujours allumé (héberge les jobs 24/7) + proxy résidentiel (IP rotatives)`.
Tant que le Mac reste allumé, le VPS n'est pas nécessaire — le proxy suffit.

## Coûts 2026 (vérifiés)

Facturation **au Go de trafic**, 3 tiers :

| Tier | Providers | Prix / Go |
|---|---|---|
| Budget | IPRoyal, DataImpulse, Webshare | 1,75–4 $ (DataImpulse ~1 $ en PAYG) |
| Milieu | Decodo/Smartproxy, SOAX, NetNut | 3–6 $ |
| Premium | Bright Data, Oxylabs | 8–12 $ |

**Notre coût réel = minuscule.** On price ~460 réfs, rafraîchies 1×/mois. En
**bloquant les images** (on ne veut que le texte des prix), ~1 Mo/page →
**~0,5–1 Go/mois → ~3–7 €/mois**. Recommandé : **IPRoyal ou DataImpulse en
pay-as-you-go**.

> Métrique clé : ce qui compte c'est le *taux de succès Cloudflare*, pas le prix
> brut. Un proxy à 1,50 $/Go qui passe 60% du temps coûte plus cher *par donnée
> valide* qu'un à 1,90 $/Go qui passe 99%. Pour Chrono24, viser un pool « clean ».

## Plan d'implémentation (quand on décide)

1. **Config env** — `backend/config.py` lit `PROXY_URL` (ex.
   `http://user:pass@gateway:port`) depuis l'environnement / un `.env`. Vide =
   comportement actuel (direct).
2. **http_client** — passer `proxies={"http": PROXY_URL, "https": PROXY_URL}` à
   `requests` quand `PROXY_URL` est défini.
3. **Playwright (market.py)** — `browser.new_context(proxy={"server": ...,
   "username": ..., "password": ...})`.
4. **Bloquer les images/médias** (Playwright `route`) → coupe ~80% de la bande
   passante = du coût. À faire **même sans proxy** (accélère le scan).
5. **Remonter les cadences** une fois le proxy en place : `MARKET_DELAY` peut
   redescendre à ~2 s, `max_workers` du market monter, `--limit` nocturne à 400+.
6. **Rotation de session** : la plupart des providers rotent par requête via la
   passerelle ; sinon, recycler le contexte Playwright plus souvent.

### Activation (côté Hugo, ~5 min)
1. Créer un compte (IPRoyal/DataImpulse), acheter quelques Go en PAYG.
2. Copier l'URL de passerelle proxy fournie.
3. La coller dans `scrap-montres/.env` → `PROXY_URL=...`.
4. Relancer : tout (pricing + collecte) passe par les IP rotatives.

## Sécurité / bon sens
- Usage légitime : données d'annonces publiques, recherche d'arbitrage perso.
- Garder les délais polis même avec proxy (ne pas marteler un site donné).
- Ne jamais committer le `.env` (mettre `.env` dans `.gitignore` le jour du git).

## Sources
- aimultiple.com/proxy-pricing (pricing 2026)
- humanbrowser.cloud/blog/best-residential-proxy-scraping-2026
- torchproxies.com/datacenter-vs-residential-proxies-2026
