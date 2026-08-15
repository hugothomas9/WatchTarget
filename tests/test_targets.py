from backend import targets


def test_load_targets_renvoie_une_liste():
    ts = targets.load_targets()
    assert isinstance(ts, list)
    assert ts, "targets.json doit contenir au moins une cible"
    assert "references" in ts[0]
    assert "revente_fr_min" in ts[0]
