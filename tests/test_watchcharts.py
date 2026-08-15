import re

from backend.market import WatchChartsSource


def test_extraction_days_volatility():
    # HTML statique type d'une fiche modèle (les 2 métriques y sont)
    html = ("<div>Median Days on Market</div><div>20.8</div>"
            "<span>Market Volatility</span><span>10.2%</span>")
    txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
    d = WatchChartsSource._DAYS_RE.search(txt)
    v = WatchChartsSource._VOL_RE.search(txt)
    assert float(d.group(1)) == 20.8
    assert float(v.group(1)) == 10.2


def test_volatility_regex_variante_sans_market():
    txt = "Volatility 4.4 % Risk Score 54/100"
    assert float(WatchChartsSource._VOL_RE.search(txt).group(1)) == 4.4
