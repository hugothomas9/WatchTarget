"""Collecte en ligne de commande.

Usage : python -m backend.run [--full|--incremental] [--only jackroad,kamekichi]
"""
import sys

from . import pipeline


def main():
    mode = "full" if "--full" in sys.argv else "incremental"
    only = None
    if "--only" in sys.argv:
        i = sys.argv.index("--only")
        if i + 1 < len(sys.argv):
            only = [s.strip() for s in sys.argv[i + 1].split(",") if s.strip()]
    res = pipeline.run(mode, only=only)
    cible = f" ({','.join(only)})" if only else ""
    print(f"Collecte {mode}{cible} terminée : {res['fetched']} fiches, "
          f"{res['new']} nouvelles.")


if __name__ == "__main__":
    main()
