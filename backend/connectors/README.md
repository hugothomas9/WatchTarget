# Écrire un connecteur boutique

1. Copier `_template.py` → `<boutique>.py`, renommer la classe.
2. Adapter `_parse_liste` (URLs des fiches) et `_parse_fiche` (sélecteurs CSS).
3. Mapper les prix : récupérer le **TTC (税込)** ; passer le **HT (税抜)** dans
   `prix_ht` si le site l'affiche (sinon `pricing` divisera le TTC par 1.10).
4. Enregistrer dans `registry.py` : ajouter à `CONNECTORS` et `BOUTIQUES`.
5. Site 100% JavaScript ? Remplacer `http_client.get_text` par un rendu
   Playwright headless (à ajouter dans `http_client` au besoin).
6. Tester : `python -m backend.run --full` puis vérifier dans l'API.
