import requests

from backend import fx


def test_jpy_to_eur_applique_le_taux():
    assert fx.jpy_to_eur(100000, rate=0.006) == 600.0


def test_jpy_to_eur_arrondi_2_decimales():
    assert fx.jpy_to_eur(123456, rate=0.0061) == round(123456 * 0.0061, 2)


def test_get_rate_utilise_le_fallback_si_pas_de_cache(monkeypatch, tmp_path):
    from backend import config
    monkeypatch.setattr(config, "JPY_EUR_CACHE", tmp_path / "fx.json")

    def boom(*a, **k):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(fx, "_fetch_remote", boom)
    assert fx.get_rate() == config.JPY_EUR_FALLBACK
