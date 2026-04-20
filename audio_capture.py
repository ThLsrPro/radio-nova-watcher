"""
audio_capture.py — Capture du flux AAC via FFmpeg, découpage en chunks WAV 15 s.
"""

import logging
import os
import subprocess
import time
from collections.abc import Generator
from pathlib import Path

import config

logger = logging.getLogger(__name__)

# Dossier de stockage temporaire des chunks
CHUNKS_DIR = Path("./tmp_chunks")
CHUNKS_DIR.mkdir(exist_ok=True)


def _build_ffmpeg_command(stream_url: str, output_path: str, duration: int) -> list[str]:
    """Construit la commande FFmpeg pour extraire un chunk WAV depuis le flux."""
    return [
        "ffmpeg",
        "-y",                        # Écraser le fichier de sortie sans demander
        "-loglevel", "error",        # Réduire la verbosité FFmpeg
        "-i", stream_url,            # URL du flux d'entrée
        "-t", str(duration),         # Durée du chunk en secondes
        "-ar", "16000",              # Fréquence d'échantillonnage 16 kHz (requis par Whisper)
        "-ac", "1",                  # Mono
        "-f", "wav",                 # Format de sortie WAV
        output_path,
    ]


def capture_chunks(
    stream_url: str = config.RADIO_STREAM_URL,
    chunk_duration: int = config.CHUNK_DURATION_SECONDS,
    max_retries: int = 5,
) -> Generator[Path, None, None]:
    """
    Générateur qui capture en continu des chunks WAV depuis le flux radio.

    Yields:
        Path : chemin vers le fichier WAV prêt à être transcrit.

    Gère la reconnexion automatique avec backoff exponentiel en cas d'échec.
    """
    chunk_index = 0

    while True:
        chunk_path = CHUNKS_DIR / f"chunk_{chunk_index:06d}.wav"
        command = _build_ffmpeg_command(stream_url, str(chunk_path), chunk_duration)

        attempt = 0
        backoff = 2  # secondes initiales entre les tentatives

        while attempt < max_retries:
            try:
                logger.debug(f"Capture du chunk {chunk_index} (tentative {attempt + 1})")
                result = subprocess.run(
                    command,
                    capture_output=True,
                    timeout=chunk_duration + 30,  # tolérance supplémentaire
                )

                if result.returncode == 0 and chunk_path.exists() and chunk_path.stat().st_size > 0:
                    logger.debug(f"Chunk {chunk_index} capturé : {chunk_path}")
                    yield chunk_path
                    break  # succès, on sort de la boucle retry
                else:
                    stderr = result.stderr.decode(errors="replace").strip()
                    logger.warning(f"FFmpeg a échoué (code {result.returncode}) : {stderr}")

            except subprocess.TimeoutExpired:
                logger.warning(f"FFmpeg a dépassé le délai pour le chunk {chunk_index}")
            except FileNotFoundError:
                logger.error("FFmpeg introuvable. Installez-le avec : brew install ffmpeg")
                raise
            except Exception as exc:
                logger.error(f"Erreur inattendue lors de la capture : {exc}")

            attempt += 1
            if attempt < max_retries:
                logger.info(f"Nouvelle tentative dans {backoff}s…")
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)  # backoff exponentiel, max 60 s
        else:
            logger.error(
                f"Échec de la capture après {max_retries} tentatives. "
                "Poursuite avec le chunk suivant."
            )

        # Nettoyage du chunk précédent pour éviter de saturer le disque
        _cleanup_chunk(chunk_path)
        chunk_index += 1


def _cleanup_chunk(chunk_path: Path) -> None:
    """Supprime un chunk WAV après traitement."""
    try:
        if chunk_path.exists():
            chunk_path.unlink()
            logger.debug(f"Chunk supprimé : {chunk_path}")
    except OSError as exc:
        logger.warning(f"Impossible de supprimer {chunk_path} : {exc}")


def cleanup_all_chunks() -> None:
    """Supprime tous les chunks temporaires (appelé à l'arrêt du programme)."""
    for chunk_file in CHUNKS_DIR.glob("*.wav"):
        _cleanup_chunk(chunk_file)
    logger.info("Tous les chunks temporaires ont été supprimés.")
