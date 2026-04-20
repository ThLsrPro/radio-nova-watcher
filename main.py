"""
main.py — Point d'entrée : boucle principale de surveillance Radio Nova.
"""

import argparse
import logging
import subprocess
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
import requests

import config
import quota_monitor
from archiver import GistArchiver
from audio_capture import capture_chunks, cleanup_all_chunks
from detector import Detector
from notifier import (
    send_notification,
    send_shutdown_notification,
    send_startup_notification,
    send_test_notification,
)
from transcriber import Transcriber


# ── Health checks ─────────────────────────────────────────────────────────────

def check_internet() -> str:
    try:
        requests.get("https://ntfy.sh", timeout=5)
        return "✅ Internet OK"
    except Exception:
        return "❌ Pas de connexion internet"


def check_radio_stream() -> str:
    try:
        with requests.get(config.RADIO_STREAM_URL, stream=True, timeout=5) as resp:
            if resp.status_code < 400:
                return "✅ Flux Radio Nova accessible"
            return f"❌ Flux inaccessible (HTTP {resp.status_code})"
    except Exception as exc:
        return f"❌ Flux inaccessible ({exc})"


def check_groq_api() -> str:
    try:
        from groq import Groq
        client = Groq(api_key=config.GROQ_API_KEY)
        client.models.list()
        return "✅ Groq API operationnelle"
    except Exception as exc:
        return f"❌ Groq API indisponible ({exc})"


def check_ffmpeg() -> str:
    try:
        result = subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
        if result.returncode == 0:
            first_line = result.stdout.decode(errors="replace").splitlines()[0]
            version = first_line.split(" ")[2] if len(first_line.split(" ")) > 2 else "?"
            return f"✅ FFmpeg disponible ({version})"
        return "❌ FFmpeg a retourné une erreur"
    except FileNotFoundError:
        return "❌ FFmpeg non trouve (installez-le : sudo apt-get install ffmpeg)"
    except Exception as exc:
        return f"❌ FFmpeg indisponible ({exc})"


def run_health_checks() -> tuple[list[str], bool]:
    print("\n── Health checks ─────────────────────────────────────")
    results: list[str] = []
    for _, fn in [("Internet", check_internet), ("Flux radio", check_radio_stream),
                  ("Groq API", check_groq_api), ("FFmpeg", check_ffmpeg)]:
        result = fn()
        results.append(result)
        print(f"  {result}")
    all_ok = all("✅" in r for r in results)
    print("──────────────────────────────────────────────────────\n")
    return results, all_ok


# ── Boucle principale ─────────────────────────────────────────────────────────

def print_startup_banner(archiver: GistArchiver) -> None:
    topic_url = f"{config.NTFY_SERVER}/{config.NTFY_TOPIC}"
    print("\n" + "=" * 60)
    print("  Radio Nova Watcher — Surveillance en temps réel")
    print("=" * 60)
    print(f"  Flux radio     : {config.RADIO_STREAM_URL}")
    print(f"  Transcription  : Groq whisper-large-v3")
    print(f"  Durée chunk    : {config.CHUNK_DURATION_SECONDS}s")
    print(f"  Cooldown       : {config.DETECTION_COOLDOWN_MINUTES} min")
    print(f"  Topic ntfy     : {topic_url}")
    if archiver.is_enabled:
        print(f"  Archivage Gist : activé (ID : {archiver.gist_id})")
    else:
        print(f"  Archivage Gist : désactivé")
    print("=" * 60)


def run_surveillance() -> None:
    """Boucle principale de surveillance."""

    # ── Archiveur Gist ─────────────────────────────────────────────────────────
    archiver = GistArchiver()
    archiver.start_session()

    print_startup_banner(archiver)

    # ── Health checks ──────────────────────────────────────────────────────────
    check_results, all_ok = run_health_checks()

    ntfy_ok = send_startup_notification(
        check_results,
        quota_summary=quota_monitor.get_monthly_summary(),
    )
    if ntfy_ok:
        print(f"  Notification de démarrage envoyée sur ntfy.")
    else:
        print(f"  ❌ Envoi ntfy échoué — vérifiez NTFY_TOPIC et NTFY_SERVER.")

    if not all_ok:
        logger.warning("Certains checks ont échoué — surveillance démarrée quand même.")

    # ── Initialisation des modules ─────────────────────────────────────────────
    logger.info("Initialisation des modules…")
    transcriber = Transcriber()
    detector = Detector()
    logger.info("Tous les modules sont prêts. Démarrage de la surveillance.\n")

    start_time = time.time()
    chunks_processed = 0
    detections_count = 0
    last_detection_info = ""

    try:
        for chunk_path in capture_chunks():
            timestamp = time.strftime("%H:%M:%S")

            # ── Transcription ──────────────────────────────────────────────────
            result = transcriber.transcribe(chunk_path)
            if result is None:
                logger.warning("Transcription échouée, passage au chunk suivant.")
                continue

            chunks_processed += 1
            print(f"[{timestamp}] {result.text or '(silence)'}")

            # Archiver la transcription
            archiver.add_transcription(timestamp, result.text)

            if not result.text.strip():
                continue

            # ── Analyse contextuelle multi-chunks ──────────────────────────────
            detection = detector.analyze(result.text)
            detector.add_transcript(result.text)

            if detection.detected:
                logger.info(
                    f"Détection positive ! confidence={detection.confidence} "
                    f"action_required={detection.action_required} "
                    f"mots-clés={detection.matched_keywords}"
                )

            # ── Notification et archivage de la détection ─────────────────────
            if detector.should_notify(detection):
                logger.info("Envoi de la notification ntfy…")
                success = send_notification(
                    detected_info={
                        "extracted_info": detection.extracted_info,
                        "confidence": detection.confidence,
                    },
                    transcription=detection.context_text or result.text,
                )
                if success:
                    detector.mark_notified()
                    detections_count += 1
                    last_detection_info = detection.extracted_info
                    logger.info("Notification envoyée avec succès.")

                # Archiver la détection (qu'elle soit notifiée ou non)
                archiver.add_detection(
                    timestamp=timestamp,
                    confidence=detection.confidence,
                    extracted_info=detection.extracted_info,
                    transcription_context=detection.context_text or result.text,
                    notification_sent=success if detector.should_notify(detection) else False,
                )

    except KeyboardInterrupt:
        print("\n\nArrêt demandé par l'utilisateur (Ctrl+C).")
    finally:
        duration = time.time() - start_time
        logger.info("Nettoyage des fichiers temporaires…")
        transcriber.close()
        cleanup_all_chunks()

        # Mettre à jour les stats quota dans l'archiveur avant la sauvegarde finale
        from quota_monitor import _session_requests, _session_audio_minutes
        archiver.update_quota_stats(_session_requests, _session_audio_minutes)
        archiver.save_session(duration)

        send_shutdown_notification(
            duration_seconds=duration,
            chunks_processed=chunks_processed,
            detections_count=detections_count,
            detection_summary=last_detection_info,
            session_quota_summary=quota_monitor.get_session_summary(),
        )
        logger.info("Arrêt propre.")


# ── Test de notification ───────────────────────────────────────────────────────

def run_test_notification() -> None:
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


# ── Point d'entrée ─────────────────────────────────────────────────────────────

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
