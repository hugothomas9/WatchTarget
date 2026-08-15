"""Rapprochement tolérant entre une référence scrapée et les cibles du JSON."""
import re

_PREFIX_RE = re.compile(r"\b(ref(erence)?|référence|réf|model[e]?)\b\.?:?", re.I)
_NONALNUM_RE = re.compile(r"[^A-Z0-9]")


def normalize_ref(ref: str) -> str:
    """Normalise une référence : retire préfixes, ponctuation, espaces, casse."""
    if not ref:
        return ""
    ref = _PREFIX_RE.sub(" ", ref)
    return _NONALNUM_RE.sub("", ref.upper())


MIN_SUBSTR_LEN = 6  # sous-chaîne autorisée seulement pour des réfs assez longues


def _contains_ref(haystack: str, ref: str) -> bool:
    """True si `ref` apparaît dans `haystack` avec des FRONTIÈRES de numéro :
    le caractère juste avant/après ne doit pas être un chiffre, sinon
    '16610LN' matcherait à tort dans '116610LN' (réfs Rolex voisines)."""
    i = haystack.find(ref)
    while i != -1:
        before = haystack[i - 1] if i > 0 else ""
        after = haystack[i + len(ref)] if i + len(ref) < len(haystack) else ""
        if not before.isdigit() and not after.isdigit():
            return True
        i = haystack.find(ref, i + 1)
    return False


def match_target(watch_ref: str, targets: list[dict]) -> dict | None:
    """Renvoie la cible dont une référence normalisée matche celle de la montre.
    Égalité stricte, OU réf cible contenue dans la réf scrapée (titres longs)
    avec frontières de numéro. Le sens inverse (réf scrapée courte contenue
    dans la cible) est interdit : trop de faux positifs → faux bénéfices."""
    w = normalize_ref(watch_ref)
    if not w:
        return None
    for t in targets:
        for ref in t.get("references", []):
            n = normalize_ref(ref)
            if not n:
                continue
            if n == w:
                return t
            if len(n) >= MIN_SUBSTR_LEN and _contains_ref(w, n):
                return t
    return None
