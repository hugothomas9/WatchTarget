"""Authentification Telegram (Login Widget) — sans mot de passe.

Le widget renvoie {id, first_name, last_name, username, photo_url, auth_date, hash}.
On VÉRIFIE la signature (impossible à falsifier sans le token du bot) :
  secret = SHA256(bot_token) ; hash attendu = HMAC-SHA256(data_check_string, secret)
où data_check_string = les champs (sauf hash) triés « clé=valeur » joints par \n.

Session : cookie signé (HMAC) contenant l'id Telegram — pas de mot de passe, pas de
stockage de session côté serveur. Doc : docs/specs/deploiement-multiutilisateurs.md.
"""
import hashlib
import hmac
import time

from . import config


def verifier_widget(payload: dict, max_age_s: int = 86400) -> dict | None:
    """Valide la charge du Login Widget. Renvoie {telegram_id, first_name, username}
    si la signature ET la fraîcheur sont bonnes, sinon None."""
    token = config.TELEGRAM_BOT_TOKEN
    if not token or "hash" not in payload:
        return None
    data = {k: str(v) for k, v in payload.items() if k != "hash"}
    check = "\n".join(f"{k}={data[k]}" for k in sorted(data))
    secret = hashlib.sha256(token.encode()).digest()
    attendu = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(attendu, str(payload.get("hash", ""))):
        return None
    try:
        if time.time() - int(payload.get("auth_date", 0)) > max_age_s:
            return None
    except (TypeError, ValueError):
        return None
    return {"telegram_id": int(payload["id"]),
            "first_name": payload.get("first_name", "") or "",
            "username": payload.get("username", "") or ""}


# --- session : cookie signé (id Telegram) ---
def creer_session(telegram_id: int) -> str:
    """Jeton « <id>.<signature> » signé avec le token du bot (HMAC)."""
    sig = hmac.new(config.TELEGRAM_BOT_TOKEN.encode(), str(telegram_id).encode(),
                   hashlib.sha256).hexdigest()
    return f"{telegram_id}.{sig}"


def lire_session(cookie: str | None) -> int | None:
    """Renvoie l'id Telegram si le cookie est valide, sinon None."""
    # sans token configuré, la clé HMAC serait VIDE (calculable par quiconque →
    # forge de session admin) : on refuse toute session tant que le bot n'est
    # pas configuré
    if not config.TELEGRAM_BOT_TOKEN:
        return None
    if not cookie or "." not in cookie:
        return None
    tid, _, sig = cookie.partition(".")
    attendu = hmac.new(config.TELEGRAM_BOT_TOKEN.encode(), tid.encode(),
                       hashlib.sha256).hexdigest()
    if hmac.compare_digest(attendu, sig):
        try:
            return int(tid)
        except ValueError:
            return None
    return None
