"""
config.py — Chargement des variables d'environnement depuis .env
"""

import os
from dotenv import load_dotenv

# Charger le fichier .env situé à la racine du projet
load_dotenv()


def _require(key: str) -> str:
    """Récupère une variable obligatoire, lève une erreur si absente."""
    value = os.getenv(key)
    if not value:
        raise EnvironmentError(f"Variable d'environnement manquante : {key}")
    return value


def _optional(key: str, default: str) -> str:
    """Récupère une variable optionnelle avec valeur par défaut."""
    return os.getenv(key, default)


# ── Groq API ──────────────────────────────────────────────────────────────────
GROQ_API_KEY: str = _require("GROQ_API_KEY")

# ── ntfy.sh ───────────────────────────────────────────────────────────────────
# Nom unique du topic sur lequel les notifications sont publiées
NTFY_TOPIC: str = _require("NTFY_TOPIC")
# URL du serveur ntfy (ntfy.sh public ou instance auto-hébergée)
NTFY_SERVER: str = _optional("NTFY_SERVER", "https://ntfy.sh")

# ── GitHub Gist — Archivage des sessions ─────────────────────────────────────
# Token GitHub avec le scope "gist" (Settings > Developer settings > PAT)
GIST_TOKEN: str = _optional("GIST_TOKEN", "")
# Activer l'archivage : "true" pour activer, toute autre valeur pour désactiver
GIST_ENABLED: bool = _optional("GIST_ENABLED", "false").lower() == "true"

# ── Flux radio ────────────────────────────────────────────────────────────────
RADIO_STREAM_URL: str = _optional(
    "RADIO_STREAM_URL",
    "http://radionova.ice.infomaniak.ch/radionova-256.aac",
)

# ── Capture audio ─────────────────────────────────────────────────────────────
CHUNK_DURATION_SECONDS: int = int(_optional("CHUNK_DURATION_SECONDS", "15"))

# ── Détection ─────────────────────────────────────────────────────────────────
DETECTION_COOLDOWN_MINUTES: int = int(_optional("DETECTION_COOLDOWN_MINUTES", "30"))
