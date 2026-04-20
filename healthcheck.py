"""
healthcheck.py — Vérifications pré-émission autonomes (check du samedi).

Exécutable en local :  python healthcheck.py
Exécuté par GitHub Actions chaque samedi à 16h00 UTC (18h Paris).

Retourne :
  exit(0) si tous les checks sont OK
  exit(1) si au moins un check échoue
"""

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

# ── Logging minimal (stdout uniquement) ───────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# Charger .env si présent (pas obligatoire en CI où les secrets sont injectés)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import requests

# Variables d'environnement requises
_NTFY_TOPIC  = os.environ.get("NTFY_TOPIC", "")
_NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh")
_GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
_STREAM_URL  = os.environ.get(
    "RADIO_STREAM_URL",
    "http://radionova.ice.infomaniak.ch/radionova-256.aac",
)
_GH_RUN_URL  = (
    f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/"
    f"{os.environ.get('GITHUB_REPOSITORY', '')}/"
    f"actions/runs/{os.environ.get('GITHUB_RUN_ID', '')}"
)

SILENCE_WAV = Path("/tmp/test_silence.wav")


# ── Fonctions de vérification ─────────────────────────────────────────────────

def check_internet() -> str:
    """Vérifie la connexion internet."""
    try:
        requests.get("https://ntfy.sh", timeout=5)
        return "✅ Internet OK"
    except Exception as exc:
        return f"❌ Pas de connexion internet ({exc})"


def check_radio_stream() -> str:
    """Vérifie l'accessibilité du flux Radio Nova."""
    try:
        with requests.get(_STREAM_URL, stream=True, timeout=5) as resp:
            if resp.status_code < 400:
                return "✅ Flux Radio Nova accessible"
            return f"❌ Flux inaccessible (HTTP {resp.status_code})"
    except Exception as exc:
        return f"❌ Flux inaccessible ({exc})"


def check_groq_api() -> str:
    """
    Vérifie la clé Groq en transcrivant un fichier WAV de silence d'1 seconde.
    Plus fiable qu'un simple appel à models.list().
    """
    if not _GROQ_API_KEY:
        return "❌ GROQ_API_KEY non définie"

    # Générer le fichier de silence
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
                "-t", "1",
                str(SILENCE_WAV),
            ],
            capture_output=True,
            timeout=10,
        )
        if result.returncode != 0 or not SILENCE_WAV.exists():
            return "❌ Impossible de générer le fichier de test (FFmpeg)"
    except FileNotFoundError:
        return "❌ FFmpeg requis pour le test Groq"
    except Exception as exc:
        return f"❌ Erreur génération silence : {exc}"

    # Envoyer à l'API Groq
    try:
        from groq import Groq
        client = Groq(api_key=_GROQ_API_KEY)
        with SILENCE_WAV.open("rb") as f:
            client.audio.transcriptions.create(
                file=(SILENCE_WAV.name, f, "audio/wav"),
                model="whisper-large-v3",
                language="fr",
                response_format="text",
            )
        return "✅ Groq API operationnelle"
    except Exception as exc:
        return f"❌ Groq API indisponible ({exc})"
    finally:
        if SILENCE_WAV.exists():
            SILENCE_WAV.unlink()


def check_ffmpeg() -> str:
    """Vérifie que FFmpeg est installé."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            first_line = result.stdout.decode(errors="replace").splitlines()[0]
            parts = first_line.split(" ")
            version = parts[2] if len(parts) > 2 else "?"
            return f"✅ FFmpeg disponible ({version})"
        return "❌ FFmpeg a retourné une erreur"
    except FileNotFoundError:
        return "❌ FFmpeg non trouve"
    except Exception as exc:
        return f"❌ FFmpeg indisponible ({exc})"


def send_ntfy_report(results: list[str], all_ok: bool) -> bool:
    """Envoie le rapport de vérification sur ntfy."""
    if not _NTFY_TOPIC:
        logger.error("NTFY_TOPIC non défini — impossible d'envoyer le rapport.")
        return False

    checks_text = "\n".join(results)
    url = f"{_NTFY_SERVER}/{_NTFY_TOPIC}"

    if all_ok:
        title = "Check pre-emission - Tout est pret !"
        priority = "default"
        tags = "white_check_mark,radio"
        body = (
            f"{checks_text}\n\n"
            "🎙️ Surveillance prete pour demain 18h00\n"
            "📅 Emission : La Derniere - Radio Nova\n"
            "📍 L'Europeen, Paris"
        )
    else:
        title = "Check pre-emission - Probleme detecte !"
        priority = "urgent"
        tags = "warning,radio"
        body = (
            f"{checks_text}\n\n"
            "⚠️ Verifiez la configuration avant demain 18h !\n"
            f"🔗 Logs : {_GH_RUN_URL}"
        )

    try:
        response = requests.post(
            url,
            data=body.encode("utf-8"),
            headers={
                "Title": title,
                "Priority": priority,
                "Tags": tags,
                "Content-Type": "text/plain; charset=utf-8",
            },
            timeout=10,
        )
        response.raise_for_status()
        logger.info(f"Rapport ntfy envoyé (HTTP {response.status_code})")
        return True
    except Exception as exc:
        logger.error(f"Impossible d'envoyer le rapport ntfy : {exc}")
        return False


# ── Point d'entrée ─────────────────────────────────────────────────────────────

def main() -> None:
    print("\n── Health check pré-émission ─────────────────────────")

    checks = [
        ("Internet",   check_internet),
        ("Flux radio", check_radio_stream),
        ("Groq API",   check_groq_api),
        ("FFmpeg",     check_ffmpeg),
    ]

    results: list[str] = []
    for name, fn in checks:
        print(f"  Vérification {name}…", end=" ", flush=True)
        result = fn()
        results.append(result)
        print(result)

    all_ok = all("✅" in r for r in results)

    print("──────────────────────────────────────────────────────")
    print(f"  Résultat global : {'✅ Tout OK' if all_ok else '❌ Problème(s) détecté(s)'}")

    # ntfy compte comme 5e check (son envoi valide la chaîne de notification)
    ntfy_ok = send_ntfy_report(results, all_ok)
    ntfy_result = "✅ ntfy OK" if ntfy_ok else "❌ ntfy indisponible"
    print(f"  {ntfy_result}")
    results.append(ntfy_result)

    print("──────────────────────────────────────────────────────\n")

    sys.exit(0 if all_ok and ntfy_ok else 1)


if __name__ == "__main__":
    main()
