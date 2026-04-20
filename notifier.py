"""
notifier.py — Envoi de notifications via ntfy.sh (HTTP POST).
Aucune dépendance externe hors de `requests`.
"""

import logging
import time

import requests

import config

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5


def _post_ntfy(title: str, body: str, priority: str = "default", tags: str = "bell,radio") -> bool:
    """
    Fonction interne : envoie un POST vers ntfy avec retry.

    Args:
        title:    Titre de la notification (ASCII uniquement — pas d'emojis).
        body:     Corps du message (UTF-8, emojis autorisés).
        priority: Priorité ntfy : min | low | default | high | urgent.
        tags:     Tags ntfy séparés par des virgules (noms d'emojis).

    Returns:
        True si l'envoi a réussi.
    """
    url = f"{config.NTFY_SERVER}/{config.NTFY_TOPIC}"
    headers = {
        "Title": title,
        "Priority": priority,
        "Tags": tags,
        "Content-Type": "text/plain; charset=utf-8",
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.post(
                url,
                data=body.encode("utf-8"),
                headers=headers,
                timeout=10,
            )
            response.raise_for_status()
            logger.info(f"Notification ntfy envoyée (HTTP {response.status_code}) → {url}")
            return True

        except requests.exceptions.HTTPError as exc:
            logger.warning(f"Erreur HTTP ntfy (tentative {attempt}/{MAX_RETRIES}) : {exc}")
        except requests.exceptions.ConnectionError as exc:
            logger.warning(f"Connexion ntfy impossible (tentative {attempt}/{MAX_RETRIES}) : {exc}")
        except requests.exceptions.Timeout:
            logger.warning(f"Délai dépassé ntfy (tentative {attempt}/{MAX_RETRIES})")
        except Exception as exc:
            logger.error(f"Erreur inattendue lors de l'envoi ntfy : {exc}")

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY_SECONDS)

    logger.error(f"Impossible d'envoyer la notification ntfy après {MAX_RETRIES} tentatives.")
    return False


def send_notification(detected_info: dict, transcription: str) -> bool:
    """
    Envoie une alerte ntfy pour une détection positive de mise en vente.

    Args:
        detected_info: Dictionnaire avec 'extracted_info' et 'confidence'.
        transcription: Transcription brute du chunk audio concerné.
    """
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    extracted_info = detected_info.get("extracted_info", "")
    confidence = detected_info.get("confidence", 0)

    # Tronquer la transcription brute si trop longue
    max_len = 300
    if len(transcription) > max_len:
        transcription = transcription[:max_len] + "…"

    body = (
        "🎙️ ALERTE - Places en vente !\n\n"
        f"📢 Info détectée : {extracted_info}\n"
        f"🕐 Heure : {timestamp}\n"
        f"📝 Contexte complet : {transcription}\n"
        f"🎯 Confidence : {confidence}%"
    )

    return _post_ntfy(
        title="ALERTE Radio Nova - La Derniere",
        body=body,
        priority="urgent",
        tags="bell,radio",
    )


def send_startup_notification(check_results: list[str], quota_summary: str = "") -> bool:
    """
    Envoie la notification de démarrage avec les résultats des health checks.

    Args:
        check_results:  Liste de chaînes décrivant chaque vérification (✅/❌).
        quota_summary:  Résumé des quotas Groq du mois (optionnel).
    """
    checks_text = "\n".join(check_results)
    quota_line = f"\n{quota_summary}" if quota_summary else ""
    body = (
        "🎙️ Radio Nova Watcher est operationnel !\n"
        "📅 Dimanche - Surveillance 18h00 → 20h00\n\n"
        "Resultats des verifications :\n"
        f"{checks_text}"
        f"{quota_line}\n\n"
        "🔍 Detection active - En attente d'annonce billetterie..."
    )

    return _post_ntfy(
        title="Radio Nova Watcher - Demarrage",
        body=body,
        priority="default",
        tags="white_check_mark,radio",
    )


def send_shutdown_notification(
    duration_seconds: float,
    chunks_processed: int,
    detections_count: int,
    detection_summary: str = "",
    session_quota_summary: str = "",
) -> bool:
    """
    Envoie la notification de fin de surveillance.

    Args:
        duration_seconds:      Durée totale de la surveillance en secondes.
        chunks_processed:      Nombre de chunks audio traités.
        detections_count:      Nombre de détections positives.
        detection_summary:     Résumé de la détection si applicable.
        session_quota_summary: Résumé des quotas Groq de la session.
    """
    minutes = int(duration_seconds // 60)
    seconds = int(duration_seconds % 60)
    duration_str = f"{minutes}min {seconds}s"

    if detections_count > 0 and detection_summary:
        resume = f"🎯 Détection : {detection_summary}"
    elif detections_count > 0:
        resume = f"🎯 {detections_count} détection(s) positive(s) — voir les logs."
    else:
        resume = "🔕 Aucune annonce de billetterie détectée."

    quota_line = f"\n{session_quota_summary}" if session_quota_summary else ""
    body = (
        "📴 Surveillance terminée\n"
        f"⏱️ Durée : {duration_str}\n"
        f"📝 Chunks traités : {chunks_processed}\n"
        f"🔍 Détections : {detections_count}\n"
        f"{resume}"
        f"{quota_line}"
    )

    return _post_ntfy(
        title="Radio Nova Watcher - Arret",
        body=body,
        priority="default",
        tags="stop_sign,radio",
    )


def send_test_notification() -> bool:
    """Envoie un message de test pour vérifier la configuration ntfy."""
    body = (
        "✅ Test de notification Radio Nova Watcher\n\n"
        "Si vous recevez ce message, la configuration est correcte !"
    )
    return _post_ntfy(
        title="Radio Nova Watcher - Test",
        body=body,
        priority="default",
        tags="white_check_mark",
    )
