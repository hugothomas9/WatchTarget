"""Détaxe japonaise (10%) et calcul du bénéfice d'arbitrage vers la France."""
from . import fx
from . import config

TVA_JP = 0.10  # taxe à la consommation japonaise


def liquidity_score(days_on_market) -> int | None:
    """Note de liquidité 0-10 (10 = se vend le plus vite) à partir du nombre
    médian de jours-pour-vendre WatchCharts. Barème : ≤15 j = 10, puis −1 point
    par tranche de ~15 jours. None si la donnée manque."""
    if days_on_market is None:
        return None
    return max(1, min(10, round(10 - (days_on_market - 15) / 15)))


def marge_nette_import(prix_achat_eur: float, prix_vente_eur: float) -> dict:
    """Marge NETTE d'un import déclaré Japon→France revendu sur plateforme :
    droits de douane + TVA import (sur valeur + droits + port) + port
    + commission de vente. Toutes les hypothèses sont dans config.py."""
    droits = prix_achat_eur * config.DOUANE_PCT
    port = config.PORT_ASSURANCE_EUR
    tva = config.TVA_IMPORT_PCT * (prix_achat_eur + droits + port)
    commission = prix_vente_eur * config.COMMISSION_VENTE_PCT
    couts = droits + tva + port + commission
    return {
        "couts_import_eur": round(couts, 2),
        "marge_nette_eur": round(prix_vente_eur - prix_achat_eur - couts, 2),
    }


def prix_detaxe_jpy(prix_ttc: float | None, prix_ht: float | None) -> float | None:
    """Prix détaxé en yens : le HT (税抜) s'il est donné, sinon TTC / 1.10."""
    if prix_ht is not None:
        return float(prix_ht)
    if prix_ttc is not None:
        return round(float(prix_ttc) / (1 + TVA_JP), 2)
    return None


def compute_benef(prix_ttc, prix_ht, revente_min, revente_max,
                  rate: float, couts_opt: float = 0.0) -> dict:
    """Calcule le prix détaxé en € et le bénéfice min/max vs fourchette de revente FR."""
    detaxe_jpy = prix_detaxe_jpy(prix_ttc, prix_ht)
    if detaxe_jpy is None:
        return {"prix_detaxe_jpy": None, "prix_detaxe_eur": None,
                "benef_min": None, "benef_max": None,
                "benef_pct_min": None, "benef_pct_max": None}
    detaxe_eur = fx.jpy_to_eur(detaxe_jpy, rate=rate)
    cout = detaxe_eur + couts_opt
    benef_min = round(revente_min - cout, 2)
    benef_max = round(revente_max - cout, 2)
    return {
        "prix_detaxe_jpy": detaxe_jpy,
        "prix_detaxe_eur": detaxe_eur,
        "benef_min": benef_min,
        "benef_max": benef_max,
        "benef_pct_min": (benef_min / cout) if cout else None,
        "benef_pct_max": (benef_max / cout) if cout else None,
    }
