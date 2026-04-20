"""
archiver.py — Archivage des sessions sur GitHub Gist (privé).

Fonctionnement :
  - Au démarrage : cherche ou crée un Gist "radio-nova-watcher-data"
  - Pendant la session : accumule transcriptions et détections en mémoire
  - Toutes les 2 minutes : pousse les données vers le Gist
  - En fin de session : push final + mise à jour des stats agrégées

Si GIST_ENABLED=false ou si GIST_TOKEN est absent : mode no-op silencieux.
"""

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any

import requests

import config

logger = logging.getLogger(__name__)

GIST_API = "https://api.github.com/gists"
GIST_DESCRIPTION = "radio-nova-watcher-data"
PERIODIC_SAVE_INTERVAL = 120  # 2 minutes en secondes (~8 transcriptions de 15s)


# ── Structures de données ─────────────────────────────────────────────────────

@dataclass
class TranscriptEntry:
    timestamp: str
    text: str


@dataclass
class DetectionEntry:
    timestamp: str
    confidence: int
    extracted_info: str
    transcription_context: str
    notification_sent: bool


@dataclass
class SessionData:
    id: str
    date: str
    start_time: str
    end_time: str = ""
    duration_minutes: float = 0.0
    chunks_processed: int = 0
    detections: list[dict] = field(default_factory=list)
    flux_interruptions: int = 0
    groq_requests: int = 0
    groq_audio_minutes: float = 0.0
    full_transcript: list[dict] = field(default_factory=list)


# ── Archiveur principal ───────────────────────────────────────────────────────

class GistArchiver:
    """Gère l'archivage des sessions sur GitHub Gist."""

    def __init__(self) -> None:
        self._enabled = config.GIST_ENABLED and bool(config.GIST_TOKEN)
        if not self._enabled:
            logger.info("Archivage Gist désactivé (GIST_ENABLED=false ou GIST_TOKEN absent).")
            self._gist_id: str = ""
            self._gist_raw_url: str = ""
            self._session: SessionData | None = None
            self._sessions_history: list[dict] = []
            self._last_save_time: float = 0.0
            return

        self._headers = {
            "Authorization": f"token {config.GIST_TOKEN}",
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json",
        }
        self._gist_id = ""
        self._gist_raw_url = ""
        self._session: SessionData | None = None
        self._sessions_history: list[dict] = []
        self._last_save_time: float = 0.0

        self._init_gist()

    # ── Initialisation ─────────────────────────────────────────────────────────

    def _init_gist(self) -> None:
        """Cherche le Gist existant ou en crée un nouveau."""
        existing_id, existing_raw = self._find_existing_gist()
        if existing_id:
            self._gist_id = existing_id
            self._gist_raw_url = existing_raw
            self._load_sessions_history()
            logger.info(f"Gist existant trouvé : {self._gist_id}")
        else:
            self._create_gist()
            logger.info(f"Nouveau Gist créé : {self._gist_id}")

    def _find_existing_gist(self) -> tuple[str, str]:
        """Retourne (gist_id, raw_url) du Gist existant, ou ('', '') si absent."""
        try:
            resp = requests.get(GIST_API, headers=self._headers, timeout=10)
            resp.raise_for_status()
            for gist in resp.json():
                if gist.get("description") == GIST_DESCRIPTION:
                    gist_id = gist["id"]
                    raw_url = gist["files"].get("sessions.json", {}).get("raw_url", "")
                    return gist_id, raw_url
        except Exception as exc:
            logger.warning(f"Impossible de lister les Gists : {exc}")
        return "", ""

    def _create_gist(self) -> None:
        """Crée un Gist privé avec les fichiers initiaux."""
        initial_sessions = json.dumps({"sessions": []}, indent=2)
        initial_dashboard = json.dumps({"last_updated": "", "total_sessions": 0,
                                        "total_detections": 0, "total_hours": 0.0,
                                        "sessions_summary": []}, indent=2)
        payload = {
            "description": GIST_DESCRIPTION,
            "public": False,
            "files": {
                "sessions.json": {"content": initial_sessions},
                "dashboard_data.json": {"content": initial_dashboard},
            },
        }
        try:
            resp = requests.post(GIST_API, headers=self._headers,
                                 data=json.dumps(payload), timeout=10)
            resp.raise_for_status()
            data = resp.json()
            self._gist_id = data["id"]
            self._gist_raw_url = data["files"]["sessions.json"]["raw_url"]
        except Exception as exc:
            logger.error(f"Impossible de créer le Gist : {exc}")
            self._enabled = False

    def _load_sessions_history(self) -> None:
        """Charge l'historique des sessions depuis le Gist."""
        try:
            # La raw_url inclut un hash — on passe par l'API pour avoir la version actuelle
            resp = requests.get(
                f"{GIST_API}/{self._gist_id}",
                headers=self._headers,
                timeout=10,
            )
            resp.raise_for_status()
            raw_url = resp.json()["files"]["sessions.json"]["raw_url"]
            content_resp = requests.get(raw_url, timeout=10)
            content_resp.raise_for_status()
            data = content_resp.json()
            self._sessions_history = data.get("sessions", [])
            # Mettre à jour la raw_url (elle change à chaque mise à jour du Gist)
            self._gist_raw_url = raw_url
        except Exception as exc:
            logger.warning(f"Impossible de charger l'historique Gist : {exc}")
            self._sessions_history = []

    # ── Gestion de session ─────────────────────────────────────────────────────

    def start_session(self) -> None:
        """Démarre l'enregistrement d'une nouvelle session."""
        if not self._enabled:
            return
        now = datetime.now()
        self._session = SessionData(
            id=now.strftime("%Y-%m-%d"),
            date=now.strftime("%Y-%m-%d"),
            start_time=now.strftime("%H:%M:%S"),
        )
        self._last_save_time = time.time()
        logger.info(f"Session Gist démarrée : {self._session.id}")

    def add_transcription(self, timestamp: str, text: str) -> None:
        """Ajoute une transcription au buffer de session."""
        if not self._enabled or self._session is None:
            return
        self._session.full_transcript.append({"timestamp": timestamp, "text": text})
        self._session.chunks_processed += 1
        self._maybe_periodic_save()

    def add_detection(self, timestamp: str, confidence: int, extracted_info: str,
                      transcription_context: str, notification_sent: bool) -> None:
        """Enregistre une détection positive."""
        if not self._enabled or self._session is None:
            return
        self._session.detections.append({
            "timestamp": timestamp,
            "confidence": confidence,
            "extracted_info": extracted_info,
            "transcription_context": transcription_context,
            "notification_sent": notification_sent,
        })

    def increment_interruption(self) -> None:
        """Incrémente le compteur d'interruptions de flux."""
        if self._enabled and self._session:
            self._session.flux_interruptions += 1

    def update_quota_stats(self, groq_requests: int, groq_audio_minutes: float) -> None:
        """Met à jour les stats de quota Groq pour la session."""
        if self._enabled and self._session:
            self._session.groq_requests = groq_requests
            self._session.groq_audio_minutes = groq_audio_minutes

    def save_session(self, duration_seconds: float) -> None:
        """Finalise et sauvegarde la session complète sur le Gist."""
        if not self._enabled or self._session is None:
            return

        now = datetime.now()
        self._session.end_time = now.strftime("%H:%M:%S")
        self._session.duration_minutes = round(duration_seconds / 60, 1)

        # Mettre à jour ou ajouter la session dans l'historique
        existing_ids = [s["id"] for s in self._sessions_history]
        session_dict = asdict(self._session)
        if self._session.id in existing_ids:
            idx = existing_ids.index(self._session.id)
            self._sessions_history[idx] = session_dict
        else:
            self._sessions_history.append(session_dict)

        self._push_to_gist()
        logger.info("Session archivée sur le Gist.")

    # ── Persistance ────────────────────────────────────────────────────────────

    def _maybe_periodic_save(self) -> None:
        """Déclenche une sauvegarde si 10 minutes se sont écoulées."""
        if time.time() - self._last_save_time >= PERIODIC_SAVE_INTERVAL:
            logger.info("Sauvegarde périodique vers le Gist…")
            self._push_to_gist()
            self._last_save_time = time.time()

    def _push_to_gist(self) -> None:
        """Pousse sessions.json et dashboard_data.json vers le Gist."""
        if not self._gist_id:
            return

        # Construire la liste des sessions incluant la session en cours si active
        all_sessions = list(self._sessions_history)
        if self._session is not None:
            session_dict = asdict(self._session)
            existing_ids = [s["id"] for s in all_sessions]
            if self._session.id in existing_ids:
                all_sessions[existing_ids.index(self._session.id)] = session_dict
            else:
                all_sessions.append(session_dict)

        sessions_content = json.dumps({"sessions": all_sessions}, indent=2, ensure_ascii=False)
        dashboard_content = json.dumps(self._build_dashboard_data(all_sessions),
                                       indent=2, ensure_ascii=False)

        payload = {
            "files": {
                "sessions.json": {"content": sessions_content},
                "dashboard_data.json": {"content": dashboard_content},
            }
        }
        try:
            resp = requests.patch(
                f"{GIST_API}/{self._gist_id}",
                headers=self._headers,
                data=json.dumps(payload),
                timeout=15,
            )
            resp.raise_for_status()
            # Mettre à jour la raw_url après chaque PATCH (elle change)
            new_raw = resp.json()["files"]["sessions.json"]["raw_url"]
            self._gist_raw_url = new_raw
            logger.debug(f"Gist mis à jour ({len(all_sessions)} sessions).")
        except Exception as exc:
            logger.warning(f"Impossible de mettre à jour le Gist : {exc}")

    @staticmethod
    def _build_dashboard_data(sessions: list[dict]) -> dict[str, Any]:
        """Construit les stats agrégées pour dashboard_data.json."""
        total_detections = sum(len(s.get("detections", [])) for s in sessions)
        total_hours = sum(s.get("duration_minutes", 0) for s in sessions) / 60
        summaries = [
            {
                "date": s.get("date", ""),
                "duration_minutes": s.get("duration_minutes", 0),
                "chunks_processed": s.get("chunks_processed", 0),
                "detections_count": len(s.get("detections", [])),
            }
            for s in sessions
        ]
        return {
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_sessions": len(sessions),
            "total_detections": total_detections,
            "total_hours": round(total_hours, 1),
            "sessions_summary": summaries,
        }

    @property
    def gist_id(self) -> str:
        return self._gist_id

    @property
    def gist_raw_url(self) -> str:
        return self._gist_raw_url

    @property
    def is_enabled(self) -> bool:
        return self._enabled
