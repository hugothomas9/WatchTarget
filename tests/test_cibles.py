"""Cibles par mots-clés : matching multilingue (daytona matche デイトナ), référence,
tous-les-mots-clés-requis."""
from backend import cibles


def _w(marque, modele, reference, description=""):
    return {"marque": marque, "modele": modele, "reference": reference,
            "description": description, "famille": ""}


def test_matche_reference_exacte():
    w = _w("Rolex", "デイトナ", "126506A")
    blob = cibles.blob_recherche(w)
    assert cibles.matche("rolex daytona 126506A", blob) is True
    # réf avec casse/espaces différents
    assert cibles.matche("126506a", blob) is True


def test_matche_modele_japonais_via_famille_et_traduction():
    # modèle en katakana → « daytona » doit matcher grâce à famille/nom traduit
    w = _w("Rolex", "デイトナ コスモグラフ", "116500LN")
    blob = cibles.blob_recherche(w)
    assert cibles.matche("daytona", blob) is True
    assert cibles.matche("rolex daytona", blob) is True


def test_tous_les_mots_requis():
    w = _w("Rolex", "サブマリーナ", "126610LN")
    blob = cibles.blob_recherche(w)
    # « daytona » n'est pas une Submariner → pas de match même si rolex OK
    assert cibles.matche("rolex daytona", blob) is False
    assert cibles.matche("rolex submariner", blob) is True


def test_mauvaise_reference_ne_matche_pas():
    w = _w("Rolex", "デイトナ", "126506A")
    blob = cibles.blob_recherche(w)
    assert cibles.matche("rolex daytona 999999", blob) is False


def test_saisie_vide():
    w = _w("Omega", "スピードマスター", "310.30.42.50.01.001")
    blob = cibles.blob_recherche(w)
    assert cibles.matche("", blob) is False
    # omega speedmaster matche via traduction
    assert cibles.matche("omega speedmaster", blob) is True
