"""
transcriber.py — Transcription audio → texte via l'API Groq (whisper-large-v3).
"""

import logging
import time
from dataclasses import dataclass
from pathlib import Path

from groq import Groq, APIConnectionError, APIStatusError, RateLimitError

import config

logger = logging.getLogger(__name__)

LOG_DIR = Path("./logs")
LOG_DIR.mkdir(exist_ok=True)
TRANSCRIPTION_LOG = LOG_DIR / "transcriptions.log"

MAX_RETRIES = 3


@dataclass
class TranscriptionResult:
    """Résultat d'une transcription Groq."""
    text: str
    duration_seconds: float
    chunk_path: str


class Transcriber:
    """Envoie des chunks WAV à l'API Groq pour transcription."""

    def __init__(self) -> None:
        self._client = Groq(api_key=config.GROQ_API_KEY)
        # Ouvrir le fichier de log en mode append
        self._log_file = TRANSCRIPTION_LOG.open("a", encoding="utf-8")
        logger.info("Transcriber Groq initialisé (modèle : whisper-large-v3).")

    def transcribe(self, chunk_path: Path) -> TranscriptionResult | None:
        """
        Transcrit un chunk WAV en français via l'API Groq.

        Args:
            chunk_path: Chemin vers le fichier WAV à transcrire.

        Returns:
            TranscriptionResult ou None si toutes les tentatives échouent.
        """
        if not chunk_path.exists():
            logger.error(f"Fichier introuvable pour la transcription : {chunk_path}")
            return None

        backoff = 2  # secondes entre les tentatives

        for attempt in range(1, MAX_RETRIES + 1):
            start_time = time.time()
            try:
                with chunk_path.open("rb") as audio_file:
                    response = self._client.audio.transcriptions.create(
                        file=(chunk_path.name, audio_file, "audio/wav"),
                        model="whisper-large-v3",
                        language="fr",
                        response_format="text",
                    )
                elapsed = time.time() - start_time
                # response est une chaîne brute quand response_format="text"
                text: str = response.strip() if isinstance(response, str) else response.text.strip()

                self._log_transcription(text, chunk_path)
                return TranscriptionResult(
                    text=text,
                    duration_seconds=elapsed,
                    chunk_path=str(chunk_path),
                )

            except RateLimitError as exc:
                logger.warning(
                    f"Limite de débit Groq (tentative {attempt}/{MAX_RETRIES}) : {exc}"
                )
            except APIConnectionError as exc:
                logger.warning(
                    f"Connexion Groq impossible (tentative {attempt}/{MAX_RETRIES}) : {exc}"
                )
            except APIStatusError as exc:
                logger.warning(
                    f"Erreur API Groq {exc.status_code} (tentative {attempt}/{MAX_RETRIES}) : {exc.message}"
                )
            except Exception as exc:
                logger.error(f"Erreur inattendue lors de la transcription : {exc}")

            if attempt < MAX_RETRIES:
                logger.info(f"Nouvelle tentative dans {backoff}s…")
                time.sleep(backoff)
                backoff *= 2  # backoff exponentiel

        logger.error(f"Échec de la transcription de {chunk_path} après {MAX_RETRIES} tentatives.")
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
