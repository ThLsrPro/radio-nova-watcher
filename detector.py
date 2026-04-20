"""
detector.py — Détection locale par mots-clés et expressions régulières.
Aucun appel API externe : analyse entièrement en mémoire.

Logique en trois niveaux :
  - Mots-clés PRIMAIRES  : spécifiques à la billetterie, déclenchent seuls une détection.
  - Mots-clés SECONDAIRES : génériques, nécessitent combinaison pour être significatifs.
  - Mots-clés d'EXCLUSION : contexte publicitaire non-billetterie → annulent la détection.

Analyse contextuelle :
  - Buffer circulaire des 3 dernières transcriptions pour détecter les annonces
    à cheval sur plusieurs chunks.
  - Mode "alerte partielle" (confidence 50-84) : sensibilité augmentée sur les
    3 chunks suivants pour confirmer ou infirmer la détection.
"""

import logging
import re
import time
from collections import deque
from dataclasses import dataclass, field

import config

logger = logging.getLogger(__name__)

# ── Mots-clés PRIMAIRES ───────────────────────────────────────────────────────

_RAW_PRIMARY: list[str] = [
    r"\bbilletteri[e]?\b",
    r"\bbillet(?:s)?\b",
    r"\br[eé]servation(?:s)?\b",
    r"\br[eé]servez?\b",
    r"places?\s+en\s+vente",
    r"places?\s+disponibles?",
    r"places?\s+limit[eé]es?",
    r"\bfnac(?:\.com)?\b",
    r"\bdigitick\b",
    r"\bshotgun\b",
    r"\bbilletweb\b",
    r"\bweezevent\b",
    r"\bticketmaster\b",
    r"\blivenation\b",
    r"\bhelloasso\b",
    r"europ[eé]en\s+paris",
    r"l[''\s]europ[eé]en\b",
    r"la\s+derni[eè]re",
]

# ── Mots-clés SECONDAIRES ─────────────────────────────────────────────────────

_RAW_SECONDARY: list[str] = [
    r"\bticket(?:s)?\b",
    r"\bconcert(?:s)?\b",
    r"\bspectacle(?:s)?\b",
    r"\bshow\b",
    r"\bachat\b",
    r"\bacheter\b",
    r"\bcommander\b",
    r"\bdisponible(?:s)?\b",
    r"\ben\s+vente\b",
    r"\ben\s+ligne\b",
    r"\b[àa]\s+partir\s+de\b",
    r"\bd[eè]s\s+(?:le|ce|maintenant|aujourd)",
    r"\blien\b",
    r"\bsite\b",
    r"\bwww\b",
    r"https?://\S+",
]

# ── Mots-clés d'EXCLUSION ─────────────────────────────────────────────────────

_RAW_EXCLUSION: list[str] = [
    r"\bfromage\b",
    r"\bintermarché\b",
    r"\bintermarche\b",
    r"\bcarrefour\b",
    r"\blidl\b",
    r"\baldi\b",
    r"\bleclerc\b",
    r"\bauchain\b",
    r"\bmonoprix\b",
    r"\bfranprix\b",
    r"\bsuper[uU]\b",
    r"\bsupermarché\b",
    r"\bsupermarche\b",
    r"\bhypermarché\b",
    r"\bhypermarche\b",
    r"\beuros?\s+le\s+kilo\b",
    r"\bpromotion(?:s)?\b",
    r"\bpromo(?:s)?\b",
    r"\bsoldes?\b",
    r"\bremise(?:s)?\b",
    r"\bvoiture(?:s)?\b",
    r"\bimmobilier\b",
    r"\bassurance(?:s)?\b",
    r"\bmutuelle(?:s)?\b",
    r"\bcr[eè]dit\b",
    r"\bpr[eê]t\s+immobilier\b",
    r"\btelephonie\b",
    r"\btéléphonie\b",
    r"\bforfait\s+(?:mobile|internet)\b",
]

# ── Compilation ───────────────────────────────────────────────────────────────
_PRIMARY   = [(p, re.compile(p, re.IGNORECASE)) for p in _RAW_PRIMARY]
_SECONDARY = [(p, re.compile(p, re.IGNORECASE)) for p in _RAW_SECONDARY]
_EXCLUSION = [re.compile(p, re.IGNORECASE) for p in _RAW_EXCLUSION]

# Seuil de confidence minimal en mode alerte partielle (sensibilité augmentée)
_PARTIAL_ALERT_CONFIRM_THRESHOLD = 60


def _find_matches(text: str, patterns: list[tuple[str, re.Pattern[str]]]) -> list[str]:
    """Retourne les patterns bruts qui ont matché dans le texte."""
    return [raw for raw, compiled in patterns if compiled.search(text)]


def _is_excluded(text: str) -> bool:
    """Retourne True si un mot-clé d'exclusion est présent dans le texte."""
    return any(p.search(text) for p in _EXCLUSION)


def _compute_confidence(
    primary_hits: list[str],
    secondary_hits: list[str],
) -> tuple[int, bool]:
    """
    Calcule (confidence, action_required).

    Règles :
      - 0 primaire, < 2 secondaires  → (0,  False)
      - 0 primaire, ≥ 2 secondaires  → (30, False)
      - 1 primaire seul               → (70, False)
      - 1 primaire + ≥ 1 secondaire   → (85, True)
      - 2 primaires                   → (90, True)
      - ≥ 3 primaires                 → (98, True)
    """
    np = len(primary_hits)
    ns = len(secondary_hits)

    if np == 0:
        return (30, False) if ns >= 2 else (0, False)
    if np == 1:
        return (85, True) if ns >= 1 else (70, False)
    if np == 2:
        return 90, True
    return 98, True


def _extract_relevant_sentences(
    text: str,
    p_compiled: list[re.Pattern[str]],
    s_compiled: list[re.Pattern[str]],
) -> str:
    """Retourne les phrases contenant au moins un pattern matché."""
    all_patterns = p_compiled + s_compiled
    sentences = re.split(r"[.!?;\n]+", text)
    relevant = [
        s.strip() for s in sentences
        if s.strip() and any(p.search(s) for p in all_patterns)
    ]
    return " | ".join(relevant) if relevant else ""


@dataclass
class DetectionResult:
    """Résultat de la détection par mots-clés."""
    detected: bool
    confidence: int
    extracted_info: str
    action_required: bool
    matched_keywords: list[str] = field(default_factory=list)
    context_text: str = field(repr=False, default="")  # texte multi-chunks utilisé


class Detector:
    """
    Détecte les annonces de billets par analyse locale (mots-clés + regex).

    Maintient un buffer circulaire de 3 transcriptions pour l'analyse contextuelle
    et un état "alerte partielle" pour les détections ambiguës.
    """

    def __init__(self) -> None:
        self._last_notification_time: float = 0.0

        # Buffer circulaire des 3 dernières transcriptions (texte brut)
        self._transcript_buffer: deque[str] = deque(maxlen=3)

        # État alerte partielle
        self._partial_alert_active: bool = False
        self._partial_alert_chunks_remaining: int = 0

    def add_transcript(self, text: str) -> None:
        """Ajoute une transcription au buffer contextuel."""
        if text.strip():
            self._transcript_buffer.append(text.strip())

    def analyze(self, text: str) -> DetectionResult:
        """
        Analyse le texte courant enrichi du contexte des chunks précédents.

        Le texte analysé est la concaténation :
            [chunk N-2] ... [chunk N-1] ... [chunk N]

        En mode alerte partielle, le seuil de détection est abaissé à 60.

        Args:
            text: Transcription du chunk courant.

        Returns:
            DetectionResult.
        """
        if not text.strip():
            logger.debug("Texte vide, analyse ignorée.")
            self._tick_partial_alert()
            return DetectionResult(
                detected=False, confidence=0, extracted_info="", action_required=False
            )

        # Construire le contexte multi-chunks
        context_parts = list(self._transcript_buffer) + [text.strip()]
        context_text = " ... ".join(context_parts)

        # Vérification d'exclusion sur le contexte complet
        if _is_excluded(context_text):
            logger.debug("Contexte publicitaire détecté — ignoré.")
            self._tick_partial_alert()
            return DetectionResult(
                detected=False, confidence=0, extracted_info="", action_required=False
            )

        primary_hits   = _find_matches(context_text, _PRIMARY)
        secondary_hits = _find_matches(context_text, _SECONDARY)
        confidence, action_required = _compute_confidence(primary_hits, secondary_hits)

        matched_keywords = primary_hits + secondary_hits

        # ── Logique alerte partielle ───────────────────────────────────────────
        detect_threshold = 70  # seuil normal

        if confidence >= 50 and confidence <= 84 and not self._partial_alert_active:
            # Passage en mode alerte partielle
            self._partial_alert_active = True
            self._partial_alert_chunks_remaining = 3
            logger.info(
                f"Mode alerte partielle activé (confidence={confidence}) — "
                f"sensibilité augmentée sur les 3 prochains chunks."
            )
        elif self._partial_alert_active:
            # En mode alerte partielle : seuil abaissé
            detect_threshold = _PARTIAL_ALERT_CONFIRM_THRESHOLD
            self._partial_alert_chunks_remaining -= 1
            if self._partial_alert_chunks_remaining <= 0:
                self._partial_alert_active = False
                logger.info("Mode alerte partielle expiré sans confirmation.")

        detected = confidence >= detect_threshold

        # Extraction des phrases pertinentes sur le texte complet du contexte
        extracted_info = ""
        if detected or confidence >= 30:
            p_comp = [c for r, c in _PRIMARY   if r in primary_hits]
            s_comp = [c for r, c in _SECONDARY if r in secondary_hits]
            extracted_info = _extract_relevant_sentences(context_text, p_comp, s_comp)

        if detected:
            logger.info(
                f"Détection positive — confidence={confidence} "
                f"action_required={action_required} "
                f"mots-clés={matched_keywords}"
            )
            # Réinitialiser l'alerte partielle si on a une détection ferme
            if confidence > 84:
                self._partial_alert_active = False
        else:
            logger.debug(
                f"Détection faible — confidence={confidence} "
                f"mots-clés={matched_keywords}"
            )

        return DetectionResult(
            detected=detected,
            confidence=confidence,
            extracted_info=extracted_info,
            action_required=action_required,
            matched_keywords=matched_keywords,
            context_text=context_text,
        )

    def _tick_partial_alert(self) -> None:
        """Décrémente le compteur d'alerte partielle si actif."""
        if self._partial_alert_active:
            self._partial_alert_chunks_remaining -= 1
            if self._partial_alert_chunks_remaining <= 0:
                self._partial_alert_active = False
                logger.info("Mode alerte partielle expiré (texte vide).")

    def should_notify(self, result: DetectionResult) -> bool:
        """
        Détermine si une notification doit être envoyée.

        Conditions :
        - confidence > 80
        - action_required = True
        - Cooldown respecté
        """
        if not result.detected:
            return False
        if result.confidence <= 80:
            return False
        if not result.action_required:
            return False

        cooldown_seconds = config.DETECTION_COOLDOWN_MINUTES * 60
        elapsed = time.time() - self._last_notification_time
        if elapsed < cooldown_seconds:
            remaining = int((cooldown_seconds - elapsed) / 60)
            logger.info(
                f"Détection positive mais cooldown actif ({remaining} min restantes)."
            )
            return False

        return True

    def mark_notified(self) -> None:
        """Enregistre le timestamp de la dernière notification envoyée."""
        self._last_notification_time = time.time()
