"""
audio_capture.py — Capture du flux AAC via FFmpeg, découpage en chunks WAV 15 s.

Inclut un watchdog qui détecte les interruptions de flux et tente une reconnexion
automatique avec backoff exponentiel.
"""

import logging
import subprocess
import time
from collections.abc import Generator
from pathlib import Path

import config

logger = logging.getLogger(__name__)

CHUNKS_DIR = Path("./tmp_chunks")
CHUNKS_DIR.mkdir(exist_ok=True)

# Délai sans chunk avant de déclencher le watchdog (secondes)
WATCHDOG_TIMEOUT = 120
# Backoff exponentiel pour les reconnexions : 10s, 20s, 40s, 80s, 160s
_RECONNECT_BACKOFFS = [10, 20, 40, 80, 160]


def _build_ffmpeg_command(stream_url: str, output_path: str, duration: int) -> list[str]:
    """Construit la commande FFmpeg pour extraire un chunk WAV depuis le flux."""
    return [
        "ffmpeg",
        "-y",
        "-loglevel", "error",
        "-i", stream_url,
        "-t", str(duration),
        "-ar", "16000",
        "-ac", "1",
        "-f", "wav",
        output_path,
    ]


def _try_capture_chunk(
    stream_url: str,
    chunk_path: Path,
    chunk_duration: int,
    chunk_index: int,
) -> bool:
    """
    Tente de capturer un seul chunk. Retourne True si le chunk est valide.
    Ne gère pas les retries — le caller s'en charge.
    """
    command = _build_ffmpeg_command(stream_url, str(chunk_path), chunk_duration)
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            timeout=chunk_duration + 30,
        )
        if result.returncode == 0 and chunk_path.exists() and chunk_path.stat().st_size > 0:
            logger.debug(f"Chunk {chunk_index} capturé : {chunk_path}")
            return True
        stderr = result.stderr.decode(errors="replace").strip()
        logger.warning(f"FFmpeg a échoué (code {result.returncode}) : {stderr}")
    except subprocess.TimeoutExpired:
        logger.warning(f"FFmpeg a dépassé le délai pour le chunk {chunk_index}")
    except FileNotFoundError:
        logger.error("FFmpeg introuvable. Installez-le avec : brew install ffmpeg")
        raise
    except Exception as exc:
        logger.error(f"Erreur inattendue lors de la capture : {exc}")
    return False


def capture_chunks(
    stream_url: str = config.RADIO_STREAM_URL,
    chunk_duration: int = config.CHUNK_DURATION_SECONDS,
) -> Generator[Path, None, None]:
    """
    Générateur qui capture en continu des chunks WAV depuis le flux radio.

    Yields:
        Path : chemin vers le fichier WAV prêt à être transcrit.

    Lève StopIteration (fin du générateur) si la reconnexion échoue définitivement.
    """
    # Import local pour éviter la circularité au niveau module
    from notifier import _post_ntfy

    chunk_index = 0
    last_success_time = time.time()

    while True:
        chunk_path = CHUNKS_DIR / f"chunk_{chunk_index:06d}.wav"

        # ── Tentative de capture normale ──────────────────────────────────────
        if _try_capture_chunk(stream_url, chunk_path, chunk_duration, chunk_index):
            last_success_time = time.time()
            yield chunk_path
            _cleanup_chunk(chunk_path)
            chunk_index += 1
            continue

        # ── Échec : vérifier si le watchdog doit se déclencher ────────────────
        elapsed_since_success = time.time() - last_success_time

        if elapsed_since_success >= WATCHDOG_TIMEOUT:
            interrupt_timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            logger.warning(
                f"Watchdog déclenché : aucun chunk depuis {elapsed_since_success:.0f}s"
            )
            _post_ntfy(
                title="Radio Nova Watcher - Flux interrompu",
                body=(
                    "Le flux radio n'a pas repondu depuis 2 minutes.\n"
                    "Tentative de reconnexion en cours...\n"
                    f"Heure de detection : {interrupt_timestamp}"
                ),
                priority="high",
                tags="warning",
            )

            # ── Tentatives de reconnexion avec backoff exponentiel ─────────────
            reconnected = False
            for attempt, backoff in enumerate(_RECONNECT_BACKOFFS, start=1):
                logger.info(
                    f"Reconnexion {attempt}/{len(_RECONNECT_BACKOFFS)} "
                    f"dans {backoff}s…"
                )
                time.sleep(backoff)

                if _try_capture_chunk(stream_url, chunk_path, chunk_duration, chunk_index):
                    duration_str = _format_duration(time.time() - last_success_time)
                    logger.info(f"Flux reconnecté après {duration_str}")
                    _post_ntfy(
                        title="Radio Nova Watcher - Flux reconnecte",
                        body=f"✅ Flux radio reconnecte apres {duration_str} d'interruption",
                        priority="default",
                        tags="white_check_mark",
                    )
                    last_success_time = time.time()
                    yield chunk_path
                    _cleanup_chunk(chunk_path)
                    chunk_index += 1
                    reconnected = True
                    break

            if not reconnected:
                logger.error("Toutes les tentatives de reconnexion ont échoué.")
                _post_ntfy(
                    title="Radio Nova Watcher - Surveillance arretee",
                    body="🚨 Impossible de reconnecter le flux - Surveillance arretee",
                    priority="urgent",
                    tags="rotating_light",
                )
                return  # StopIteration → fin propre de la boucle principale

        else:
            # Échec ponctuel, pas encore watchdog — courte pause avant réessai
            logger.info("Échec de capture, nouvelle tentative dans 5s…")
            time.sleep(5)
            # Ne pas incrémenter chunk_index : on réessaie le même slot


def _format_duration(seconds: float) -> str:
    """Formate une durée en secondes en chaîne lisible."""
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m}min {s}s" if m else f"{s}s"


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
