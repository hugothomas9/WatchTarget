"""Filtres de qualification d'une montre : full set (boîte + papiers) et récence."""
import re
from datetime import datetime, timezone

# Indices de présence de la BOÎTE et des PAPIERS dans le champ 付属品 (accessoires).
_BOX = ["箱", "ボックス", "純正箱", "メーカー箱", "内箱", "外箱", "ケース箱"]
_PAPER = ["保証書", "保証カード", "ギャラン", "ワランティ", "国際保証", "証明書",
          "保付", "ギャランティー"]
_FULLSET = ["フルセット", "付属品完備", "付属品完品", "完品", "一式", "full set"]

_DATE_RE = re.compile(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})")


# Marqueurs de NÉGATION qui suivent un mot-clé (無し = sans, 欠品 = manquant,
# 付属しません = non fourni…). Fenêtre de 10 chars : « 保証書は付属しません »
# porte sa négation 5 caractères après le mot-clé.
_NEG = ("無", "なし", "ナシ", "ません", "ない", "欠品", "非付属",
        "non", "no ", "sans", "without")
_NEG_WINDOW = 10


def _present(text: str, keywords) -> bool:
    """True si un mot-clé est présent SANS négation juste après (ex: 'BOX無し' = non)."""
    low = text.lower()
    for k in keywords:
        kl = k.lower()
        i = low.find(kl)
        while i != -1:
            tail = low[i + len(kl): i + len(kl) + _NEG_WINDOW]
            if not any(n in tail for n in _NEG):
                return True
            i = low.find(kl, i + 1)
    return False


def is_full_set(accessoires: str) -> bool:
    """True si le texte d'accessoires atteste boîte ET papiers (ou 'full set'),
    en tenant compte des négations japonaises (BOX無し / 保証書なし = NON)."""
    if not accessoires:
        return False
    if _present(accessoires, _FULLSET):
        return True
    has_box = _present(accessoires, _BOX + ["box"])
    has_paper = _present(accessoires, _PAPER + ["warranty", "guarantee", "papers"])
    return has_box and has_paper


def parse_date(s: str):
    """Extrait une date (YYYY/MM/DD ou YYYY-MM-DD, éventuellement avec heure)."""
    if not s:
        return None
    m = _DATE_RE.search(s)
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                        tzinfo=timezone.utc)
    except ValueError:
        return None


def age_days(date_str: str):
    """Âge en jours d'une date d'ajout, ou None si non parsable."""
    d = parse_date(date_str)
    if d is None:
        return None
    return (datetime.now(timezone.utc) - d).days


def is_recent(date_str: str, max_days: int = 120) -> bool:
    """True si la date est connue ET récente (< max_days). Inconnu → False."""
    age = age_days(date_str)
    return age is not None and age <= max_days
