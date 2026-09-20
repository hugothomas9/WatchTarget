"""Normalisation des marques : fragments longs prioritaires + katakana complétés."""
from backend.brands import normalize_marque


def test_grand_seiko_ne_retombe_pas_sur_seiko():
    # « グランドセイコー » contient « セイコー » : le fragment LONG doit gagner
    assert normalize_marque("グランドセイコー") == "Grand Seiko"
    assert normalize_marque("セイコー") == "Seiko"


def test_marques_katakana_completees():
    assert normalize_marque("パテック フィリップ") == "Patek Philippe"
    assert normalize_marque("ハミルトン／ HAMILTON") == "Hamilton"
    assert normalize_marque("ティソ") == "Tissot"
    assert normalize_marque("カシオ／ CASIO") == "Casio"
    assert normalize_marque("H.モーザー") == "H. Moser & Cie"


def test_chronographe_nest_pas_graff():
    # le piège évité : « クロノグラフ » contient « グラフ » — seul le latin
    # « graff » est un alias, jamais le fragment katakana
    assert normalize_marque("クロノグラフ") == "クロノグラフ"
    assert normalize_marque("GRAFF") == "Graff"
