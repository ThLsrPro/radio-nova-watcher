"""
quota_monitor.py — Suivi des quotas de l'API Groq.

Sur GitHub Actions (CI=true) : tracking en mémoire uniquement, pas d'I/O fichier.
En local : persistance dans logs/quota_tracker.json avec reset auto jour/mois.
"""

import json
import logging
import os
from dataclasses import dataclass, asdict
from pathlib import Path

logger = logging.getLogger(__name__)

QUOTA_FILE = Path("./logs/quota_tracker.json")

# ── Seuils d'alerte ───────────────────────────────────────────────────────────
ALERT_REQUESTS_DAY   = 400      # sur 2000 max/jour
ALERT_REQUESTS_MONTH = 300      # repère : ~480 pour 1 session de 2h
ALERT_AUDIO_MINUTES  = 600.0    # sur 7200 max/mois

# Détection d'environnement CI (GitHub Actions définit CI=true)
_IS_CI = os.getenv("CI", "").lower() == "true"


@dataclass
class QuotaState:
    """État courant des compteurs de quota."""
    groq_requests_today: int = 0
    groq_requests_month: int = 0
    groq_audio_minutes_month: float = 0.0
    last_reset_day: str = ""
    last_reset_month: str = ""


def _today() -> str:
    """Retourne la date du jour au format YYYY-MM-DD."""
    from datetime import date
    return date.today().isoformat()


def _this_month() -> str:
    """Retourne le mois courant au format YYYY-MM."""
    return _today()[:7]


def _load() -> QuotaState:
    """Charge l'état depuis le fichier JSON. Retourne un état vide si absent ou corrompu."""
    try:
        data = json.loads(QUOTA_FILE.read_text(encoding="utf-8"))
        return QuotaState(**data)
    except FileNotFoundError:
        return QuotaState()
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning(f"Fichier quota corrompu, réinitialisation : {exc}")
        return QuotaState()


def _save(state: QuotaState) -> None:
    """Persiste l'état dans le fichier JSON."""
    QUOTA_FILE.parent.mkdir(exist_ok=True)
    try:
        QUOTA_FILE.write_text(
            json.dumps(asdict(state), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as exc:
        logger.warning(f"Impossible d'écrire quota_tracker.json : {exc}")


def _apply_resets(state: QuotaState) -> QuotaState:
    """Remet à zéro les compteurs si le jour ou le mois a changé."""
    today = _today()
    month = _this_month()

    if state.last_reset_day != today:
        state.groq_requests_today = 0
        state.last_reset_day = today

    if state.last_reset_month != month:
        state.groq_requests_month = 0
        state.groq_audio_minutes_month = 0.0
        state.last_reset_month = month

    return state


# ── Compteurs de session (toujours actifs, y compris en CI) ───────────────────
_session_requests: int = 0
_session_audio_minutes: float = 0.0


def track_groq_request(audio_duration_seconds: float) -> None:
    """
    Enregistre une requête Groq réussie.

    Args:
        audio_duration_seconds: Durée du chunk audio transcrit (en secondes).
    """
    global _session_requests, _session_audio_minutes

    audio_minutes = audio_duration_seconds / 60.0
    _session_requests += 1
    _session_audio_minutes += audio_minutes

    if _IS_CI:
        # En CI, pas de persistance fichier — on logue juste
        logger.debug(
            f"[CI] Session Groq : {_session_requests} req | "
            f"{_session_audio_minutes:.1f} min audio"
        )
        return

    # ── Mode local : persistance et vérification des seuils ───────────────────
    state = _load()
    state = _apply_resets(state)

    state.groq_requests_today += 1
    state.groq_requests_month += 1
    state.groq_audio_minutes_month += audio_minutes

    _save(state)
    _check_thresholds(state)


def _check_thresholds(state: QuotaState) -> None:
    """Envoie une alerte ntfy si un seuil est dépassé."""
    from notifier import _post_ntfy  # import local pour éviter la circularité

    if state.groq_requests_today == ALERT_REQUESTS_DAY:
        logger.warning(f"Seuil quota Groq journalier atteint : {state.groq_requests_today} req")
        _post_ntfy(
            title="Alerte quota Groq - journalier",
            body=(
                f"⚠️ Quota Groq : {state.groq_requests_today} requêtes aujourd'hui "
                f"(limite : 2000/jour)"
            ),
            priority="high",
            tags="warning",
        )

    if state.groq_requests_month == ALERT_REQUESTS_MONTH:
        logger.warning(f"Seuil quota Groq mensuel atteint : {state.groq_requests_month} req")
        _post_ntfy(
            title="Alerte quota Groq - mensuel",
            body=(
                f"⚠️ Quota Groq : {state.groq_requests_month} requêtes ce mois "
                f"(normal si 1 session = ~480)"
            ),
            priority="default",
            tags="warning",
        )

    if state.groq_audio_minutes_month >= ALERT_AUDIO_MINUTES:
        logger.warning(f"Seuil audio Groq mensuel atteint : {state.groq_audio_minutes_month:.1f} min")
        _post_ntfy(
            title="Alerte quota Groq - audio mensuel",
            body=(
                f"⚠️ Quota Groq audio : {state.groq_audio_minutes_month:.1f} minutes "
                f"transcrites ce mois (limite : 7200)"
            ),
            priority="default",
            tags="warning",
        )


def notify_rate_limit() -> None:
    """Alerte ntfy dédiée aux erreurs 429 Groq (rate limit immédiat)."""
    from notifier import _post_ntfy
    logger.warning("Rate limit Groq (429) — pause de 60 secondes.")
    _post_ntfy(
        title="Rate limit Groq",
        body="🚨 Rate limit Groq atteint - pause de 60 secondes",
        priority="high",
        tags="rotating_light",
    )


def get_monthly_summary() -> str:
    """
    Retourne un résumé des quotas du mois pour les notifications.
    Utilise les stats de session en CI, le fichier JSON en local.
    """
    if _IS_CI:
        return (
            f"📊 Cette session : {_session_requests} req Groq | "
            f"{_session_audio_minutes:.1f} min audio"
        )

    state = _load()
    state = _apply_resets(state)
    return (
        f"📊 Quota Groq ce mois : {state.groq_requests_month} req | "
        f"{state.groq_audio_minutes_month:.1f} min audio"
    )


def get_session_summary() -> str:
    """Retourne le résumé de la session en cours (toujours en mémoire)."""
    return (
        f"📊 Cette session : {_session_requests} requêtes Groq | "
        f"{_session_audio_minutes:.1f} min transcrites"
    )
