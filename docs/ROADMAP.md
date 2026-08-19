# Roadmap — scrap-montres

## Prochainement (priorité haute)


### Filtre « Modèle générique » (après le filtre Marque)
Un filtre par modèle générique transverse : Daytona / Datejust / GMT-Master (Rolex),
Seamaster / Speedmaster (Omega), Black Bay (Tudor)…

**Bonne nouvelle : la brique existe déjà.** Le champ `famille` est calculé par
`backend/familles.py` (mappings JP→Latin) et stocké sur chaque montre ; le front a
déjà un filtre cascade **Marque → Ligne**. Restant à faire :
- surfacer « Ligne » comme un vrai filtre **Modèle** visible et indépendant (pas
  seulement en cascade après la marque) ;
- compléter le glossaire `familles.py` pour les modèles manquants ;
- éventuellement un filtre multi-modèles (cocher plusieurs lignes).

### Traduction des noms de montres (EN COURS)
Le champ `modele` scrapé est souvent en japonais (スピードマスター…). On le traduit à
l'affichage via `backend/noms.py` (glossaire familles + couleurs + termes courants),
original conservé en info-bulle. À étendre au fil des cas non couverts.

## Fait récemment
- **4 correctifs critiques post-revue (2026-08-19)** — (1) SQL des TTL portable
  PostgreSQL (`db.iso_ago`, le worker prod re-fonctionne en entier) ; (2) faille
  d'accès anonyme aux alertes fermée (`LOCAL_ADMIN`, 401/404, cookie Secure,
  /api/collecte + favoris protégés, adoption des alertes orphelines par l'admin) ;
  (3) verify GMT via curl_cffi throttlé + bump last_seen sur INCONNU (fin du
  re-fetch infini, 1144 fiches GMT redeviennent vérifiables) ; (4) pipeline isolé
  par boutique + rollback transaction. 118 tests verts sur SQLite **et** PostgreSQL
  (la suite complète tourne désormais sur les 2 moteurs).
- **Comptes utilisateurs + alertes par personne (étape 2 déploiement, backend)** —
  identité Telegram (Login Widget, signature vérifiée), alertes rattachées à leur
  propriétaire, notifs envoyées au bon utilisateur. Reste le bouton front + /setdomain
  au déploiement. 102 tests verts.
- **Migration SQLite → PostgreSQL (couche portable)** — `backend/dbengine.py` : même
  code sur les 2 moteurs (SQLite local par défaut, PostgreSQL en prod via `DATABASE_URL`).
  Testé sur les 2 (95 tests + parité PG). Script de reprise `scripts/migrate_sqlite_to_pg.py`.
  → débloque le multi-utilisateurs (MVCC, plus de « database is locked »).
- **Cibles par mots-clés + alertes Telegram** — alerte « rolex daytona 126506A »,
  matching multilingue (`cibles.py`, réutilise familles+noms), vue Cibles enrichie
  (marge EW), push Telegram sur les nouveaux arrivages (`telegram.py`, anti-spam sur
  le stock existant), UI de gestion des alertes dans l'onglet Cibles.
- **5 sites artisanaux** connectés : BrandBank, Gallery Rare, Yukizaki, Housekihiroba, GMT.
- Traduction FR de l'état (`backend/etat.py`) — neuf / occasion + rang (A/AB/S…).
- Tri stock prix décroissant + case « Dispo uniquement ».
- Étoile favoris « pleine si déjà favori » (visible dans le stock), maj optimiste.
- Favoris enrichis (mêmes données que les opportunités : marge, prix vendu EW, liquidité).
- Analyse auto au clic favori (vérif dispo + pricing EveryWatch en tâche de fond).
- Connecteur MakeShop générique (King's Road, 7HOURS) — sitemap KO → pagination
  `list{N}.html` + JSON-LD Product/ProductGroup.

## Sites restants à connecter (vague artisanale)
- **BrandBank** — Color Me Shop (`/shopbrand/`, `/shopdetail/`) → connecteur `colormeshop`.
- **Gallery Rare** — FutureShop.
- **Gem Castle Yukizaki** — plateforme valx (~20 magasins).
- **Housekihiroba** — ASP.NET Shift_JIS.
- **GMT** — WAF 403 → passer par Rakuten `item.rakuten.co.jp/gmt/`.
