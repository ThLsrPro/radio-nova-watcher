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


def send_notification(detected_info: dict, transcription: str) -> bool:
    """
    Envoie une notification ntfy avec les informations détectées.

    Args:
        detected_info: Dictionnaire contenant au minimum les clés
                       'extracted_info' et 'confidence'.
        transcription: Transcription brute du chunk audio concerné.

    Returns:
        True si l'envoi a réussi, False après épuisement des tentatives.
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
        f"📝 Transcription : {transcription}\n"
        f"🎯 Confidence : {confidence}%"
    )

    url = f"{config.NTFY_SERVER}/{config.NTFY_TOPIC}"
    headers = {
        "Title": "ALERTE Radio Nova - La Derniere",
        "Priority": "urgent",
        "Tags": "bell,radio",
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
            logger.warning(
                f"Erreur HTTP ntfy (tentative {attempt}/{MAX_RETRIES}) : {exc}"
            )
        except requests.exceptions.ConnectionError as exc:
            logger.warning(
                f"Connexion ntfy impossible (tentative {attempt}/{MAX_RETRIES}) : {exc}"
            )
        except requests.exceptions.Timeout:
            logger.warning(
                f"Délai dépassé ntfy (tentative {attempt}/{MAX_RETRIES})"
            )
        except Exception as exc:
            logger.error(f"Erreur inattendue lors de l'envoi ntfy : {exc}")

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY_SECONDS)

    logger.error(f"Impossible d'envoyer la notification ntfy après {MAX_RETRIES} tentatives.")
    return False


def send_test_notification() -> bool:
    """Envoie un message de test pour vérifier la configuration ntfy."""
    detected_info = {
        "extracted_info": (
            "✅ Test de notification Radio Nova Watcher - "
            "Si vous recevez ce message, la configuration est correcte !"
        ),
        "confidence": 100,
    }
    return send_notification(detected_info, transcription="[TEST — pas de transcription réelle]")
