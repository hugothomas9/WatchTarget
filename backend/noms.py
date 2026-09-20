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
    # --- complétés d'après le scan des termes non traduits (2026-08). Beaucoup
    # sont des VARIANTES avec espace/point de composés déjà au glossaire (le
    # remplacement est textuel exact) — les longs gagnent grâce au tri par taille.
    "オーデマ ピゲ": "Audemars Piguet", "オーデマ・ピゲ": "Audemars Piguet",
    "パテック フィリップ": "Patek Philippe", "パテック・フィリップ": "Patek Philippe",
    "タグ・ホイヤー": "TAG Heuer", "タグ ホイヤー": "TAG Heuer", "ホイヤー": "Heuer",
    "ハリー・ウィンストン": "Harry Winston", "ハリー ウィンストン": "Harry Winston",
    "ハリーウィンストン": "Harry Winston",
    "フランク・ミュラー": "Franck Muller", "フランク ミュラー": "Franck Muller",
    "マックス・ビル": "Max Bill", "マックスビル": "Max Bill",
    "ビッグ・バン": "Big Bang", "ビッグ バン": "Big Bang",
    "ルイ・エラール": "Louis Erard", "オフィチーネ": "Officine",
    "キングセイコー": "King Seiko", "セイコー": "Seiko",
    "インターナショナル": "International", "カンパニー": "Company",
    # collections / modèles
    "レベルソ": "Reverso", "スーパーオーシャン": "Superocean",
    "ナビタイマー": "Navitimer", "ポルトギーゼ": "Portugieser",
    "ポートフィノ": "Portofino", "オクト": "Octo", "コンクエスト": "Conquest",
    "サブマーシブル": "Submersible", "ロングアイランド": "Long Island",
    "プルミエール": "Première", "アヴェニュー": "Avenue",
    "ハッピースポーツ": "Happy Sport", "ハッピーダイヤモンド": "Happy Diamonds",
    "ハッピー": "Happy", "パイロットウォッチ": "Pilot's Watch",
    "パイロット": "Pilot", "ムーンウォッチ": "Moonwatch", "ムーン": "Moon",
    "マリーナ": "Marina", "マリーン": "Marine",
    "フォーミュラ1": "Formula 1", "フォーミュラ": "Formula",
    "エボリューション": "Evolution", "レディ": "Lady",
    "デイト": "Date", "マスター": "Master", "ドゥエ": "Due", "ドゥ": "de",
    "ミニ": "Mini", "ロイヤル": "Royal", "オーシャン": "Ocean",
    "オリジナルボックス": "box d'origine", "オリジナル": "Original",
    "エディション": "Edition", "限定モデル": "édition limitée", "限定": "limité",
    "モデル": "modèle",
    # complications / technique
    "オートマチック": "Automatic", "オート": "Auto", "メカニカル": "Mechanical",
    "グランド コンプリケーション": "Grande Complication",
    "グランドコンプリケーション": "Grande Complication",
    "コンプリケーション": "Complication", "カレンダー": "Calendar",
    "スケルトン": "Squelette", "セラミック": "Céramique", "マット": "mat",
    # accessoires (fréquents dans les titres 7HOURS / King's Road)
    "ギャランティーカード": "carte de garantie", "ギャランティー": "garantie",
    "ギャランティ": "garantie", "ボックス": "box", "ネックレス": "collier",
    "ブレスレット": "bracelet", "オブ": "of",
    # --- 2e vague du scan (palier suivant de fréquence) ---
    "オフショア": "Offshore", "スティール": "Steel", "クオーツ": "Quartz",
    "アクイス": "Aquis", "フィフティ ファゾムス": "Fifty Fathoms",
    "フィフティファゾムス": "Fifty Fathoms", "フィフティ": "Fifty",
    "ファゾムス": "Fathoms", "スピリット": "Spirit", "アベンジャー": "Avenger",
    "トノウカーベックス": "Tonneau Curvex", "トノーカーベックス": "Tonneau Curvex",
    "トノウ": "Tonneau", "トノー": "Tonneau",
    "セルペンティ": "Serpenti", "ロレアート": "Laureato",
    "ビッグデイト": "Big Date", "ビッグ": "Big",
    "ルナロッサ": "Luna Rossa", "ルナー": "Lunar", "ルナ": "Luna",
    "エクセレンス": "Excellence", "スモールセコンド": "Small Seconds",
    "エル・プリメロ": "El Primero", "エルプリメロ": "El Primero",
    "プリメロ": "Primero", "エル": "El",
    "ジャガー・ルクルト": "Jaeger-LeCoultre", "ジャガー ルクルト": "Jaeger-LeCoultre",
    "ジャガー": "Jaeger", "ルクルト": "LeCoultre",
    "カラトラバ": "Calatrava", "ウニコ": "Unico", "ブレゲ": "Breguet",
    # --- 3e vague (queue de distribution) ---
    "ジュビリー": "Jubilee", "スプリングドライブ": "Spring Drive",
    "ネオマティック": "Neomatik", "ヴィルレ": "Villeret",
    "ジャズマスター": "Jazzmaster", "ジャズ": "Jazz",
    "フランセーズ": "Française", "ヴァンガード": "Vanguard",
    "プレステージ": "Prestige", "イーグル": "Eagle", "ラージ": "Large",
    "デイズ": "Days", "バイ": "by", "リング": "bague",
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
