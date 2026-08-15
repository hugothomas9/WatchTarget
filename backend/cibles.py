"""Cibles par MOTS-CLÉS : une alerte = des mots-clés, une montre matche si elle
contient TOUS les mots-clés (« rolex daytona 126506A »).

Astuce multilingue : le modèle scrapé est souvent en japonais (デイトナ). On construit
un « blob » de recherche qui réunit marque + famille (latin) + nom traduit + nom
original + référence + description, tout en minuscules. Ainsi « daytona » matche une
デイトナ (via la famille) et « 126506a » matche la référence normalisée.
"""
import re

from .matching import normalize_ref


def _norm(s: str) -> str:
    """Minuscule + espaces compactés (garde lettres/chiffres/kana/kanji)."""
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


def blob_recherche(w: dict) -> str:
    """Texte de recherche d'une montre = tout ce sur quoi un mot-clé peut matcher.
    Inclut la réf NORMALISÉE (sans espaces/tirets) ET la réf brute, la famille et le
    nom traduit (pour matcher en latin un modèle japonais)."""
    from .familles import famille_de
    from .noms import traduire_nom
    marque = w.get("marque", "") or ""
    modele = w.get("modele", "") or ""
    ref = w.get("reference", "") or ""
    fam = w.get("famille") or famille_de(marque, modele, w.get("description", "") or "")
    parts = [marque, fam, traduire_nom(modele), modele, ref,
             normalize_ref(ref), w.get("description", "") or ""]
    return _norm(" ".join(p for p in parts if p))


def decouper_mots(mots_cles: str) -> list[str]:
    """Découpe la saisie utilisateur en mots-clés normalisés (espaces = séparateurs).
    Une réf comme « 126506A » est aussi indexée sous sa forme normalisée."""
    out = []
    for tok in _norm(mots_cles).split():
        if tok and tok not in out:
            out.append(tok)
    return out


def matche(mots_cles: str, blob: str) -> bool:
    """True si TOUS les mots-clés sont présents dans le blob. Un mot-clé qui
    ressemble à une référence matche aussi la forme normalisée du blob."""
    mots = decouper_mots(mots_cles)
    if not mots:
        return False
    blob_ref = normalize_ref(blob)   # concatène chiffres/lettres → matche les réfs
    for m in mots:
        mref = normalize_ref(m)
        if m in blob:
            continue
        # mot-clé de type référence (contient un chiffre) : tenter la forme normalisée
        if mref and any(c.isdigit() for c in mref) and mref in blob_ref:
            continue
        return False
    return True
