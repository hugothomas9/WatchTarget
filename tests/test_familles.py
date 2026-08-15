from backend.familles import famille_de


def test_familles_japonais_et_anglais():
    assert famille_de("Omega", "スピードマスター レーシング") == "Speedmaster"
    assert famille_de("Omega", "Seamaster Planet Ocean") == "Seamaster"
    assert famille_de("Rolex", "デイトジャスト 41") == "Datejust"
    assert famille_de("Rolex", "コスモグラフ デイトナ") == "Daytona"
    assert famille_de("Tudor", "ブラックベイ 58") == "Black Bay"


def test_famille_inconnue_ou_marque_sans_regles():
    assert famille_de("Rolex", "modèle mystère") == ""
    assert famille_de("Harry Winston", "Avenue") == ""


def test_description_en_secours():
    assert famille_de("Omega", "", "chrono Speedmaster cal.3330") == "Speedmaster"
