"""Normalisation des FAMILLES de modèles (sous-catégories par marque).

Le champ `modele` scrapé est du texte japonais/anglais bruité ; on le ramène à
une ligne canonique (Speedmaster, Submariner…) pour le filtre cascade
Marque → Ligne du front. Famille inconnue → "" (affichée sous « Autres »)."""

# marque canonique -> [(famille, [fragments détectés, minuscule, JP+EN])]
_FAMILLES = {
    "Omega": [
        ("Speedmaster", ["スピードマスター", "speedmaster"]),
        ("Seamaster", ["シーマスター", "seamaster", "プラネットオーシャン",
                       "planet ocean", "アクアテラ", "aqua terra"]),
        ("Constellation", ["コンステレーション", "constellation"]),
        ("De Ville", ["デ・ヴィル", "デヴィル", "デビル", "de ville", "deville"]),
        ("Railmaster", ["レイルマスター", "railmaster"]),
        ("Globemaster", ["グローブマスター", "globemaster"]),
    ],
    "Rolex": [
        ("Submariner", ["サブマリーナ", "submariner"]),
        ("Datejust", ["デイトジャスト", "datejust"]),
        ("Daytona", ["デイトナ", "daytona", "コスモグラフ", "cosmograph"]),
        ("GMT-Master", ["gmtマスター", "gmt-master", "gmtmaster", "gmt マスター"]),
        ("Explorer", ["エクスプローラー", "explorer"]),
        ("Sea-Dweller", ["シードゥエラー", "sea-dweller", "seadweller",
                         "ディープシー", "deepsea"]),
        ("Oyster Perpetual", ["オイスターパーペチュアル", "oyster perpetual"]),
        ("Day-Date", ["デイデイト", "day-date", "daydate"]),
        ("Sky-Dweller", ["スカイドゥエラー", "sky-dweller"]),
        ("Milgauss", ["ミルガウス", "milgauss"]),
        ("Air-King", ["エアキング", "air-king", "airking"]),
        ("Yacht-Master", ["ヨットマスター", "yacht-master", "yachtmaster"]),
        ("Cellini", ["チェリーニ", "cellini"]),
    ],
    "Tudor": [
        ("Black Bay", ["ブラックベイ", "black bay"]),
        ("Pelagos", ["ペラゴス", "pelagos"]),
        ("Ranger", ["レンジャー", "ranger"]),
        ("Royal", ["ロイヤル", "royal"]),
    ],
    "Cartier": [
        ("Santos", ["サントス", "santos"]),
        ("Tank", ["タンク", "tank"]),
        ("Ballon Bleu", ["バロンブルー", "ballon bleu"]),
        ("Pasha", ["パシャ", "pasha"]),
        ("Panthère", ["パンテール", "panthere", "panthère"]),
        ("Calibre", ["カリブル", "calibre"]),
    ],
    "Patek Philippe": [
        ("Nautilus", ["ノーチラス", "nautilus"]),
        ("Aquanaut", ["アクアノート", "aquanaut"]),
        ("Calatrava", ["カラトラバ", "calatrava"]),
        ("Complications", ["コンプリケーション", "complication"]),
    ],
    "Audemars Piguet": [
        ("Royal Oak", ["ロイヤルオーク", "royal oak"]),
    ],
    "IWC": [
        ("Portugieser", ["ポルトギーゼ", "portugieser", "portuguese"]),
        ("Pilot", ["パイロット", "pilot", "マーク", "mark x"]),
        ("Portofino", ["ポートフィノ", "portofino"]),
        ("Aquatimer", ["アクアタイマー", "aquatimer"]),
        ("Ingenieur", ["インヂュニア", "インジュニア", "ingenieur"]),
    ],
    "Breitling": [
        ("Navitimer", ["ナビタイマー", "navitimer"]),
        ("Chronomat", ["クロノマット", "chronomat"]),
        ("Superocean", ["スーパーオーシャン", "superocean"]),
        ("Avenger", ["アベンジャー", "avenger"]),
        ("Premier", ["プレミエ", "premier"]),
    ],
    "Panerai": [
        ("Luminor", ["ルミノール", "luminor"]),
        ("Radiomir", ["ラジオミール", "radiomir"]),
        ("Submersible", ["サブマーシブル", "submersible"]),
    ],
    "Tag Heuer": [
        ("Carrera", ["カレラ", "carrera"]),
        ("Monaco", ["モナコ", "monaco"]),
        ("Aquaracer", ["アクアレーサー", "aquaracer"]),
        ("Formula 1", ["フォーミュラ", "formula"]),
    ],
    "Grand Seiko": [],
    "Seiko": [
        ("Prospex", ["プロスペックス", "prospex"]),
        ("Presage", ["プレザージュ", "presage"]),
        ("Astron", ["アストロン", "astron"]),
        ("King Seiko", ["キングセイコー", "king seiko"]),
    ],
}


def famille_de(marque: str, modele: str, description: str = "") -> str:
    """Famille canonique d'une montre, déduite du modèle (+description en secours)."""
    regles = _FAMILLES.get(marque)
    if not regles:
        return ""
    texte = f"{modele} {description}".lower()
    for famille, fragments in regles:
        if any(f in texte for f in fragments):
            return famille
    return ""
