from backend import variants


def test_normalize_dial_jp_et_en():
    assert variants.normalize_dial("シルバー") == "silver"
    assert variants.normalize_dial("Silver dial") == "silver"
    assert variants.normalize_dial("シャンパン") == "champagne"
    assert variants.normalize_dial("ターコイズ") == "turquoise"
    assert variants.normalize_dial("") == ""
    assert variants.normalize_dial("インコネル") == ""   # inconnu → vide


def test_dial_mother_of_pearl_prime_sur_white():
    # « 白蝶貝 » (nacre) ne doit PAS être lu comme « 白 » (white)
    assert variants.normalize_dial("白蝶貝") == "mother of pearl"
    assert variants.normalize_dial("ホワイト") == "white"


def test_normalize_material():
    assert variants.normalize_material("ステンレス") == "steel"
    assert variants.normalize_material("Stainless steel") == "steel"
    assert variants.normalize_material("イエローゴールド") == "yellow gold"
    # two-tone : acier + or ensemble (EveryWatch « Stainless steel and 18k yellow gold »)
    assert variants.normalize_material("ステンレス × イエローゴールド") == "two-tone"
    assert variants.normalize_material("Stainless steel and 18k yellow gold") == "two-tone"


def test_extraction_depuis_specs():
    specs = {"文字盤": "シルバー", "ケース": "ステンレス", "ベゼル": "ダイヤ"}
    assert variants.dial_from_specs(specs) == "シルバー"
    assert variants.material_from_specs(specs) == "ステンレス"
    # normalisation bout en bout
    assert variants.normalize_dial(variants.dial_from_specs(specs)) == "silver"
    assert variants.normalize_material(variants.material_from_specs(specs)) == "steel"


def test_material_prefere_case_sur_bracelet():
    # ケース (boîtier) doit être choisi, pas confondu avec un autre label
    specs = {"型番": "279384RBR", "ケース": "ステンレス"}
    assert variants.normalize_material(variants.material_from_specs(specs)) == "steel"
