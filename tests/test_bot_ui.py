"""Rendu du bot Telegram — module PUR : aucun réseau, aucune DB."""
import re

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


def test_legende_bloc_titre_seul_trop_long_est_tronque():
    """Cas extrême : le TITRE seul (marque/modèle/référence à rallonge) dépasse déjà
    1024 caractères une fois entouré de <b></b> et échappé — même sans aucune annonce
    à côté. La légende ne doit JAMAIS dépasser LIMITE_LEGENDE : en dernier recours,
    après avoir retiré toutes les annonces, c'est le titre lui-même qui est raccourci
    (une légende tronquée vaut mieux qu'une légende invalide que Telegram rejette)."""
    montres = bot_ui.preparer_montres(
        [w(marque="A" * 600, modele="B" * 600, ref="C" * 600)], RATE)
    legende = bot_ui.legende_bloc(bot_ui.grouper_par_reference(montres)[0])
    assert len(legende) <= bot_ui.LIMITE_LEGENDE
    assert legende.startswith("<b>")
    assert legende.endswith("…</b>")


def test_legende_bloc_titre_tronque_ne_coupe_pas_une_entite_html():
    """Le titre raccourci en dernier recours ne doit jamais couper une entité HTML
    (`&amp;`, `&lt;`, …) en plein milieu : la coupe se fait sur le texte brut, avant
    l'échappement, jamais sur la chaîne déjà échappée."""
    montres = bot_ui.preparer_montres(
        [w(marque="&" * 500, modele="B" * 500, ref="C" * 500)], RATE)
    legende = bot_ui.legende_bloc(bot_ui.grouper_par_reference(montres)[0])
    assert len(legende) <= bot_ui.LIMITE_LEGENDE
    interieur = legende[len("<b>"):-len("</b>")]
    if interieur.endswith("…"):
        interieur = interieur[:-1]
    # toute séquence commençant par « & » doit être une entité complète (finit par ';')
    for entite in re.finditer(r"&[a-zA-Z#0-9]*;?", interieur):
        assert entite.group().endswith(";"), f"entité HTML coupée : {entite.group()!r}"


def test_legende_bloc_titre_survit_toujours_quand_les_annonces_debordent():
    """Non-régression explicite du ruling : quand ce sont les annonces qui font
    déborder (titre raisonnable), le titre reste ENTIER, jamais tronqué — seul le cas
    où le titre lui-même dépasse justifie de le raccourcir."""
    montres = bot_ui.preparer_montres(
        [w(uid=f"u{i}", boutique="B" * 90, etat="E" * 90, prix_ttc=3000000 + i)
         for i in range(8)], RATE)
    legende = bot_ui.legende_bloc(bot_ui.grouper_par_reference(montres)[0])
    assert legende.startswith("<b>Rolex Daytona — 126500LN</b>")
    assert "\n<b>" not in legende  # le titre complet est bien la première ligne, intact
    assert len(legende) <= bot_ui.LIMITE_LEGENDE


def _cbs(ecran):
    return [b["callback_data"] for ligne in ecran["keyboard"] for b in ligne]


def test_ecran_accueil():
    e = bot_ui.ecran_accueil(3)
    assert "WatchTarget" in e["text"]
    assert "Mes alertes (3)" in str(e["keyboard"])
    assert "new" in _cbs(e) and "list" in _cbs(e) and "help" in _cbs(e)
    assert e["photo"] is None


def test_ecran_alertes_actives_et_en_pause():
    e = bot_ui.ecran_alertes([
        {"id": 1, "libelle": "Ma Daytona", "mots_cles": "rolex daytona",
         "actif": 1, "nb": 12},
        {"id": 2, "libelle": "", "mots_cles": "rolex submariner", "actif": 0, "nb": 41},
    ])
    libelles = [b["text"] for ligne in e["keyboard"] for b in ligne]
    assert "🟢 Ma Daytona — 12 montres" in libelles
    assert "⏸ rolex submariner — 41 montres" in libelles     # libellé vide → mots-clés
    assert "a:1" in _cbs(e) and "a:2" in _cbs(e)


def test_ecran_alertes_vide_invite_a_creer():
    e = bot_ui.ecran_alertes([])
    assert "aucune alerte" in e["text"].lower()
    assert "new" in _cbs(e)


def test_ecran_alerte_actions_et_pause():
    a = {"id": 7, "libelle": "Ma Daytona", "mots_cles": "rolex daytona",
         "actif": 1, "cree_le": "2026-08-16T10:00:00+00:00"}
    e = bot_ui.ecran_alerte(a, nb_montres=12, nb_refs=4)
    assert "Ma Daytona" in e["text"] and "rolex daytona" in e["text"]
    assert "12 montres" in e["text"] and "4 référence" in e["text"]
    for cb in ("v:7:1", "a:7:ren", "a:7:kw", "a:7:toggle", "a:7:del", "list"):
        assert cb in _cbs(e)
    assert "pause" in str(e["keyboard"]).lower()
    # alerte en pause → le bouton propose de réactiver
    e2 = bot_ui.ecran_alerte({**a, "actif": 0}, nb_montres=0, nb_refs=0)
    assert "réactiver" in str(e2["keyboard"]).lower()


def test_ecran_confirm_suppression():
    e = bot_ui.ecran_confirm_suppression({"id": 7, "libelle": "Ma Daytona",
                                          "mots_cles": "rolex daytona"})
    assert "définitive" in e["text"]
    assert "a:7:del!" in _cbs(e) and "a:7" in _cbs(e)


def test_callback_data_toujours_sous_64_octets():
    ecrans = [
        bot_ui.ecran_accueil(3),
        bot_ui.ecran_alertes([{"id": 999999, "libelle": "x" * 80,
                               "mots_cles": "y" * 80, "actif": 1, "nb": 3}]),
        bot_ui.ecran_alerte({"id": 999999, "libelle": "x" * 80, "mots_cles": "y" * 80,
                             "actif": 1, "cree_le": "2026-08-16T10:00:00+00:00"}, 5, 2),
        bot_ui.ecran_confirm_suppression({"id": 999999, "libelle": "x" * 80,
                                          "mots_cles": ""}),
        bot_ui.ecran_aide(),
    ]
    for e in ecrans:
        assert len(e["text"]) <= bot_ui.LIMITE_TEXTE
        for cb in _cbs(e):
            assert len(cb.encode()) <= 64, cb


def test_ecran_alerte_echappe_le_html():
    """Un libellé contenant du HTML ne doit pas être interprété par Telegram
    (parse_mode=HTML) : il est échappé."""
    e = bot_ui.ecran_alerte({"id": 1, "libelle": "<b>hack</b>", "mots_cles": "a & b",
                             "actif": 1, "cree_le": ""}, 0, 0)
    assert "&lt;b&gt;hack&lt;/b&gt;" in e["text"]
    assert "<b>hack</b>" not in e["text"]
    assert "a &amp; b" in e["text"]


ALERTE = {"id": 7, "libelle": "Ma Daytona", "mots_cles": "rolex daytona", "actif": 1}


def _stock(n_refs, par_ref=2):
    montres = []
    for i in range(n_refs):
        for j in range(par_ref):
            montres.append(w(uid=f"u{i}-{j}", ref=f"REF{i:03d}",
                             prix_ttc=3000000 + i * 100000 + j))
    return bot_ui.preparer_montres(montres, RATE)


def test_page_montres_entete_et_pagination():
    p = bot_ui.page_montres(ALERTE, _stock(7), page=1)
    assert "Ma Daytona" in p["entete"]
    assert "14 annonces" in p["entete"] and "7 réf" in p["entete"]
    assert "page 1/3" in p["entete"]                      # 7 réfs / 3 par page
    assert "vérifié quotidiennement" in p["entete"]
    assert len(p["blocs"]) == bot_ui.REFS_PAR_PAGE
    assert p["pages"] == 3


def test_page_montres_navigation_bornee():
    p1 = bot_ui.page_montres(ALERTE, _stock(7), page=1)
    cbs1 = [b["callback_data"] for l in p1["keyboard"] for b in l]
    assert "v:7:2" in cbs1 and "v:7:0" not in cbs1        # pas de « Préc » en page 1
    p3 = bot_ui.page_montres(ALERTE, _stock(7), page=3)
    cbs3 = [b["callback_data"] for l in p3["keyboard"] for b in l]
    assert "v:7:2" in cbs3 and "v:7:4" not in cbs3        # pas de « Suivant » en fin
    assert "a:7" in cbs3                                  # retour à l'alerte
    assert len(p3["blocs"]) == 1                          # 7 = 3 + 3 + 1


def test_page_montres_page_hors_bornes_est_ramenee():
    p = bot_ui.page_montres(ALERTE, _stock(2), page=99)
    assert p["page"] == 1 and p["pages"] == 1 and len(p["blocs"]) == 2


def test_page_montres_chaque_bloc_a_titre_et_legende_valide():
    p = bot_ui.page_montres(ALERTE, _stock(3), page=1)
    for bloc in p["blocs"]:
        assert bloc["caption"].startswith("<b>")
        assert len(bloc["caption"]) <= bot_ui.LIMITE_LEGENDE
        assert bloc["photo"] == "https://img/1.jpg"


def test_ecran_alerte_vide():
    e = bot_ui.ecran_alerte_vide(ALERTE)
    assert "Ma Daytona" in e["text"]
    assert "a:7" in [b["callback_data"] for l in e["keyboard"] for b in l]
