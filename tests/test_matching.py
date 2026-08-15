from backend import matching

TARGETS = [
    {"id": "sub-126610LN", "references": ["126610LN", "126610 LN"]},
    {"id": "speedmaster-311", "references": ["311.30.42.30.01.005"]},
]


def test_normalize_enleve_espaces_casse_prefixe():
    assert matching.normalize_ref("Ref. 126610 LN") == "126610LN"
    assert matching.normalize_ref("référence: 126610-ln") == "126610LN"


def test_match_trouve_la_cible_malgre_variante():
    t = matching.match_target("Rolex Submariner Ref 126610LN", TARGETS)
    assert t["id"] == "sub-126610LN"


def test_match_none_si_aucune_cible():
    assert matching.match_target("Seiko SKX007", TARGETS) is None


def test_pas_de_faux_positif_ref_voisine():
    # 16610LN (cible) ne doit PAS matcher une 116610LN scrapée (frontière de chiffre)
    targets = [{"id": "sub-16610LN", "references": ["16610LN"]}]
    assert matching.match_target("Rolex 116610LN", targets) is None
    assert matching.match_target("Rolex 16610LN", targets)["id"] == "sub-16610LN"


def test_ref_scrapee_courte_ne_matche_pas_dans_la_cible():
    # sens inverse interdit : réf scrapée '001' ne matche pas la cible longue
    targets = [{"id": "x", "references": ["326.30.40.50.01.002"]}]
    assert matching.match_target("001", targets) is None
