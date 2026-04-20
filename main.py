"""
main.py — Point d'entrée : boucle principale de surveillance Radio Nova.
"""

import argparse
import logging
import sys
import time
from pathlib import Path

# ── Initialisation du logging avant tout autre import ─────────────────────────
LOG_DIR = Path("./logs")
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "app.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# ── Imports des modules du projet ─────────────────────────────────────────────
import config
from audio_capture import capture_chunks, cleanup_all_chunks
from detector import Detector
from notifier import send_notification, send_test_notification
from transcriber import Transcriber


def print_startup_banner() -> None:
    """Affiche les informations de démarrage (sans exposer les secrets)."""
    topic_url = f"{config.NTFY_SERVER}/{config.NTFY_TOPIC}"
    print("\n" + "=" * 60)
    print("  Radio Nova Watcher — Surveillance en temps réel")
    print("=" * 60)
    print(f"  Flux radio     : {config.RADIO_STREAM_URL}")
    print(f"  Modèle Whisper : {config.WHISPER_MODEL}")
    print(f"  Durée chunk    : {config.CHUNK_DURATION_SECONDS}s")
    print(f"  Cooldown       : {config.DETECTION_COOLDOWN_MINUTES} min")
    print(f"  Topic ntfy     : {topic_url}")
    print("=" * 60 + "\n")


def run_surveillance() -> None:
    """Boucle principale de surveillance."""
    print_startup_banner()

    # Initialisation des modules
    logger.info("Initialisation des modules…")
    transcriber = Transcriber()
    detector = Detector()
    logger.info("Tous les modules sont prêts. Démarrage de la surveillance.\n")

    try:
        for chunk_path in capture_chunks():
            timestamp = time.strftime("%H:%M:%S")

            # ── Transcription ─────────────────────────────────────────────────
            result = transcriber.transcribe(chunk_path)
            if result is None:
                logger.warning("Transcription échouée, passage au chunk suivant.")
                continue

            # Affichage temps réel dans le terminal
            print(f"[{timestamp}] {result.text or '(silence)'}")

            if not result.text.strip():
                continue  # Rien à analyser

            # ── Détection ─────────────────────────────────────────────────────
            detection = detector.analyze(result.text)

            if detection.detected:
                logger.info(
                    f"Détection positive ! confidence={detection.confidence} "
                    f"action_required={detection.action_required}"
                )

            # ── Notification ──────────────────────────────────────────────────
            if detector.should_notify(detection):
                logger.info("Envoi de la notification ntfy…")
                success = send_notification(
                    detected_info={
                        "extracted_info": detection.extracted_info,
                        "confidence": detection.confidence,
                    },
                    transcription=result.text,
                )
                if success:
                    detector.mark_notified()
                    logger.info("Notification envoyée avec succès.")

    except KeyboardInterrupt:
        print("\n\nArrêt demandé par l'utilisateur (Ctrl+C).")
    finally:
        logger.info("Nettoyage des fichiers temporaires…")
        transcriber.close()
        cleanup_all_chunks()
        logger.info("Arrêt propre.")


def run_test_notification() -> None:
    """Envoie une notification ntfy de test sans lancer la surveillance."""
    topic_url = f"{config.NTFY_SERVER}/{config.NTFY_TOPIC}"
    print(f"\nEnvoi d'une notification ntfy de test…")
    print(f"Topic : {topic_url}")
    print(f"Vérifiez dans votre navigateur ou l'app ntfy : {topic_url}\n")

    success = send_test_notification()
    if success:
        print("Test réussi ! Vérifiez vos notifications ntfy.")
    else:
        print("Échec de l'envoi. Vérifiez NTFY_TOPIC et NTFY_SERVER dans .env.")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Radio Nova Watcher — Détecte les annonces de billets pour La Dernière."
    )
    parser.add_argument(
        "--test-notification",
        action="store_true",
        help="Envoie une notification ntfy de test et quitte.",
    )
    args = parser.parse_args()

    if args.test_notification:
        run_test_notification()
    else:
        run_surveillance()


if __name__ == "__main__":
    main()
