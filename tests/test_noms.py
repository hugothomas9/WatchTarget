"""Traduction des noms de montres : collections, complications, termes composés."""
from backend.noms import traduire_nom


def test_collections():
    assert traduire_nom("スピードマスター") == "Speedmaster"
    assert traduire_nom("デイトナ") == "Daytona"
    assert traduire_nom("ブラックベイ クロノ") == "Black Bay Chrono"


def test_terme_compose_avant_court():
    # « マスタークロノメーター » traduit en entier, pas « マスター » + « クロノメーター »
    assert "Master Chronometer" in traduire_nom("シーマスター コーアクシャル マスタークロノメーター")
    assert "Co-Axial" in traduire_nom("シーマスター コーアクシャル マスタークロノメーター")


def test_garde_reference_et_taille():
    out = traduire_nom("デイトジャスト41")
    assert "Datejust" in out and "41" in out


def test_vide():
    assert traduire_nom("") == ""
    assert traduire_nom(None) == ""


def test_variantes_avec_separateurs():
    """Les composés écrits avec espace/point (オーデマ ピゲ) doivent se traduire
    comme leurs équivalents collés — c'était le gros des trous du glossaire."""
    assert traduire_nom("オーデマ ピゲ ロイヤルオーク") == "Audemars Piguet Royal Oak"
    assert traduire_nom("パテック フィリップ カラトラバ").startswith("Patek Philippe")
    assert "TAG Heuer" in traduire_nom("タグ・ホイヤー カレラ")


def test_termes_frequents_completes():
    assert traduire_nom("マスターコレクション デイト") == "Master Collection Date"
    assert traduire_nom("レベルソ クラシック") == "Reverso Classic"
    assert "Navitimer" in traduire_nom("ナビタイマー B01")
    # les composés longs gagnent sur leurs sous-chaînes
    assert "Datejust" in traduire_nom("デイトジャスト")      # pas « Datejust Date »
    assert traduire_nom("デイデイト") == "Day-Date"
