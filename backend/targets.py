"""Chargement de la liste des montres ciblées (targets.json)."""
import json

from . import config


def load_targets(path=None) -> list[dict]:
    """Charge les cibles depuis targets.json. Renvoie [] si le fichier est absent."""
    path = path or config.TARGETS_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    return data.get("targets", [])
