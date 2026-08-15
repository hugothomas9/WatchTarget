# Scraper Montres JP — Arbitrage Japon → France

**Date :** 2026-06-27
**Auteur :** Hugo Thomas
**Statut :** Design validé, en attente de la liste des boutiques

## Contexte & objectif

Les montres d'occasion sont moins chères au Japon, généralement en très bon état et bien
entretenues. Il existe une opportunité d'arbitrage inter-région : acheter au Japon, revendre
en France. Le problème est purement logistique — il est impossible de parcourir physiquement
toutes les boutiques de Tokyo, d'autant qu'elles sont dispersées. Heureusement, ces boutiques
publient leur stock en ligne.

**But de l'outil :** parcourir automatiquement les sites des boutiques japonaises, centraliser
tout le stock dans une base, et faire ressortir les montres correspondant à une liste de
références ciblées avec le bénéfice estimé à la revente en France.

L'architecture est volontairement décalquée sur le projet existant `scrap alternance`
(connecteurs modulaires, pipeline, SQLite, front React) pour maximiser la réutilisation.

## Architecture

```
scrap-montres/
├── backend/
│   ├── connectors/        # 1 fichier par boutique JP + base.py commun
│   ├── targets.json       # références cibles + fourchette de revente FR
│   ├── pipeline.py        # orchestre la collecte (--full / --incremental)
│   ├── db.py              # SQLite : watches + historique + favorites
│   ├── matching.py        # match montre scrapée ↔ référence cible (tolérant)
│   ├── pricing.py         # détaxe + conversion JPY→EUR + calcul du bénéfice
│   ├── fx.py              # taux JPY/EUR via API gratuite, cache 1 jour
│   ├── http_client.py     # requêtes HTTP + Playwright headless en fallback
│   └── api.py             # API servant le front (Stock, Cibles, Favoris)
├── frontend/             # React/Vite (même stack que scrap alternance)
│   └── ...
├── scripts/
│   └── collecte.sh       # lance une collecte
└── docs/specs/
```

## Composants

### `connectors/` — un par boutique

Chaque connecteur expose la même interface (définie dans `base.py`) :
- `collect(mode)` où `mode ∈ {full, incremental}`.
- `full` : parcourt tout le catalogue (toutes les pages) — utilisé une seule fois pour amorcer.
- `incremental` : récupère uniquement les nouveautés (1ère page triée par date d'ajout).

`base.py` gère le commun : rotation de user-agent, délais entre requêtes, retries,
parsing tolérant. Scraping HTML brut (requests + BeautifulSoup) par défaut ; Playwright
headless en fallback **uniquement** pour les sites 100% JavaScript.

### `db.py` — stockage SQLite

Tables :
- **`watches`** : une ligne par montre scrapée. Dédoublonnage sur `(boutique, reference, lien)`.
- **`favorites`** : montres épinglées par l'utilisateur (snapshot conservé même si la montre
  est vendue ensuite).

Champs `watches` (tout ce qui figure sur la fiche produit) :

| Champ | Description |
|---|---|
| `id` | identifiant interne unique |
| `boutique` | source / lieu |
| `marque`, `modele` | marque et modèle |
| `reference` | référence telle qu'écrite sur le site |
| `prix_ttc` | prix affiché taxe incluse (税込) |
| `prix_ht` | prix hors taxe (税抜) si le site le donne |
| `prix_detaxe` | prix détaxé calculé (voir Pricing) |
| `etat` | état / condition |
| `annee` | année / date de la montre |
| `date_ajout_site` | date d'ajout sur la boutique (si disponible) |
| `date_vue` | date du 1er scrape par nous |
| `description` | description si présente |
| `lien` | URL de la fiche sur le site source |
| `images` | URLs des photos |

### `matching.py` — montre ↔ cible

Rapproche chaque montre scrapée d'une référence cible de `targets.json`. Le matching est
**tolérant** aux variantes d'écriture des références : espaces, préfixes (« Ref. »), casse,
tirets. Une cible peut lister plusieurs orthographes de référence.

### `pricing.py` — détaxe, conversion, bénéfice

Mécanique fiscale japonaise (vérifiée) : taxe à la consommation = **10%**, prix affichés
généralement en **TTC (税込)**. Le prix détaxé pour un acheteur étranger = le prix **HT (税抜)**.

```
prix_detaxe_jpy = prix_ht            si le site affiche le 税抜
                = prix_ttc / 1.10    sinon   (et NON prix_ttc × 0.90)

prix_detaxe_eur = prix_detaxe_jpy × taux_JPY→EUR_du_jour

benef_min = revente_fr_min − prix_detaxe_eur − couts_optionnels_eur
benef_max = revente_fr_max − prix_detaxe_eur − couts_optionnels_eur
benef_pct = benef / prix_detaxe_eur
```

> Note : `prix_ttc / 1.10 = prix_ttc × 0.909`, soit ~9,1% sous le TTC (pas 10%). Sur une
> montre à ¥1 500 000 l'écart vaut ~¥14 000 (~85 €), donc on utilise bien la division.

> Note 2026 : depuis le 1er nov. 2026, la détaxe en boutique disparaît — on paie le TTC
> plein puis on se fait rembourser les 10% à l'aéroport. Le coût net reste identique
> (avance de trésorerie uniquement), le calcul ne change pas.

Le bénéfice principal **n'inclut pas** douane / port / commission de revente. Un champ
`couts_optionnels_eur` par cible permet de les ajouter manuellement plus tard si souhaité.

### `fx.py` — taux de change

Récupère le taux JPY→EUR via une API gratuite (frankfurter.app ou exchangerate.host),
avec cache 1 jour pour éviter les appels répétés.

### `api.py` + frontend — 3 pages

1. **Stock** : tableau filtrable de tout le stock collecté (boutique, marque, modèle, prix,
   état, date d'ajout). Bouton ★ favoris sur chaque ligne.
2. **Cibles** : uniquement les montres matchant `targets.json`. Affiche prix détaxé €,
   fourchette de revente FR, bénéfice min/max et %, lien direct vers la fiche. Tri par
   bénéfice décroissant. Bouton ★ favoris.
3. **Favoris** : montres épinglées depuis Stock ou Cibles. Conserve le snapshot et le
   bénéfice (si cible) ; marque « plus dispo » si la montre disparaît du stock.

## Format `targets.json`

```json
{
  "targets": [
    {
      "id": "rolex-submariner-126610LN",
      "marque": "Rolex",
      "modele": "Submariner Date",
      "references": ["126610LN", "126610 LN"],
      "revente_fr_min": 9500,
      "revente_fr_max": 11000,
      "criteres": { "etat_min": "très bon", "annee_min": 2015 },
      "couts_optionnels_eur": 0
    }
  ]
}
```

Les références sont fournies progressivement par l'utilisateur.

## Flux de collecte

- **Premier lancement (`--full`)** : parcourt l'intégralité du catalogue de chaque boutique
  pour amorcer la base.
- **Lancements suivants (`--incremental`)** : récupère uniquement les nouveautés (1ère page
  triée par date d'ajout). L'historique est conservé entre les runs.
- À chaque collecte : dédoublonnage, calcul des prix détaxés/bénéfices, mise à jour de la base.

## Données / sources

Boutiques japonaises fournies par l'utilisateur (liste à venir). Claude complétera avec des
boutiques similaires. Approche : scraping HTML brut, Playwright headless en fallback pour les
sites JS. Démarrage du dev sur **un seul site** pour valider le flux complet de bout en bout,
puis duplication des connecteurs sur les autres sites.

## Roadmap (à rediscuter plus tard)

- **Déploiement** de l'outil, code maintenu **privé**.
- **Multi-utilisateurs** : permettre à différents utilisateurs de configurer leurs propres
  cibles et alertes. À définir ultérieurement.
- Champs de coûts réels (douane, port, commission) intégrables dans le bénéfice si besoin.

## Hors-scope (v1)

- Achat / commande automatisée (l'outil informe, l'achat reste manuel).
- Authentification multi-utilisateurs (roadmap).
- Notifications / alertes push (roadmap).
