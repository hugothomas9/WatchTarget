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


def test_message_push_quatre_lignes_distinctes():
    """Gabarit restauré en revue (round 1) : titre / annonce / alerte / lien,
    quatre lignes distinctes — pas de lien inline fusionné dans l'annonce."""
    txt = telegram._message(_w(), ["Ma Daytona"], rate=RATE)
    lignes = [l for l in txt.split("\n") if l.strip()]
    assert lignes == [
        "🎯 <b>Rolex Daytona — 126500LN</b>",
        "Occasion A · 19 260 € · jackroad",
        "Alerte : Ma Daytona",
        "https://ex/a",
    ]


def test_message_push_pas_de_lien_inline_dans_annonce():
    """`bot_ui.ligne_annonce` termine normalement par `→ <a href=...>Voir</a>` ;
    la ligne d'annonce du message push ne doit pas le contenir (URL neutralisée),
    le lien étant porté par sa propre ligne, nue, à la fin (plus tappable/copiable)."""
    txt = telegram._message(_w(), ["Ma Daytona"], rate=RATE)
    lignes = [l for l in txt.split("\n") if l.strip()]
    annonce = lignes[1]
    assert "<a href" not in annonce and "Voir" not in annonce


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


def test_message_push_libelle_alerte_echappe_html():
    """`libelles` vient du texte libre saisi par l'utilisateur dans le bot
    (`c['libelle']` ou `c['mots_cles']`) : jamais échappé en amont. Une alerte
    nommée « Sub <5000€ » ou « Daytona & GMT » ferait échouer sendMessage en
    HTML et perdrait la notification en silence (finding revue, round 1)."""
    txt = telegram._message(_w(), ["Sub <5000€ & GMT"], rate=RATE)
    assert "<5000€" not in txt
    assert "&lt;5000€" in txt
    assert "GMT &amp; " in txt or "&amp; GMT" in txt or "&amp;" in txt


def test_message_push_lien_non_duplique():
    """L'URL n'apparaît qu'une seule fois dans le message (sur sa propre ligne),
    jamais aussi en href d'un lien inline dans l'annonce."""
    txt = telegram._message(_w(), ["Ma Daytona"], rate=RATE)
    assert txt.count("https://ex/a") == 1
