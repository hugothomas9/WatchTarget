from backend import pricing


def test_detaxe_utilise_le_ht_si_present():
    assert pricing.prix_detaxe_jpy(prix_ttc=110000, prix_ht=100000) == 100000


def test_detaxe_divise_le_ttc_par_1_1_si_pas_de_ht():
    assert pricing.prix_detaxe_jpy(prix_ttc=110000, prix_ht=None) == 100000.0


def test_detaxe_none_si_aucun_prix():
    assert pricing.prix_detaxe_jpy(None, None) is None


def test_compute_benef_complet():
    r = pricing.compute_benef(
        prix_ttc=1100000, prix_ht=None,
        revente_min=9500, revente_max=11000,
        rate=0.006, couts_opt=0.0,
    )
    assert r["prix_detaxe_jpy"] == 1000000.0
    assert r["prix_detaxe_eur"] == 6000.0
    assert r["benef_min"] == 3500.0
    assert r["benef_max"] == 5000.0
    assert round(r["benef_pct_min"], 4) == round(3500 / 6000, 4)


def test_liquidity_score():
    assert pricing.liquidity_score(15) == 10
    assert pricing.liquidity_score(10) == 10   # plafonné
    assert pricing.liquidity_score(25) == 9
    assert pricing.liquidity_score(60) == 7
    assert pricing.liquidity_score(90) == 5
    assert pricing.liquidity_score(200) == 1   # plancher
    assert pricing.liquidity_score(None) is None


def test_marge_nette_import_mode_declare(monkeypatch):
    # scénario import déclaré : douane 450 + TVA 20%×(10000+450+120)=2114
    # + port 120 + commission 6,5%×13000=845 → coûts 3529 → nette = -529
    from backend import config
    monkeypatch.setattr(config, "DOUANE_PCT", 0.045)
    monkeypatch.setattr(config, "TVA_IMPORT_PCT", 0.20)
    monkeypatch.setattr(config, "PORT_ASSURANCE_EUR", 120)
    monkeypatch.setattr(config, "COMMISSION_VENTE_PCT", 0.065)
    r = pricing.marge_nette_import(10000, 13000)
    assert r["couts_import_eur"] == 3529.0
    assert r["marge_nette_eur"] == -529.0


def test_marge_nette_mode_valise(monkeypatch):
    # mode valise (défaut Hugo) : seule la commission de vente compte
    from backend import config
    monkeypatch.setattr(config, "DOUANE_PCT", 0.0)
    monkeypatch.setattr(config, "TVA_IMPORT_PCT", 0.0)
    monkeypatch.setattr(config, "PORT_ASSURANCE_EUR", 0)
    monkeypatch.setattr(config, "COMMISSION_VENTE_PCT", 0.065)
    r = pricing.marge_nette_import(10000, 13000)
    assert r["couts_import_eur"] == 845.0          # 6,5% de 13 000
    assert r["marge_nette_eur"] == 2155.0          # 3000 − 845


def test_compute_benef_soustrait_couts_optionnels():
    r = pricing.compute_benef(
        prix_ttc=1100000, prix_ht=None,
        revente_min=9500, revente_max=11000,
        rate=0.006, couts_opt=500.0,
    )
    assert r["benef_min"] == 3000.0
