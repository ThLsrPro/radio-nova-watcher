"""
archiver.py — Archivage des sessions sur GitHub Gist (privé).

Fonctionnement :
  - Au démarrage : cherche ou crée le Gist "radio-nova-watcher-data"
  - start_session() : recharge l'historique existant depuis le Gist,
    reprend la session du jour si elle existe déjà (après interruption)
  - add_transcription / add_detection : accumule en mémoire
  - _push_to_gist() : récupère le contenu actuel du Gist, fusionne la
    session courante, puis pousse le tableau complet (logique fetch-merge-push)
  - Rétention : 20 dernières sessions maximum
  - Mode no-op silencieux si GIST_ENABLED=false ou GIST_TOKEN absent
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

GIST_API             = "https://api.github.com/gists"
GIST_DESCRIPTION     = "radio-nova-watcher-data"
PERIODIC_SAVE_INTERVAL = 120   # 2 minutes entre les sauvegardes automatiques
MAX_SESSIONS         = 10      # nombre maximum de sessions conservées dans le Gist


# ── Structures de données ─────────────────────────────────────────────────

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


# ── Archiveur principal ───────────────────────────────────────────────────

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

    # ── Initialisation ─────────────────────────────────────────────────────

    def _init_gist(self) -> None:
        """Cherche le Gist existant ou en crée un nouveau."""
        existing_id, existing_raw = self._find_existing_gist()
        if existing_id:
            self._gist_id = existing_id
            self._gist_raw_url = existing_raw
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
        initial_sessions  = json.dumps({"sessions": []}, indent=2)
        initial_dashboard = json.dumps({
            "last_updated": "", "total_sessions": 0,
            "total_detections": 0, "total_hours": 0.0,
            "sessions_summary": [],
        }, indent=2)
        payload = {
            "description": GIST_DESCRIPTION,
            "public": False,
            "files": {
                "sessions.json":    {"content": initial_sessions},
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

    def _fetch_sessions_from_gist(self) -> list[dict]:
        """
        Charge le tableau 'sessions' actuel depuis le Gist.
        Retourne une liste vide en cas d'erreur.
        """
        if not self._gist_id:
            return []
        try:
            # Passer par l'API pour obtenir la raw_url la plus récente
            resp = requests.get(
                f"{GIST_API}/{self._gist_id}",
                headers=self._headers,
                timeout=10,
            )
            resp.raise_for_status()
            raw_url = resp.json()["files"]["sessions.json"]["raw_url"]
            # Mettre à jour la raw_url en cache
            self._gist_raw_url = raw_url
            content_resp = requests.get(raw_url, timeout=10)
            content_resp.raise_for_status()
            return content_resp.json().get("sessions", [])
        except Exception as exc:
            logger.warning(f"Impossible de charger les sessions depuis le Gist : {exc}")
            return []

    # ── Gestion de session ─────────────────────────────────────────────────

    def start_session(self) -> None:
        """
        Démarre l'enregistrement d'une nouvelle session.

        Recharge l'historique existant depuis le Gist pour éviter
        d'écraser les sessions passées. Si une session avec l'id du
        jour existe déjà (reprise après interruption), elle est restaurée.
        """
        if not self._enabled:
            return

        # Recharger l'historique actuel depuis le Gist
        self._sessions_history = self._fetch_sessions_from_gist()

        now = datetime.now()
        session_id = now.strftime("%Y-%m-%d")

        # Reprendre la session du jour si elle existe déjà
        existing = next(
            (s for s in self._sessions_history if s.get("id") == session_id), None
        )
        if existing:
            self._session = SessionData(
                id=existing["id"],
                date=existing["date"],
                start_time=existing["start_time"],
                end_time=existing.get("end_time", ""),
                duration_minutes=existing.get("duration_minutes", 0.0),
                chunks_processed=existing.get("chunks_processed", 0),
                detections=existing.get("detections", []),
                flux_interruptions=existing.get("flux_interruptions", 0),
                groq_requests=existing.get("groq_requests", 0),
                groq_audio_minutes=existing.get("groq_audio_minutes", 0.0),
                full_transcript=existing.get("full_transcript", []),
            )
            logger.info(
                f"Session Gist reprise : {self._session.id} "
                f"({self._session.chunks_processed} chunks déjà enregistrés)"
            )
        else:
            self._session = SessionData(
                id=session_id,
                date=now.strftime("%Y-%m-%d"),
                start_time=now.strftime("%H:%M:%S"),
            )
            logger.info(f"Session Gist démarrée : {self._session.id}")

        self._last_save_time = time.time()

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

        self._push_to_gist()
        logger.info("Session sauvegardée sur le Gist.")

    # ── Persistance (fetch-merge-push) ────────────────────────────────────

    def _maybe_periodic_save(self) -> None:
        """Déclenche une sauvegarde si l'intervalle périodique est écoulé."""
        if time.time() - self._last_save_time >= PERIODIC_SAVE_INTERVAL:
            logger.info("Sauvegarde périodique vers le Gist…")
            self._push_to_gist()
            self._last_save_time = time.time()

    def _push_to_gist(self) -> None:
        """
        Pousse sessions.json et dashboard_data.json vers le Gist.

        Logique fetch-merge-push :
          1. Recharge les sessions actuelles depuis le Gist (source de vérité)
          2. Fusionne la session courante dans ce tableau
          3. Applique la limite de rétention (MAX_SESSIONS)
          4. Pousse l'ensemble mis à jour

        En cas d'échec du rechargement, utilise l'historique en mémoire
        comme fallback pour ne pas perdre les données de la session courante.
        """
        if not self._gist_id:
            return

        # 1. Recharger les sessions actuelles depuis le Gist
        fresh_sessions = self._fetch_sessions_from_gist()
        if fresh_sessions:
            all_sessions = fresh_sessions
        else:
            # Fallback sur l'historique en mémoire si le rechargement échoue
            logger.warning("Rechargement Gist échoué — utilisation de l'historique en mémoire.")
            all_sessions = list(self._sessions_history)

        # 2. Fusionner la session courante dans le tableau
        if self._session is not None:
            session_dict = asdict(self._session)
            existing_ids = [s["id"] for s in all_sessions]
            if self._session.id in existing_ids:
                all_sessions[existing_ids.index(self._session.id)] = session_dict
            else:
                all_sessions.append(session_dict)

        # 3. Appliquer la limite de rétention (les plus récentes en priorité)
        if len(all_sessions) > MAX_SESSIONS:
            removed = len(all_sessions) - MAX_SESSIONS
            all_sessions = all_sessions[-MAX_SESSIONS:]
            logger.info(f"{removed} session(s) ancienne(s) supprimée(s) — limite {MAX_SESSIONS} sessions.")

        # 4. Mettre à jour l'historique en mémoire
        self._sessions_history = all_sessions

        # 5. Pousser vers le Gist
        sessions_content  = json.dumps({"sessions": all_sessions}, indent=2, ensure_ascii=False)
        dashboard_content = json.dumps(
            self._build_dashboard_data(all_sessions), indent=2, ensure_ascii=False
        )

        payload = {
            "files": {
                "sessions.json":       {"content": sessions_content},
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
            self._gist_raw_url = resp.json()["files"]["sessions.json"]["raw_url"]
            logger.info(f"Gist mis à jour — {len(all_sessions)} session(s) conservée(s).")
        except Exception as exc:
            logger.warning(f"Impossible de mettre à jour le Gist : {exc}")

    @staticmethod
    def _build_dashboard_data(sessions: list[dict]) -> dict[str, Any]:
        """Construit les stats agrégées pour dashboard_data.json."""
        total_detections = sum(len(s.get("detections", [])) for s in sessions)
        total_hours      = sum(s.get("duration_minutes", 0) for s in sessions) / 60
        summaries = [
            {
                "date":              s.get("date", ""),
                "duration_minutes":  s.get("duration_minutes", 0),
                "chunks_processed":  s.get("chunks_processed", 0),
                "detections_count":  len(s.get("detections", [])),
            }
            for s in sessions
        ]
        return {
            "last_updated":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_sessions":   len(sessions),
            "total_detections": total_detections,
            "total_hours":      round(total_hours, 1),
            "sessions_summary": summaries,
        }

    # ── Propriétés ────────────────────────────────────────────────────────

    @property
    def gist_id(self) -> str:
        return self._gist_id

    @property
    def gist_raw_url(self) -> str:
        return self._gist_raw_url

    @property
    def is_enabled(self) -> bool:
        return self._enabled


# ── Test d'accumulation ───────────────────────────────────────────────────

def test_accumulation() -> None:
    """
    Simule 3 sessions et vérifie qu'elles s'accumulent correctement
    dans le Gist sans s'écraser mutuellement.

    Utilisation :
        python -c "from archiver import test_accumulation; test_accumulation()"
    """
    import sys

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
                        stream=sys.stdout)

    logger.info("=== Test d'accumulation des sessions ===")

    archiver = GistArchiver()
    if not archiver.is_enabled:
        logger.warning("Gist désactivé (GIST_ENABLED=false ou GIST_TOKEN absent) — test ignoré.")
        return

    # Simuler 3 sessions sur 3 dates différentes
    test_dates = ["2099-01-01", "2099-01-08", "2099-01-15"]
    for date in test_dates:
        archiver._session = SessionData(
            id=date,
            date=date,
            start_time="18:00:00",
            end_time="20:00:00",
            duration_minutes=120.0,
            chunks_processed=480,
            detections=[{
                "timestamp": "18:30:00",
                "confidence": 90,
                "extracted_info": f"Test détection {date}",
                "transcription_context": "contexte test",
                "notification_sent": True,
            }],
            flux_interruptions=0,
            groq_requests=480,
            groq_audio_minutes=120.0,
            full_transcript=[
                {"timestamp": "18:00:15", "text": f"Transcription test {date} chunk 1"},
                {"timestamp": "18:00:30", "text": f"Transcription test {date} chunk 2"},
            ],
        )
        archiver._push_to_gist()
        logger.info(f"  → Session {date} poussée vers le Gist")

    # Vérifier que les 3 sessions sont présentes dans le Gist
    fresh = archiver._fetch_sessions_from_gist()
    found_ids = [s["id"] for s in fresh]
    missing   = [d for d in test_dates if d not in found_ids]

    logger.info(f"Sessions présentes dans le Gist : {found_ids}")
    if missing:
        logger.error(f"❌ ÉCHEC — sessions manquantes : {missing}")
    else:
        logger.info(f"✅ OK — les {len(test_dates)} sessions sont bien accumulées")

    # Nettoyage : supprimer les sessions de test
    cleaned = [s for s in fresh if s["id"] not in test_dates]
    archiver._sessions_history = cleaned
    archiver._session = None
    # Push de nettoyage direct
    sessions_content = json.dumps({"sessions": cleaned}, indent=2, ensure_ascii=False)
    dashboard_content = json.dumps(
        GistArchiver._build_dashboard_data(cleaned), indent=2, ensure_ascii=False
    )
    try:
        resp = requests.patch(
            f"{GIST_API}/{archiver.gist_id}",
            headers=archiver._headers,
            data=json.dumps({"files": {
                "sessions.json":       {"content": sessions_content},
                "dashboard_data.json": {"content": dashboard_content},
            }}),
            timeout=15,
        )
        resp.raise_for_status()
        logger.info(f"Nettoyage effectué — {len(cleaned)} session(s) réelle(s) conservée(s).")
    except Exception as exc:
        logger.warning(f"Nettoyage échoué : {exc}")
