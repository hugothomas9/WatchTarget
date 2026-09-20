"""Normalisation des noms de marque (chaque site les écrit différemment :
オメガ / OMEGA / Omega …). On ramène tout à un libellé canonique pour que le
filtre marque du front soit propre. Marque inconnue → renvoyée telle quelle."""

# clé = fragment (minuscule) cherché dans le libellé brut ; valeur = canonique
_ALIASES = {
    "オメガ": "Omega", "omega": "Omega",
    "ロレックス": "Rolex", "rolex": "Rolex",
    "チューダー": "Tudor", "チュードル": "Tudor", "tudor": "Tudor",
    "カルティエ": "Cartier", "cartier": "Cartier",
    "パテックフィリップ": "Patek Philippe", "パテック・フィリップ": "Patek Philippe",
    "patek": "Patek Philippe",
    "オーデマ": "Audemars Piguet", "audema": "Audemars Piguet",
    "ランゲ": "A. Lange & Söhne", "lange": "A. Lange & Söhne",
    "グラスヒュッテ": "Glashütte Original", "glashutte": "Glashütte Original",
    "ヴァシュロン": "Vacheron Constantin", "vacheron": "Vacheron Constantin",
    "ブレゲ": "Breguet", "breguet": "Breguet",
    "ジャガー": "Jaeger-LeCoultre", "jaeger": "Jaeger-LeCoultre",
    "セイコー": "Seiko", "seiko": "Seiko",
    "グランドセイコー": "Grand Seiko", "grand seiko": "Grand Seiko",
    "タグ": "Tag Heuer", "tag heuer": "Tag Heuer", "ホイヤー": "Tag Heuer",
    "iwc": "IWC",
    "ブライトリング": "Breitling", "breitling": "Breitling",
    "パネライ": "Panerai", "panerai": "Panerai",
    "フランク": "Franck Muller", "franck": "Franck Muller",
    "ウブロ": "Hublot", "hublot": "Hublot",
    "ブランパン": "Blancpain", "blancpain": "Blancpain",
    "ゼニス": "Zenith", "zenith": "Zenith",
    "ハリー": "Harry Winston", "harry winston": "Harry Winston",
    "ルイヴィトン": "Louis Vuitton", "ルイ・ヴィトン": "Louis Vuitton",
    "louis vuitton": "Louis Vuitton", "vuitton": "Louis Vuitton",
    "シャネル": "Chanel", "chanel": "Chanel",
    "エルメス": "Hermès", "hermes": "Hermès", "hermès": "Hermès",
    "ショパール": "Chopard", "chopard": "Chopard",
    "ショーメ": "Chaumet", "chaumet": "Chaumet",
    "ブルガリ": "Bvlgari", "bvlgari": "Bvlgari", "bulgari": "Bvlgari",
    "ベル": "Bell & Ross", "bell&ross": "Bell & Ross", "bell & ross": "Bell & Ross",
    "ジラール": "Girard-Perregaux", "girard": "Girard-Perregaux",
    "ノモス": "Nomos", "nomos": "Nomos",
    "ロンジン": "Longines", "longines": "Longines",
    "ボーム": "Baume & Mercier", "baume": "Baume & Mercier",
    "コルム": "Corum", "corum": "Corum",
    "クロノスイス": "Chronoswiss", "chronoswiss": "Chronoswiss",
    "ジン": "Sinn", "sinn": "Sinn",
    "ロジェ": "Roger Dubuis", "roger dubuis": "Roger Dubuis",
    "モンブラン": "Montblanc", "montblanc": "Montblanc",
    "フレデリック": "Frederique Constant", "frederique": "Frederique Constant",
    "モーリス": "Maurice Lacroix", "maurice": "Maurice Lacroix",
    "ユリス": "Ulysse Nardin", "ulysse": "Ulysse Nardin",
    "ジャケ": "Jaquet Droz", "jaquet": "Jaquet Droz",
    "グラハム": "Graham", "graham": "Graham",
    "パルミジャーニ": "Parmigiani Fleurier", "parmigiani": "Parmigiani Fleurier",
    "シチズン": "Citizen", "citizen": "Citizen",
    "オリエント": "Orient", "orient": "Orient",
    "ユニバーサル": "Universal Genève", "universal": "Universal Genève",
    "リシャール": "Richard Mille", "richard mille": "Richard Mille",
    "ヴァンクリーフ": "Van Cleef & Arpels", "van cleef": "Van Cleef & Arpels",
    "ティファニー": "Tiffany & Co.", "tiffany": "Tiffany & Co.",
    "オリス": "Oris", "oris": "Oris",
    # --- complétés d'après le scan des marques restées en katakana (2026-08) ---
    "ユンハンス": "Junghans", "junghans": "Junghans",
    "ティソ": "Tissot", "tissot": "Tissot",
    "ハミルトン": "Hamilton", "hamilton": "Hamilton",
    "エラール": "Louis Erard", "louis erard": "Louis Erard",
    "アイクポッド": "Ikepod", "ikepod": "Ikepod",
    "パテック": "Patek Philippe",   # couvre « パテック フィリップ » (avec espace)
    "ピアジェ": "Piaget", "piaget": "Piaget",
    "ラドー": "Rado", "rado": "Rado",
    "カシオ": "Casio", "casio": "Casio",
    "ノルケイン": "Norqain", "norqain": "Norqain",
    "ペキニエ": "Pequignet", "pequignet": "Pequignet",
    "エポス": "Epos", "epos": "Epos",
    "ポルシェ": "Porsche Design", "porsche": "Porsche Design",
    "レイモンド": "Raymond Weil", "raymond": "Raymond Weil",
    # PAS de fragment katakana « グラフ » : il est contenu dans クロノグラフ
    # (chronographe) et transformerait n'importe quel chrono en montre Graff.
    "graff": "Graff",
    "フォルティス": "Fortis", "fortis": "Fortis",
    "グッチ": "Gucci", "gucci": "Gucci",
    "モーザー": "H. Moser & Cie", "moser": "H. Moser & Cie",
}

OTHER = "Autres"
_OTHER_HINTS = ("その他", "other")


# fragments testés du plus LONG au plus court : « グランドセイコー » doit gagner
# sur « セイコー » qu'il contient (sinon les Grand Seiko retombaient sur Seiko)
_ALIASES_TRIES = sorted(_ALIASES.items(), key=lambda kv: -len(kv[0]))


def normalize_marque(raw: str) -> str:
    """Ramène un libellé de marque brut vers son nom canonique."""
    if not raw:
        return ""
    low = raw.strip().lower()
    for frag, canon in _ALIASES_TRIES:
        if frag in low:
            return canon
    for hint in _OTHER_HINTS:
        if hint in low:
            return OTHER
    return raw.strip()
