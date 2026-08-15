"""Traduction de l'état (condition) d'une montre en français lisible.

Les boutiques JP expriment l'état de façons hétérogènes : anglais (NEW/USED/UNUSED),
japonais court (新品 / 中古A / 未使用品), rang seul (Aランク / Sランク), ou longue prose
japonaise (中古 ランク A ケース 僅かな小傷…). Certains connecteurs capturent aussi des
fragments parasites (« ですが、外装仕上げ… ») : on les ramène à « — » plutôt que d'afficher
du charabia. On renvoie un libellé court : base (Neuf/Occasion/Vintage) + rang si connu.
"""
import re

# rang de condition → libellé FR (du meilleur au moins bon)
_RANGS = {
    "N": "neuf",
    "S": "comme neuf",
    "A": "très bon état",
    "AB": "bon état",
    "B": "état correct",
    "BC": "état moyen",
    "C": "état moyen",
}


def _rang(texte: str) -> str:
    """Extrait le rang (S/A/AB/B/N…) où qu'il soit : « ランク A », « Aランク », « 中古AB »,
    « ランク N »… Renvoie '' si absent. On teste les rangs à 2 lettres d'abord (AB, BC)."""
    for code in ("AB", "BC", "N", "S", "A", "B", "C"):
        # « ランク AB », « ABランク », « 中古AB », « 中古 ランク AB »
        if re.search(rf"(?:ランク[・･\s]*{code}\b|{code}\s*ランク|中古\s*{code}\b|新品\s*ランク\s*{code}\b)",
                     texte):
            return code
    return ""


def traduire_etat(texte: str | None) -> str:
    """Libellé d'état en français, ou '' si rien d'exploitable."""
    if not texte:
        return ""
    t = texte.strip()

    # --- base : neuf / jamais porté / occasion / vintage ---
    neuf = bool(re.search(r"新品|(?<![A-Za-z])NEW(?![A-Za-z])", t, re.I)) and "未使用" not in t
    jamais_porte = bool(re.search(r"未使用|UNUSED|S（未使用）|S\(未使用\)", t, re.I))
    vintage = bool(re.search(r"ヴィンテージ|アンティーク|VINTAGE|ANTIQUE", t, re.I))
    occasion = bool(re.search(r"中古|(?<![A-Za-z])USED(?![A-Za-z])", t, re.I))

    rang = _rang(t)
    detail = f" – {_RANGS[rang]} ({rang})" if rang in _RANGS else ""

    if vintage:
        return "Vintage" + detail
    if jamais_porte:
        return "Neuf (jamais porté)"
    if neuf:
        return "Neuf" + (detail if rang and rang != "N" else "")
    if occasion:
        return "Occasion" + detail
    # rang seul sans mot-clé de base (ex « Aランク（ランクについて） »)
    if rang:
        return "Occasion" + detail
    # rien de reconnu (fragment parasite d'un connecteur) → non renseigné
    return ""
