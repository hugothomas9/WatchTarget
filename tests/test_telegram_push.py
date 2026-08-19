"""Le message push doit être aussi sobre que le bot (aucune fuite de l'edge)."""
from backend import telegram

RATE = 0.0060


def _w(**extra):
    w = {"uid": "jackroad:126500LN:a", "boutique": "jackroad",
         "reference": "126500LN", "marque": "Rolex", "modele": "Daytona",
         "etat": "Occasion A", "prix_ttc": 3210000, "url": "https://ex/a"}
    w.update(extra)
    return w


def test_message_push_titre_puis_annonce_puis_alerte():
    txt = telegram._message(_w(), ["Ma Daytona"], rate=RATE)
    lignes = [l for l in txt.split("\n") if l.strip()]
    assert "Rolex Daytona — 126500LN" in lignes[0]     # titre EN PREMIER
    assert "Occasion A" in txt and "19 260 €" in txt and "jackroad" in txt
    assert "Ma Daytona" in txt                          # quelle alerte a déclenché
    assert "https://ex/a" in txt


def test_message_push_sans_donnee_everywatch_ni_marge():
    txt = telegram._message(
        _w(prix_detaxe_eur=26000.0, ew_median_eur=27400.0, ew_n_sales=57,
           spread_eur=8100.0, benef_min=700.0), ["Ma Daytona"], rate=RATE)
    for interdit in ("26 000", "27 400", "8 100", "Vendu réel", "marge", "détaxé"):
        assert interdit not in txt


def test_message_push_prix_absent():
    txt = telegram._message(_w(prix_ttc=None), ["Ma Daytona"], rate=RATE)
    assert "prix sur demande" in txt


def test_message_push_titre_echappe_html():
    """bot_ui.titre_bloc() renvoie du texte NON échappé — le message part en
    parse_mode=HTML, donc un modèle/marque contenant <, > ou & doit être échappé
    au point d'usage, sinon le message est cassé ou injectable (cf revue Task 9)."""
    txt = telegram._message(
        _w(marque="Rolex <script>", modele="Daytona & Co"), ["Ma Daytona"],
        rate=RATE)
    assert "<script>" not in txt
    assert "&lt;script&gt;" in txt
    assert "Daytona &amp; Co" in txt


def test_message_push_lien_non_duplique():
    """ligne_annonce() se termine déjà par un lien HTML `→ <a href=...>Voir</a>` ;
    le message ne doit pas répéter l'URL une deuxième fois sur sa propre ligne."""
    txt = telegram._message(_w(), ["Ma Daytona"], rate=RATE)
    assert txt.count("https://ex/a") == 1
