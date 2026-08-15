"""Vérification de disponibilité : revisite les montres 'dispo' en base sur
leur site d'origine et met à jour le statut (vendue / retiree / dispo confirmée).

Pourquoi : entre deux collectes, une montre peut se vendre. Les boutiques ne la
retirent pas toutes : watchnian/kamekichi/cywatch/firekids la MARQUENT vendue,
jackroad la sort du listing. Cette passe garde la base honnête.

Usage :
  python -m backend.verify_dispo                    # dispo non revues depuis 7j
  python -m backend.verify_dispo --all              # toutes les dispo
  python -m backend.verify_dispo --boutique "Jack Road"
"""
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor

import requests

from . import db, http_client

DISPO, VENDUE, RETIREE, INCONNU = "dispo", "vendue", "retiree", None


def _status_watchnian(html: str) -> str | None:
    return VENDUE if "price-soldout" in html else DISPO


def _status_jackroad(html: str) -> str | None:
    if "OutOfStock" in html:
        return VENDUE
    if "InStock" in html:
        return DISPO
    return INCONNU


def _status_kamekichi(html: str) -> str | None:
    """Kame-Kichi est une SPA Next.js : le stock fiable est dans __NEXT_DATA__ à
    itemPageData.webItem.stock.inStock. ATTENTION : le HTML contient plusieurs
    "stockType" (widget « bonne affaire » = NEGO, produits liés = OUT) — lire le
    premier au regard naïf donnait des faux positifs massifs. On cible l'article."""
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return INCONNU
    try:
        props = json.loads(m.group(1)).get("props", {}).get("pageProps", {})
    except (ValueError, AttributeError):
        return INCONNU
    # article RETIRÉ : Kame-Kichi redirige /items/{id} vers la page modèle
    # (pageProps sans itemPageData, avec searchPage/modelGroups) → la fiche n'existe plus
    if "itemPageData" not in props:
        return RETIREE
    wi = (props.get("itemPageData") or {}).get("webItem") or {}
    if not wi:
        return INCONNU
    in_stock = wi.get("stock", {}).get("inStock")
    if in_stock is True:
        return DISPO
    if in_stock is False:
        return VENDUE
    st = wi.get("stockType")
    if st == "IN":
        return DISPO
    if st in ("OUT", "SOLDOUT"):
        return VENDUE
    return INCONNU


def _status_firekids(html: str) -> str | None:
    if "取り置き" in html or "SOLD OUT" in html.upper():
        return VENDUE
    if "カートに入れる" in html:
        return DISPO
    return INCONNU


def _status_shopify(html: str) -> str | None:
    """Shopify (Moon Phase / Timeseek / Brand Yukichi) : la dispo fiable est sur la
    PAGE (JSON-LD availability), PAS dans le .json produit individuel qui renvoie
    available=None pour tout (Moon Phase). Fallback = bouton d'achat."""
    m = re.search(r'"availability"\s*:\s*"[^"]*(InStock|OutOfStock)', html)
    if m:
        return DISPO if "InStock" in m.group(1) else VENDUE
    if "カートに入れる" in html or "Add to cart" in html:
        return DISPO
    if re.search(r"売り切れ|Sold\s*out", html, re.I):
        return VENDUE
    return INCONNU


def _status_eccube(html: str) -> str | None:
    """EC-CUBE (Ginza LINKS / The Capital / Satin Doll) : bouton d'achat scopé
    (« カートに入れる » = dispo, « SOLD OUT » = vendu) sinon JSON-LD availability."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    btn = soup.select_one(".ec-blockBtn--action, .ec-productRole__btn")
    if btn:
        t = btn.get_text(" ", strip=True)
        if "カート" in t:
            return DISPO
        if re.search(r"SOLD\s*OUT|売り切|完売|在庫切", t, re.I):
            return VENDUE
    if re.search(r"OutOfStock|SoldOut|Discontinued", html):
        return VENDUE
    if re.search(r"InStock|LimitedAvailability", html):
        return DISPO
    return INCONNU


def _status_jsonld_avail(html: str) -> str | None:
    """Fiches à JSON-LD (MakeShop, Gallery Rare, Yukizaki, GMT) : availability
    InStock/OutOfStock. Fallback texte « 品切れ » / « SOLD »."""
    m = re.search(r'"availability"\s*:\s*"[^"]*(InStock|OutOfStock|SoldOut)', html)
    if m:
        return DISPO if m.group(1) == "InStock" else VENDUE
    if re.search(r"品切れ|SOLD\s*OUT|売り切れ", html, re.I):
        return VENDUE
    return INCONNU


def _status_brandbank(html: str) -> str | None:
    """BrandBank (Color Me Shop) : vendu = fiche retirée (404, géré par check) ou
    balise « soldout » ; sinon présence d'un prix = dispo. Conservateur : INCONNU
    si rien de net (on ne dégrade jamais un statut sans preuve)."""
    if re.search(r'class="gensan"[^>]*>\s*soldout|売り切れ|SOLD\s*OUT', html, re.I):
        return VENDUE
    if re.search(r"product:price:amount|品切れ", html) and "品切れ" not in html:
        return DISPO
    return INCONNU


def _status_housekihiroba(html: str) -> str | None:
    """Housekihiroba : la ligne « 在庫 » de la fiche porte 在庫有り (dispo). Le
    « 在庫なし » se trouve aussi dans un template <script> sur TOUTES les fiches →
    on ne se fie qu'au 在庫有り explicite ; sinon INCONNU (pas de faux positif)."""
    if "在庫有り" in html or "在庫あり" in html:
        return DISPO
    return INCONNU


def status_from_html(boutique: str, html: str) -> str | None:
    """Statut d'une fiche à partir de son HTML (pur → testable)."""
    return {
        "Watchnian": _status_watchnian,
        "Jack Road": _status_jackroad,
        "Kame-Kichi": _status_kamekichi,
        "Fire Kids": _status_firekids,
        "Moon Phase": _status_shopify,
        "Timeseek": _status_shopify,
        "Brand Yukichi": _status_shopify,
        "Ginza LINKS": _status_eccube,
        "The Capital": _status_eccube,
        "Satin Doll": _status_eccube,
        "King's Road": _status_jsonld_avail,
        "7HOURS": _status_jsonld_avail,
        "Gallery Rare": _status_jsonld_avail,
        "Yukizaki": _status_jsonld_avail,
        "GMT": _status_jsonld_avail,
        "BrandBank": _status_brandbank,
        "Housekihiroba": _status_housekihiroba,
    }.get(boutique, lambda h: INCONNU)(html)


# CY Watch : son .json produit expose bien variant.available (contrairement aux 3
# autres Shopify dont le .json renvoie None → on les vérifie par la PAGE, ci-dessus).
_SHOPIFY_JSON = {"CY Watch"}


def check(boutique: str, url: str) -> str | None:
    """Statut actuel d'une montre sur son site (None = indéterminé, on ne touche pas)."""
    try:
        if boutique in _SHOPIFY_JSON:
            data = http_client.get_json(url.rstrip("/") + ".json")
            var = (data.get("product", {}).get("variants") or [{}])[0]
            return DISPO if var.get("available") else VENDUE
        enc = {"Jack Road": "cp932", "Housekihiroba": "cp932",
               "BrandBank": "euc-jp"}.get(boutique)
        # Yukizaki : l'URL stockée est en .com (cache cassé) → on vérifie sur .jp
        if boutique == "Yukizaki":
            url = url.replace("gc-yukizaki.com", "gc-yukizaki.jp")
        html = http_client.get_text(url, encoding=enc)
        return status_from_html(boutique, html)
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code in (404, 410):
            return RETIREE          # la fiche n'existe plus
        return INCONNU
    except Exception:
        return INCONNU


def run(older_than_days: int | None = 7, boutique: str | None = None) -> dict:
    conn = db.connect()
    db.init_db(conn)
    q = "SELECT uid, boutique, url FROM watches WHERE status='dispo'"
    args = []
    if boutique:
        q += " AND boutique=?"
        args.append(boutique)
    if older_than_days is not None:
        q += " AND datetime(last_seen) < datetime('now', ?)"
        args.append(f"-{older_than_days} days")
    rows = conn.execute(q, args).fetchall()
    print(f"{len(rows)} montre(s) dispo à vérifier", flush=True)

    counts = {DISPO: 0, VENDUE: 0, RETIREE: 0, "inconnu": 0}
    ts = db.now_iso()
    with ThreadPoolExecutor(max_workers=6) as ex:
        results = ex.map(lambda r: (r["uid"], check(r["boutique"], r["url"])), rows)
        for i, (uid, st) in enumerate(results, 1):
            if st is None:
                counts["inconnu"] += 1
            else:
                counts[st] += 1
                conn.execute(
                    "UPDATE watches SET status=?, last_seen=? WHERE uid=?",
                    (st, ts, uid))
                # commit immédiat : les résultats arrivent au rythme du réseau,
                # une transaction laissée ouverte bloquerait les autres process
                conn.commit()
            if i % 50 == 0:
                print(f"  ... {i}/{len(rows)} vérifiées "
                      f"(vendues={counts[VENDUE]}, retirées={counts[RETIREE]})",
                      flush=True)
    conn.commit()
    print(f"RESULTAT verify: dispo confirmées={counts[DISPO]} "
          f"vendues={counts[VENDUE]} retirées={counts[RETIREE]} "
          f"indéterminées={counts['inconnu']}", flush=True)
    return counts


def main():
    older = 7
    boutique = None
    if "--all" in sys.argv:
        older = None
    if "--older-than-days" in sys.argv:
        older = int(sys.argv[sys.argv.index("--older-than-days") + 1])
    if "--boutique" in sys.argv:
        boutique = sys.argv[sys.argv.index("--boutique") + 1]
    run(older_than_days=older, boutique=boutique)


if __name__ == "__main__":
    main()
