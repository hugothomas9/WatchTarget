from backend import db
from backend.noms import traduire_nom
import re
from collections import Counter

conn = db.connect()
rows = conn.execute("SELECT modele, marque FROM watches").fetchall()

# 1) tokens katakana/kanji restant APRÈS traduction (les trous du glossaire)
c = Counter()
for r in rows:
    t = traduire_nom(r["modele"] or "")
    for tok in re.findall(r"[ァ-ヶー]{2,}", t):
        c[tok] += 1
print("=== TOP 60 termes NON traduits (après traduire_nom) ===")
for tok, n in c.most_common(60):
    print(f"{n:5}  {tok}")

# 2) marques encore en katakana dans le champ marque
m = Counter()
for r in rows:
    mq = r["marque"] or ""
    if re.search(r"[ァ-ヶー]", mq):
        m[mq] += 1
print("\n=== MARQUES encore en katakana ===")
for mq, n in m.most_common(20):
    print(f"{n:5}  {mq}")

# Usage : PYTHONPATH=. python3 scripts/scan_glossaire.py
# Liste les termes katakana les plus fréquents ENCORE non traduits par
# backend/noms.py + les marques restées en katakana → matière des prochaines
# vagues d'enrichissement du glossaire.
