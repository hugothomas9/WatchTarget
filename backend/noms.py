"""Traduction des NOMS de montres (champ `modele`) japonais → latin/français.

Le nom scrapé est souvent en katakana (スピードマスター…). On remplace les termes
connus (collections, complications, matières, couleurs) par leur équivalent latin,
du plus LONG au plus court (pour que « マスタークロノメーター » soit traité avant
« マスター »). Ce qui n'est pas au glossaire est laissé tel quel (référence, année…).

Glossaire volontairement pragmatique : il couvre les termes fréquents observés en
base. À étendre au fil des cas non traduits (cf. docs/ROADMAP.md).
"""
import re

# terme japonais -> latin. Regroupé par thème pour la maintenance.
_GLOSSAIRE = {
    # --- collections / lignes (transverses marques) ---
    "スピードマスター": "Speedmaster", "シーマスター": "Seamaster",
    "コンステレーション": "Constellation", "グローブマスター": "Globemaster",
    "レイルマスター": "Railmaster", "デ・ヴィル": "De Ville", "デヴィル": "De Ville",
    "プラネットオーシャン": "Planet Ocean", "アクアテラ": "Aqua Terra",
    "デイトジャスト": "Datejust", "デイトナ": "Daytona", "サブマリーナ": "Submariner",
    "エクスプローラー": "Explorer", "シードゥエラー": "Sea-Dweller",
    "ディープシー": "Deepsea", "オイスターパーペチュアル": "Oyster Perpetual",
    "デイデイト": "Day-Date", "スカイドゥエラー": "Sky-Dweller",
    "ミルガウス": "Milgauss", "エアキング": "Air-King", "ヨットマスター": "Yacht-Master",
    "チェリーニ": "Cellini", "コスモグラフ": "Cosmograph",
    "ブラックベイ": "Black Bay", "ペラゴス": "Pelagos", "レンジャー": "Ranger",
    "ロイヤルオーク": "Royal Oak", "ノーチラス": "Nautilus", "アクアノート": "Aquanaut",
    "ルミノール": "Luminor", "ラジオミール": "Radiomir",
    "カレラ": "Carrera", "アクアレーサー": "Aquaracer", "モナコ": "Monaco",
    "ロイヤルオークオフショア": "Royal Oak Offshore",
    "サントス": "Santos", "タンク": "Tank", "バロンブルー": "Ballon Bleu",
    "パンテール": "Panthère", "カリブル": "Calibre",
    "プロスペックス": "Prospex", "グランドセイコー": "Grand Seiko",
    "ムーンフェイズ": "Moonphase", "ヘリテージ": "Heritage", "デファイ": "Defy",
    "フュージョン": "Fusion", "クラシックフュージョン": "Classic Fusion",
    "ビッグバン": "Big Bang", "オーヴァーシーズ": "Overseas",
    # --- complications / attributs (l'ordre long→court est géré au tri) ---
    "マスタークロノメーター": "Master Chronometer", "コーアクシャル": "Co-Axial",
    "クロノグラフ": "Chronograph", "クロノメーター": "Chronometer", "クロノ": "Chrono",
    "オートマティック": "Automatic", "パーペチュアル": "Perpetual",
    "プロフェッショナル": "Professional", "コレクション": "Collection",
    "リミテッド": "Limited", "リミテッドエディション": "Édition limitée",
    "キャリバー": "Calibre", "ダイバー": "Diver", "スポーツ": "Sport",
    "ダイヤモンド": "Diamant", "ダイヤ": "Diamant", "ヴィンテージ": "Vintage",
    "アンティーク": "Antique", "パワーリザーブ": "Réserve de marche",
    "パワーマティック": "Powermatic", "アニュアルカレンダー": "Calendrier annuel",
    "gmtマスターⅱ": "GMT-Master II", "gmtマスター": "GMT-Master",
    "ぺラゴス": "Pelagos",
    "オイスター": "Oyster", "クラシック": "Classic", "アイコン": "Icon",
    "ウォッチ": "", "腕時計": "", "自動巻き": "Automatique", "自動巻": "Automatique",
    "手巻き": "Remontage manuel", "クォーツ": "Quartz",
    "メンズ": "Homme", "レディース": "Femme", "ボーイズ": "Mixte",
    "新品": "Neuf", "中古": "Occasion", "未使用": "Jamais porté",
    # --- matières / couleurs fréquentes ---
    "ステンレススチール": "Acier", "ステンレス": "Acier", "チタニウム": "Titane",
    "イエローゴールド": "Or jaune", "ピンクゴールド": "Or rose",
    "ローズゴールド": "Or rose", "ホワイトゴールド": "Or blanc",
    "ブラック": "Noir", "ホワイト": "Blanc", "シルバー": "Argent",
    "ブルー": "Bleu", "グリーン": "Vert", "シャンパン": "Champagne",
    "グレー": "Gris", "ピンク": "Rose", "ターコイズ": "Turquoise",
    # --- marques en katakana ---
    "ロレックス": "Rolex", "オメガ": "Omega", "カルティエ": "Cartier",
    "チューダー": "Tudor", "チュードル": "Tudor", "パネライ": "Panerai",
    "ブライトリング": "Breitling", "タグホイヤー": "TAG Heuer",
    "オーデマピゲ": "Audemars Piguet", "パテックフィリップ": "Patek Philippe",
    "ジャガールクルト": "Jaeger-LeCoultre", "ヴァシュロンコンスタンタン": "Vacheron Constantin",
    "ウブロ": "Hublot", "ゼニス": "Zenith", "ブルガリ": "Bulgari",
    "フランクミュラー": "Franck Muller", "エルメス": "Hermès", "シャネル": "Chanel",
}

# on remplace du plus LONG au plus court → « マスタークロノメーター » avant « マスター »
_TERMES = sorted(_GLOSSAIRE.items(), key=lambda kv: -len(kv[0]))


def traduire_nom(modele: str | None) -> str:
    """Nom de montre avec les termes japonais connus traduits en latin."""
    if not modele:
        return ""
    s = modele
    for jp, latin in _TERMES:
        if jp in s:
            s = s.replace(jp, (" " + latin + " ") if latin else " ")
    # espaces multiples / bordures propres
    return re.sub(r"\s+", " ", s).strip(" 　・/-")
