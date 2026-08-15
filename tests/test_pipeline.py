from backend import pipeline

TARGETS = [{
    "id": "sub-126610LN", "references": ["126610LN"],
    "revente_fr_min": 9500, "revente_fr_max": 11000, "couts_optionnels_eur": 0,
}]


def test_enrich_montre_ciblee():
    w = {"reference": "Ref 126610LN", "prix_ttc": 1100000, "prix_ht": None}
    out = pipeline.enrich(dict(w), TARGETS, rate=0.006)
    assert out["target_id"] == "sub-126610LN"
    assert out["prix_detaxe_eur"] == 6000.0
    assert out["benef_min"] == 3500.0


def test_enrich_montre_hors_cible():
    w = {"reference": "Seiko SKX007", "prix_ttc": 50000, "prix_ht": None}
    out = pipeline.enrich(dict(w), TARGETS, rate=0.006)
    assert out["target_id"] is None
    assert out["benef_min"] is None
