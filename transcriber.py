"""
transcriber.py — Transcription audio → texte avec Whisper local.
"""

import logging
import time
from dataclasses import dataclass
from pathlib import Path

import whisper

import config

logger = logging.getLogger(__name__)

# Format des logs de transcription
LOG_DIR = Path("./logs")
LOG_DIR.mkdir(exist_ok=True)
TRANSCRIPTION_LOG = LOG_DIR / "transcriptions.log"


@dataclass
class TranscriptionResult:
    """Résultat d'une transcription Whisper."""
    text: str
    duration_seconds: float
    chunk_path: str


class Transcriber:
    """Charge le modèle Whisper et transcrit des fichiers audio WAV."""

    def __init__(self, model_name: str = config.WHISPER_MODEL) -> None:
        logger.info(f"Chargement du modèle Whisper « {model_name} »…")
        self.model = whisper.load_model(model_name)
        logger.info("Modèle Whisper chargé.")

        # Ouvrir le fichier de log en mode append
        self._log_file = TRANSCRIPTION_LOG.open("a", encoding="utf-8")

    def transcribe(self, chunk_path: Path) -> TranscriptionResult | None:
        """
        Transcrit un chunk WAV en français.

        Args:
            chunk_path: Chemin vers le fichier WAV à transcrire.

        Returns:
            TranscriptionResult ou None si la transcription échoue.
        """
        if not chunk_path.exists():
            logger.error(f"Fichier introuvable pour la transcription : {chunk_path}")
            return None

        start_time = time.time()
        try:
            result = self.model.transcribe(
                str(chunk_path),
                language="fr",
                fp16=False,  # Compatibilité CPU (pas de GPU requis)
            )
            elapsed = time.time() - start_time
            text: str = result["text"].strip()

            self._log_transcription(text, chunk_path)

            return TranscriptionResult(
                text=text,
                duration_seconds=elapsed,
                chunk_path=str(chunk_path),
            )

        except Exception as exc:
            logger.error(f"Échec de la transcription de {chunk_path} : {exc}")
            return None

    def _log_transcription(self, text: str, chunk_path: Path) -> None:
        """Écrit la transcription dans le fichier de log avec timestamp."""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] [{chunk_path.name}] {text}\n"
        try:
            self._log_file.write(line)
            self._log_file.flush()
        except OSError as exc:
            logger.warning(f"Impossible d'écrire dans le fichier de log : {exc}")

    def close(self) -> None:
        """Ferme le fichier de log."""
        try:
            self._log_file.close()
        except OSError:
            pass
