"""Traduction de l'état en français : anglais, japonais court, rang seul, prose,
et fragments parasites (→ vide)."""
from backend.etat import traduire_etat


def test_bases_anglais_japonais():
    assert traduire_etat("NEW") == "Neuf"
    assert traduire_etat("UNUSED") == "Neuf (jamais porté)"
    assert traduire_etat("USED") == "Occasion"
    assert traduire_etat("中古品") == "Occasion"
    assert traduire_etat("未使用品") == "Neuf (jamais porté)"


def test_rangs():
    assert traduire_etat("中古A") == "Occasion – très bon état (A)"
    assert traduire_etat("中古AB") == "Occasion – bon état (AB)"
    assert traduire_etat("中古B") == "Occasion – état correct (B)"
    assert traduire_etat("Sランク( ランクについて )") == "Occasion – comme neuf (S)"
    assert traduire_etat("Aランク") == "Occasion – très bon état (A)"


def test_prose_longue_watchnian():
    assert traduire_etat(
        "中古 ランク A ケース 僅かな小傷 が見受けられます") == "Occasion – très bon état (A)"


def test_vintage():
    assert traduire_etat("ヴィンテージ/アンティーク") == "Vintage"


def test_fragments_parasites_ignores():
    # fragments captés par erreur (Satin Doll / thème EC-CUBE) → non renseigné
    assert traduire_etat("ですが、外装仕上げ(研磨)を必要とするよ") == ""
    assert traduire_etat("となるclassをON/OFF $pro") == ""
    assert traduire_etat("") == ""
    assert traduire_etat(None) == ""
