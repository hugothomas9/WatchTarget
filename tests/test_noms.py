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
