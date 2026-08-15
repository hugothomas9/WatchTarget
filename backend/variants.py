"""Normalisation cadran (文字盤) + matière (素材/ケース) JP/EN → valeurs canoniques
anglaises, pour matcher les variantes EveryWatch (qui sont en anglais : « Silver »,
« Stainless steel », « Yellow gold »…). Chaque boutique écrit ça à sa façon
(シルバー / silver / Silver dial…) → on ramène à un jeu commun.

Sert de PRÉ-FILTRE avant le matching image (réduit le nombre de variantes à comparer)
ET de fallback quand la photo est inexploitable.
"""

# fragment (minuscule) cherché dans le texte → couleur de cadran canonique EN.
# Les fragments LONGS/spécifiques doivent primer (白蝶貝 avant 白) → on scanne par
# longueur décroissante.
_DIALS = {
    "マザーオブパール": "mother of pearl", "白蝶貝": "mother of pearl",
    "mother of pearl": "mother of pearl", "mop": "mother of pearl",
    "シャンパン": "champagne", "champagne": "champagne",
    "ターコイズ": "turquoise", "turquoise": "turquoise",
    "チョコレート": "chocolate", "chocolate": "chocolate", "ブラウン": "brown",
    "シルバー": "silver", "silver": "silver", "銀": "silver",
    "ホワイト": "white", "white": "white", "白": "white",
    "ブラック": "black", "black": "black", "黒": "black",
    "ブルー": "blue", "blue": "blue", "青": "blue",
    "グリーン": "green", "green": "green", "緑": "green",
    "ピンク": "pink", "pink": "pink",
    "グレー": "gray", "グレイ": "gray", "gray": "gray", "grey": "gray",
    "パープル": "purple", "purple": "purple", "紫": "purple",
    "ベージュ": "beige", "beige": "beige",
    "コーラル": "coral", "coral": "coral",
    "ロジウム": "rhodium", "rhodium": "rhodium",
    "アイボリー": "ivory", "ivory": "ivory",
    "レッド": "red", "red": "red", "赤": "red",
    "イエロー": "yellow", "yellow": "yellow",
    "ゴールド": "gold", "gold": "gold", "金": "gold",
}

# matière de boîtier. « コンビ / 2つ折 / SS×YG » = two-tone (EveryWatch : « Stainless
# steel and 18k yellow gold »). On mappe les deux côtés vers les mêmes jetons.
_MATERIALS = {
    "ステンレススチール": "steel", "ステンレス": "steel", "stainless steel": "steel",
    "stainless": "steel", "steel": "steel", "sus": "steel", "ss": "steel",
    "エバーローズ": "everose", "everose": "everose",
    "ローズゴールド": "rose gold", "ピンクゴールド": "rose gold", "rose gold": "rose gold",
    "イエローゴールド": "yellow gold", "yellow gold": "yellow gold",
    "k18yg": "yellow gold", "yg": "yellow gold", "18k yellow gold": "yellow gold",
    "ホワイトゴールド": "white gold", "white gold": "white gold",
    "k18wg": "white gold", "wg": "white gold",
    "プラチナ": "platinum", "platinum": "platinum", "pt950": "platinum", "pt": "platinum",
    "チタン": "titanium", "titanium": "titanium",
    "コンビ": "two-tone", "ロレゾール": "two-tone", "two-tone": "two-tone",
}


def _match(text: str, table: dict) -> str:
    """Renvoie la valeur canonique du 1er fragment connu trouvé dans `text`
    (fragments longs d'abord → « 白蝶貝 » gagne sur « 白 »)."""
    if not text:
        return ""
    low = text.lower()
    for frag in sorted(table, key=len, reverse=True):
        if frag in low:
            return table[frag]
    return ""


def normalize_dial(text: str) -> str:
    """Couleur de cadran canonique EN (silver, white, turquoise…) ou ''."""
    return _match(text, _DIALS)


def normalize_material(text: str) -> str:
    """Matière de boîtier canonique EN. Détecte le two-tone (acier + or ensemble)."""
    low = (text or "").lower()
    has_steel = _match(low, {k: v for k, v in _MATERIALS.items() if v == "steel"})
    golds = _match(low, {k: v for k, v in _MATERIALS.items()
                         if v in ("yellow gold", "rose gold", "everose", "white gold")})
    if has_steel and golds:
        return "two-tone"
    return _match(low, _MATERIALS)


# libellés de spec possibles selon la boutique
_DIAL_LABELS = ("文字盤", "ダイヤル", "ダイアル", "カラー", "色", "dial", "color", "colour")
_MAT_LABELS = ("ケース素材", "素材", "ケース", "材質", "case material", "material", "case")


def _pick(specs: dict, labels) -> str:
    for lab in labels:
        for k, v in specs.items():
            if lab == k or lab in k:
                if v:
                    return v
    return ""


def dial_from_specs(specs: dict) -> str:
    """Texte brut du cadran depuis un dict de specs (pour raw['cadran'])."""
    return _pick(specs, _DIAL_LABELS)


def material_from_specs(specs: dict) -> str:
    return _pick(specs, _MAT_LABELS)
