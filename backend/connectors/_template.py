"""Template de connecteur boutique. Copier, adapter les 3 hooks, enregistrer
dans registry.py. NE PAS appeler directement (URLs fictives).

L'entonnoir (dispo → récent → full set), la reprise instantanée et la collecte
parallèle sont fournis par BaseConnector : n'implémenter QUE les hooks.
"""
from bs4 import BeautifulSoup

from .. import http_client
from .base import BaseConnector, watch, strip_html, make_uid


class TemplateConnector(BaseConnector):
    boutique = "Template"

    def brands_to_scan(self):
        """Identifiants internes au site des catégories/marques à parcourir."""
        return self.entry.get("brands", ["omega"])          # À ADAPTER

    def iter_listing(self, brand):
        """Génère un dict par montre du listing, du plus récent au plus ancien.
        Doit au minimum porter 'vendue' + de quoi construire build_detail."""
        page = 1
        while page <= self.entry.get("max_pages_per_brand", 40):
            html = http_client.get_text(f"{self.base_url}/list/{brand}?page={page}")
            soup = BeautifulSoup(html, "html.parser")
            cards = soup.select("li.product")               # À ADAPTER
            if not cards:
                break
            for li in cards:
                a = li.select_one("a[href]")
                yield {
                    "vendue": li.select_one(".soldout") is not None,   # À ADAPTER
                    "url": a["href"],
                    "reference": (li.select_one(".ref") or li).get_text(strip=True),
                }
            page += 1

    def item_uid(self, item):
        """UID depuis le listing (sans ouvrir la fiche) → reprise instantanée.
        Renvoyer None si la réf n'est lisible que sur la fiche (cf. item_url)."""
        return make_uid(self.boutique, item["reference"], item["url"])

    def build_detail(self, item):
        """Fiche complète. NE PAS attraper les exceptions réseau : une erreur
        doit remonter (→ montre non marquée, retentée au prochain run).
        raw['accessoires'] alimente le filtre full set (boîte + papiers)."""
        soup = BeautifulSoup(http_client.get_text(item["url"]), "html.parser")

        def txt(sel):
            el = soup.select_one(sel)
            return el.get_text(strip=True) if el else ""

        prix = txt(".price-tax-included").replace("¥", "").replace(",", "")
        return watch(
            boutique=self.boutique,
            reference=item["reference"] or txt(".reference"),
            url=item["url"],
            marque=txt(".brand"),
            modele=txt(".model"),
            prix_ttc=float(prix) if prix.isdigit() else None,
            etat=txt(".condition"),
            date_ajout_site=txt(".date-added"),
            description=strip_html(txt(".description")),
            images=[img["src"] for img in soup.select(".gallery img")][:1],
            raw={"accessoires": txt(".accessories")},        # À ADAPTER (付属品)
        )
