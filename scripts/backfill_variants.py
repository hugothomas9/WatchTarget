"""Backfill cadran (文字盤) + matière (素材/ケース) sur les montres DÉJÀ en base
(collectées avant que les connecteurs ne capturent ces champs).

Scope = montres d'OPPORTUNITÉS (les seules où la précision du pricing EveryWatch
compte) : on re-lit la fiche de chaque montre sans cadran et on extrait les deux
champs par regex générique sur le texte rendu (les libellés 文字盤/素材/ケース sont
affichés sur toutes les boutiques). Best-effort : fiche disparue ou libellé absent
→ on passe, l'agrégat réf EveryWatch reste le secours.

Reprenable : les montres déjà backfillées (raw['cadran'] non vide) sont sautées.

Usage :  python -m scripts.backfill_variants [--limit N] [--all-rolex]
"""
import json
import sys
import time

import re

from backend import db, config, http_client, variants
from backend.connectors.base import strip_html

# encodage spécifique par boutique (le reste = UTF-8 auto)
_ENCODINGS = {"Jack Road": "cp932"}

# variantes de libellé selon la boutique : « 文字盤 シルバー » (watchnian),
# « 文字盤カラー グレー » (jackroad), « ブラック文字盤 » (valeur AVANT le label).
# Chaque candidat est VALIDÉ par normalisation (sinon le texte descriptif
# « 文字盤の模様が… » et « ケース径 » = diamètre pollueraient tout).
_DIAL_RES = (re.compile(r"文字盤(?:カラー|の?色)?\s*[：:]?\s*([^\s　、,<\n]{1,14})"),
             # inversé : « ブラック文字盤 ». Max 8 chars (ターコイズブルー) sinon le
             # pattern gobe la phrase descriptive qui précède le mot 文字盤.
             re.compile(r"([^\s　、,<\n]{1,8})文字盤"))
_MAT_RES = (re.compile(r"(?:ケース素材|素材|ケース)\s*[：:]?\s*([^\s　、,<\n]{1,14})"),)


def _first_valid(text, regexes, normalize):
    for rx in regexes:
        for m in rx.finditer(text):
            if normalize(m.group(1)):
                return m.group(1)
    return ""


def extract(boutique: str, url: str) -> tuple[str, str]:
    html = http_client.get_text(url, encoding=_ENCODINGS.get(boutique))
    text = strip_html(html)
    return (_first_valid(text, _DIAL_RES, variants.normalize_dial),
            _first_valid(text, _MAT_RES, variants.normalize_material))


def main():
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    conn = db.connect()
    db.init_db(conn)

    targets = {}
    for o in db.get_opportunities(conn, config.SPREAD_MIN_EUR,
                                  config.LIQUIDITY_MIN_LISTINGS):
        targets[o["uid"]] = (o["boutique"], o["url"], o["raw"])
    if "--all-rolex" in sys.argv:
        for w in conn.execute("SELECT uid, boutique, url, raw FROM watches "
                              "WHERE status='dispo' AND marque='Rolex'"):
            targets.setdefault(w["uid"], (w["boutique"], w["url"], w["raw"]))

    todo = []
    for uid, (boutique, url, raw) in targets.items():
        try:
            r = json.loads(raw or "{}") if isinstance(raw, str) else (raw or {})
        except ValueError:
            r = {}
        if not r.get("cadran") and not r.get("variants_backfill"):
            todo.append((uid, boutique, url, r))
    if limit:
        todo = todo[:limit]
    print(f"{len(todo)} montre(s) à backfiller", flush=True)

    ok = ko = 0
    for i, (uid, boutique, url, r) in enumerate(todo, 1):
        try:
            cadran, matiere = extract(boutique, url)
        except Exception:
            ko += 1
            continue           # erreur réseau : PAS marquée → retentée au prochain run
        r["variants_backfill"] = 1        # tentée (même sans résultat) → pas de re-fetch
        if not cadran and not matiere:
            ko += 1
            conn.execute("UPDATE watches SET raw=? WHERE uid=?",
                         (json.dumps(r, ensure_ascii=False), uid))
            conn.commit()
            continue
        r["cadran"] = cadran
        r["matiere"] = r.get("matiere") or matiere
        conn.execute("UPDATE watches SET raw=? WHERE uid=?",
                     (json.dumps(r, ensure_ascii=False), uid))
        conn.commit()          # commit par item : interruptible sans perte
        ok += 1
        if i % 20 == 0:
            print(f"  ... {i}/{len(todo)} (ok={ok}, sans={ko})", flush=True)
        time.sleep(0.2)
    print(f"RESULTAT backfill ok={ok} sans_info={ko}", flush=True)


if __name__ == "__main__":
    main()
