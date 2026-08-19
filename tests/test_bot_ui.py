"""Rendu du bot Telegram — module PUR : aucun réseau, aucune DB."""
from backend import bot_ui

RATE = 0.0060      # 1 JPY = 0.006 EUR → 3 210 000 ¥ = 19 260 €


def w(uid="jackroad:126500LN:a", ref="126500LN", prix_ttc=3210000, etat="Occasion A",
      boutique="jackroad", marque="Rolex", modele="Daytona", images=None, **extra):
    d = {"uid": uid, "reference": ref, "prix_ttc": prix_ttc, "etat": etat,
         "boutique": boutique, "marque": marque, "modele": modele,
         "url": "https://ex/" + uid, "images": images or ["https://img/1.jpg"]}
    d.update(extra)
    return d


def test_fmt_eur_espace_milliers():
    assert bot_ui.fmt_eur(19260.0) == "19 260 €"
    assert bot_ui.fmt_eur(None) == "prix sur demande"


def test_preparer_montres_convertit_le_prix_boutique():
    m = bot_ui.preparer_montres([w()], RATE)[0]
    assert m["prix_eur"] == 19260
    assert m["image"] == "https://img/1.jpg"


def test_preparer_montres_accepte_les_images_en_json():
    """`watches.images` est stocké en JSON sérialisé : la photo doit être retrouvée."""
    m = bot_ui.preparer_montres([w(images='["https://img/9.jpg"]')], RATE)[0]
    assert m["image"] == "https://img/9.jpg"
    assert bot_ui.preparer_montres([w(images="pas du json")], RATE)[0]["image"] is None


def test_preparer_montres_prix_absent():
    m = bot_ui.preparer_montres([w(prix_ttc=None)], RATE)[0]
    assert m["prix_eur"] is None
    assert "prix sur demande" in bot_ui.ligne_annonce(m)


def test_preparer_montres_ne_retombe_jamais_sur_le_detaxe():
    """Un prix boutique manquant ne doit PAS être remplacé par un prix détaxé."""
    m = bot_ui.preparer_montres(
        [w(prix_ttc=None, prix_detaxe_eur=26000.0, prix_detaxe_jpy=4000000.0)], RATE)[0]
    assert m["prix_eur"] is None
    assert "26 000" not in bot_ui.ligne_annonce(m)


def test_preparer_montres_supprime_les_champs_interdits():
    m = bot_ui.preparer_montres(
        [w(prix_detaxe_eur=26000.0, ew_median_eur=27400.0, spread_eur=8100.0,
           benef_min=700.0)], RATE)[0]
    for interdit in bot_ui.CHAMPS_INTERDITS:
        assert interdit not in m


def test_titre_bloc_marque_modele_reference():
    assert bot_ui.titre_bloc(w()) == "Rolex Daytona — 126500LN"


def test_titre_bloc_sans_reference():
    assert bot_ui.titre_bloc(w(ref="")) == "Rolex Daytona"


def test_ligne_annonce_sobre():
    m = bot_ui.preparer_montres([w()], RATE)[0]
    ligne = bot_ui.ligne_annonce(m)
    assert "Occasion A" in ligne and "19 260 €" in ligne and "jackroad" in ligne
    assert 'href="https://ex/jackroad:126500LN:a"' in ligne


def test_ligne_annonce_echappe_le_html():
    m = bot_ui.preparer_montres([w(boutique="A & B <shop>")], RATE)[0]
    assert "A &amp; B &lt;shop&gt;" in bot_ui.ligne_annonce(m)


def test_grouper_par_reference_et_tri_prix_croissant():
    montres = bot_ui.preparer_montres([
        w(uid="a", ref="126500LN", prix_ttc=3500000),
        w(uid="b", ref="116500LN", prix_ttc=3000000),
        w(uid="c", ref="126500LN", prix_ttc=3210000),
    ], RATE)
    blocs = bot_ui.grouper_par_reference(montres)
    # blocs triés par prix mini croissant ; 116500LN (18 000 €) avant 126500LN (19 260 €)
    assert [b["titre"] for b in blocs] == ["Rolex Daytona — 116500LN",
                                           "Rolex Daytona — 126500LN"]
    # annonces triées par prix croissant à l'intérieur du bloc
    assert [a["prix_eur"] for a in blocs[1]["annonces"]] == [19260, 21000]


def test_grouper_montres_sans_prix_en_dernier():
    montres = bot_ui.preparer_montres([
        w(uid="a", ref="AAA", prix_ttc=None),
        w(uid="b", ref="BBB", prix_ttc=3000000),
    ], RATE)
    blocs = bot_ui.grouper_par_reference(montres)
    assert [b["titre"] for b in blocs] == ["Rolex Daytona — BBB", "Rolex Daytona — AAA"]


def test_legende_bloc_titre_puis_annonces():
    montres = bot_ui.preparer_montres([w(uid="a"), w(uid="b", prix_ttc=3500000)], RATE)
    legende = bot_ui.legende_bloc(bot_ui.grouper_par_reference(montres)[0])
    lignes = legende.split("\n")
    assert lignes[0] == "<b>Rolex Daytona — 126500LN</b>"
    assert len(lignes) == 3        # titre + 2 annonces


def test_legende_bloc_plafonne_les_annonces():
    montres = bot_ui.preparer_montres(
        [w(uid=f"u{i}", prix_ttc=3000000 + i) for i in range(40)], RATE)
    legende = bot_ui.legende_bloc(bot_ui.grouper_par_reference(montres)[0])
    assert legende.startswith("<b>Rolex Daytona — 126500LN</b>")   # titre préservé
    assert "…et 32 autres" in legende                             # 40 - 8
    assert len(legende) <= bot_ui.LIMITE_LEGENDE


def test_legende_bloc_titre_survit_aux_annonces_tres_longues():
    """Cas limite : des boutiques/états à rallonge feraient dépasser 1024 caractères.
    Le titre doit rester ; ce sont les annonces qui sont coupées."""
    montres = bot_ui.preparer_montres(
        [w(uid=f"u{i}", boutique="B" * 90, etat="E" * 90, prix_ttc=3000000 + i)
         for i in range(8)], RATE)
    legende = bot_ui.legende_bloc(bot_ui.grouper_par_reference(montres)[0])
    assert legende.startswith("<b>Rolex Daytona — 126500LN</b>")
    assert len(legende) <= bot_ui.LIMITE_LEGENDE


def test_aucun_champ_interdit_dans_le_rendu():
    """Barrière anti-régression : même nourri de données EveryWatch, le rendu n'en
    laisse rien passer."""
    montres = bot_ui.preparer_montres(
        [w(prix_detaxe_eur=26000.0, ew_median_eur=27400.0, ew_n_sales=57,
           spread_eur=8100.0, benef_min=700.0, benef_max=900.0)], RATE)
    legende = bot_ui.legende_bloc(bot_ui.grouper_par_reference(montres)[0])
    for valeur in ("26 000", "27 400", "8 100", "700", "57 ventes", "EveryWatch"):
        assert valeur not in legende
