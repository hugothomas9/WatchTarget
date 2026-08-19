"""Rendu du bot Telegram — module PUR : aucun réseau, aucune DB, aucun accès config.

Tout ce qui s'affiche dans le bot est construit ici, à partir de données déjà lues.
C'est ce qui rend le bot testable sans réseau (cf. `verify_dispo.status_from_html`).

RÈGLE DURE (spec 2026-08-17) : le bot est PUBLIC. Aucun prix détaxé, aucune donnée
EveryWatch, aucune marge — `preparer_montres` supprime ces champs à l'entrée et
`tests/test_bot_ui.py` interdit leur réapparition en sortie.
"""
import html
import json

LIMITE_LEGENDE = 1024      # légende d'une photo Telegram
LIMITE_TEXTE = 4096        # message texte Telegram
REFS_PAR_PAGE = 3          # blocs (= photos) par page
ANNONCES_PAR_REF = 8       # annonces listées par référence, puis « …et N autres »

# Champs qui ne doivent JAMAIS sortir du bot (edge d'arbitrage privé).
CHAMPS_INTERDITS = ("prix_detaxe_eur", "prix_detaxe_jpy", "prix_ht",
                    "ew_median_eur", "ew_p25_eur", "ew_p75_eur", "ew_n_sales",
                    "spread_eur", "spread_p25_eur", "net_eur",
                    "benef_min", "benef_max", "median_eur")


def _esc(s) -> str:
    return html.escape(str(s or ""))


def fmt_eur(montant) -> str:
    """« 19 260 € », ou « prix sur demande » si le prix est inconnu."""
    if montant is None:
        return "prix sur demande"
    return f"{round(montant):,} €".replace(",", " ")


def preparer_montres(rows: list[dict], rate: float) -> list[dict]:
    """Lignes brutes de `watches` → montres prêtes à afficher.

    `rate` = EUR pour 1 JPY (fourni par l'appelant : le module reste pur).
    Convertit le PRIX BOUTIQUE `prix_ttc` (yens) en euros — jamais un prix détaxé —
    et ne garde que les champs autorisés.
    """
    out = []
    for r in rows:
        prix_ttc = r.get("prix_ttc")
        # `watches.images` est stocké en JSON sérialisé (db.upsert_watch) ; les tests
        # passent parfois déjà une liste → on accepte les deux formes.
        images = r.get("images") or []
        if isinstance(images, str):
            try:
                images = json.loads(images)
            except (TypeError, ValueError):
                images = []
        if not isinstance(images, list):
            images = []
        out.append({
            "uid": r.get("uid", ""),
            "marque": r.get("marque", "") or "",
            "modele": r.get("modele", "") or "",
            "reference": r.get("reference", "") or "",
            "etat": r.get("etat", "") or "",
            "boutique": r.get("boutique", "") or "",
            "url": r.get("url", "") or "",
            "image": images[0] if images else None,
            "prix_eur": round(prix_ttc * rate) if prix_ttc else None,
        })
    return out


def titre_bloc(w: dict) -> str:
    """« Marque Modèle — Référence ». Ligne PRIORITAIRE : jamais tronquée."""
    gauche = " ".join(p for p in (w.get("marque"), w.get("modele")) if p).strip()
    ref = (w.get("reference") or "").strip()
    return f"{gauche} — {ref}" if ref else gauche


def ligne_annonce(w: dict) -> str:
    """« • Occasion A · 19 260 € · jackroad → Voir » (lien HTML)."""
    bouts = [p for p in (_esc(w.get("etat")), fmt_eur(w.get("prix_eur")),
                         _esc(w.get("boutique"))) if p]
    ligne = "• " + " · ".join(bouts)
    if w.get("url"):
        ligne += f' → <a href="{_esc(w["url"])}">Voir</a>'
    return ligne


def _prix_tri(m: dict):
    """Clé de tri : prix croissant, prix inconnu en dernier."""
    return (m.get("prix_eur") is None, m.get("prix_eur") or 0)


def grouper_par_reference(montres: list[dict]) -> list[dict]:
    """Regroupe par référence (à défaut par titre) : un bloc = une photo + ses annonces.
    Blocs triés par prix mini croissant, annonces triées par prix croissant."""
    blocs: dict = {}
    for m in montres:
        cle = (m.get("reference") or "").strip().lower() or titre_bloc(m).lower()
        b = blocs.setdefault(cle, {"titre": titre_bloc(m), "photo": None,
                                   "annonces": []})
        b["annonces"].append(m)
        if b["photo"] is None and m.get("image"):
            b["photo"] = m["image"]
    for b in blocs.values():
        b["annonces"].sort(key=_prix_tri)
    return sorted(blocs.values(), key=lambda b: _prix_tri(b["annonces"][0]))


def _titre_html_tronque(titre_brut: str) -> str:
    """Dernier recours : le titre (balises + échappement compris) dépasse à lui seul
    LIMITE_LEGENDE. On raccourcit le TEXTE BRUT avant de l'échapper et de l'envelopper,
    pour ne jamais couper une entité HTML ou une balise en plein milieu (`&lt;` coupé
    en `&l` serait un bug)."""
    texte = titre_brut
    while texte:
        candidat = f"<b>{_esc(texte)}…</b>"
        if len(candidat) <= LIMITE_LEGENDE:
            return candidat
        texte = texte[:-1]
    # même un seul caractère ne suffit pas (LIMITE_LEGENDE absurdement petite) : on
    # renvoie le strict minimum, garanti <= LIMITE_LEGENDE dans tous les cas réalistes.
    return "<b>…</b>"


def legende_bloc(bloc: dict) -> str:
    """Légende de la photo d'un bloc : titre puis annonces.

    Garde-fous, dans l'ordre : au plus ANNONCES_PAR_REF annonces ; si la légende
    dépasse LIMITE_LEGENDE on retire des annonces une par une — LE TITRE RESTE
    TOUJOURS PRIORITAIRE. Si même le titre seul (une fois entouré de <b></b> et
    échappé) dépasse LIMITE_LEGENDE, on le raccourcit en dernier recours : la spec
    exige à la fois « titre jamais sacrifié aux annonces » ET « légende <= 1024 » —
    un titre écourté vaut mieux qu'une légende invalide que Telegram refusera.
    """
    titre_brut = titre_bloc(bloc["annonces"][0])
    titre = f"<b>{_esc(titre_brut)}</b>"
    annonces = bloc["annonces"]
    n_max = min(len(annonces), ANNONCES_PAR_REF)
    while n_max > 0:
        lignes = [titre] + [ligne_annonce(a) for a in annonces[:n_max]]
        reste = len(annonces) - n_max
        if reste > 0:
            lignes.append(f"…et {reste} autres")
        texte = "\n".join(lignes)
        if len(texte) <= LIMITE_LEGENDE:
            return texte
        n_max -= 1

    # Plus aucune annonce ne tient à côté du titre. On essaie titre + résumé, puis
    # titre seul, avant de raccourcir le titre en tout dernier recours.
    reste = len(annonces)
    if reste > 0:
        texte = f"{titre}\n…et {reste} autres"
        if len(texte) <= LIMITE_LEGENDE:
            return texte
    if len(titre) <= LIMITE_LEGENDE:
        return titre
    return _titre_html_tronque(titre_brut)
