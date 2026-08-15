# EveryWatch comme source de prix — spike de faisabilité (2026-07-06)

## ★★ CRACKÉ — recette gratuite complète (2026-07-06 soir) ★★
**Prix RÉELLEMENT VENDUS récupérables gratuitement, sans compte, sans token, en EUR.**
Validé : 126610LN → 49 ventes réelles, médiane 13 699€ (P25 12 912 / P75 14 889).

Recette (curl_cffi impersonate safari17_0, headers `x-fe-webdriver: false`,
`Referer/Origin: https://everywatch.com`) :

1. **Résoudre réf → referenceNumberId** (GraphQL public, PAS de token) :
   `GET https://api.everywatch.com/api/GraphQL?queryName=SearchResults&variables={"query":"126610LN","page":1,"size":10}`
   → `data.data.data.searchResults.variants[i].referenceNumberId` (ex 149975) + `count`.
   (⚠️ c'est `{query,page,size}`, pas `searchTerm`.)

2. **Récupérer les ventes réelles** (rendu HTML côté Next, PAS de token) :
   `GET https://everywatch.com/api/listing/getListingData?variables={"filterData":{"referenceNumber":["149975"]},"auctionType":"result","pageNumber":1,"pageSize":50}`
   → HTML. (⚠️ referenceNumberId en **string dans un array** ; `filterData` imbriqué ;
   sinon 400/500. Charger d'abord `GET everywatch.com/` pour semer les cookies.)

3. **Parser** chaque carte `[data-prices]` → JSON `{"netPayableUsd":...,"netPayableEur":13835.17,...}`
   (prix DÉJÀ en EUR, pas de conversion). Statut « Sold », date « Jul, 2026 », source
   (Dealer/maison), pays dans le texte de la carte (`a[title]`). Médiane/P25/P75 des netPayableEur.

Ce qui reste payant/inaccessible (on s'en passe) : `/Event/GetAuctionResults_v2` (400 sans
token abonné), `GetSearchAnalysis` (médian/histogramme calculés). On recalcule nous-mêmes
la médiane depuis les ventes brutes de l'étape 2 → même résultat, gratuit.

**Reste à coder** : `backend/market_everywatch.py` (`EveryWatchSource.stats(ref)` : étapes
1-3 → médiane/P25/P75/n_ventes/date_derniere EUR), colonnes `ew_*` dans market_prices +
migration, `enrich_everywatch()` dans market_scan (TTL, progressif), `get_opportunities`
utilise le prix vendu réel EveryWatch comme référence (Chrono24 en secours), colonne front
« Vendu réel (EveryWatch) ». La liquidité reste WatchCharts.

---

## Verdict court (spike initial)
EveryWatch = **la meilleure donnée de prix** pour nous (prix RÉELLEMENT payés :
résultats d'enchères + ventes dealers), là où Chrono24 = prix *demandés* et
WatchCharts = prix *paywallé*. **Pas de Cloudflare** (curl_cffi safari passe).
MAIS l'intégration automatisée est **lourde** (session + flux SPA) → différée.
On garde Chrono24 (prix) + WatchCharts (liquidité) en attendant.

## Ce qui est confirmé (utile pour reprendre vite)
- **API** : `https://api.everywatch.com/api` — atteignable via `curl_cffi` (safari17_0).
  `bb-check` → 204 (anti-bot franchi sans peine).
- **Front** : Next.js (buildId visible), données hydratées côté client via RTK Query
  (les pages réf sont un shell SPA ~7 Ko, aucune donnée en SSR).
- **Endpoints repérés dans les chunks** :
  - `/Event/GetAuctionResults_v2` — **résultats d'enchères** (la donnée cible : prix
    vendu + date + maison). `params: {variables: JSON.stringify(<obj>)}`, method GET.
  - `/AuctionHouse/MarketPlaceListing` (GET) — listings dealers.
  - `/Watch/GetSearchAnalysis` (GET) — médian/analyse (**payant** $49/mois probable).
  - `/Watch/GetPriceHistogram`, `/Watch/GetPriceHistoryDetails` — histo/tendance (payant).
  - `/api/Watch/GetTotalWatchCount` — seul appel qui part au chargement d'une page réf.
- **Réponses de sonde** (curl_cffi, sans session) :
  - `/api/Watch/GetSearchAnalysis?searchTerm=…` → **HTTP 400** (endpoint EXISTE, params faux).
  - `/api/AuctionHouse/MarketPlaceListing` en POST → 405 (veut GET).
  - Les autres en GET nu → 404 (mauvais préfixe/params).

## Le blocage restant (= le travail à faire)
1. **Schéma du `variables`** : chaque endpoint prend `?variables=<JSON>` dont la forme
   n'est pas devinable. Il contient a priori un **modelId/watchId** (pas la réf brute)
   → il faut d'abord un endpoint de **recherche réf→id**, façon résolution WatchCharts.
2. **Session** : la capture Playwright headless d'une page réf/recherche ne déclenche
   PAS l'appel aux résultats d'enchères → très probablement gaté par
   `/api/ewauth/actions/ewsession` (token de session à établir d'abord).

## Comment finir quand on décidera de le faire (estimé : 1 session dédiée)
1. Capturer un vrai parcours navigateur **headed** (ou HAR export depuis Chrome devtools)
   sur une page réf qui affiche « Recent Auction Results » → lire l'URL exacte de
   `GetAuctionResults_v2` + son `variables` + les headers (session/cookies).
2. Reproduire : (a) établir la session `ewsession`, (b) résoudre réf→id, (c) appeler
   `GetAuctionResults_v2`, parser prix vendu/date/maison.
3. Créer `backend/market_everywatch.py` (miroir de `WatchChartsSource`) : `stats(ref)`
   → médiane des ventes réelles + n_ventes, stockées dans une colonne dédiée
   (`ew_median_eur`, `ew_n_sales`, `ew_fetched_at`) à côté de Chrono24, comme demandé.
4. Front : 3e colonne « Prix vendu réel (EveryWatch) ».

## Rappel décision produit
Le tier gratuit donne les **résultats d'enchères récents** (prix/date/maison) sans
login — suffisant pour enrichir une opportunité. Le médian/volatilité calculés sont
payants ($49/mois) : à ne prendre que si on industrialise.
