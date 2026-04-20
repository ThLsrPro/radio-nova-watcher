"""
detector.py — Détection locale par mots-clés et expressions régulières.
Aucun appel API externe : analyse entièrement en mémoire.

Logique en trois niveaux :
  - Mots-clés PRIMAIRES  : spécifiques à la billetterie, déclenchent seuls une détection.
  - Mots-clés SECONDAIRES : génériques, nécessitent combinaison pour être significatifs.
  - Mots-clés d'EXCLUSION : contexte publicitaire non-billetterie → annulent la détection.
"""

import logging
import re
import time
from dataclasses import dataclass, field

import config

logger = logging.getLogger(__name__)

# ── Mots-clés PRIMAIRES ───────────────────────────────────────────────────────
# Très spécifiques au contexte billetterie/spectacle. Un seul suffit à déclencher
# une détection (confidence ≥ 70).

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
    r"la\s+derni[eè]re",          # mention de l'émission cible
]

# ── Mots-clés SECONDAIRES ─────────────────────────────────────────────────────
# Génériques : seuls ils ne signifient rien (pub, météo, sport…).
# Déclenchent une détection uniquement s'ils accompagnent au moins un primaire
# OU s'ils sont au moins deux combinés ensemble.

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
# Signaux forts de contexte publicitaire non-billetterie.
# Leur présence ramène la confidence à 0.

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

# ── Compilation des patterns ───────────────────────────────────────────────────
_PRIMARY   = [(p, re.compile(p, re.IGNORECASE)) for p in _RAW_PRIMARY]
_SECONDARY = [(p, re.compile(p, re.IGNORECASE)) for p in _RAW_SECONDARY]
_EXCLUSION = [re.compile(p, re.IGNORECASE) for p in _RAW_EXCLUSION]


def _find_matches(text: str, patterns: list[tuple[str, re.Pattern[str]]]) -> list[str]:
    """Retourne la liste des patterns bruts (chaînes) qui ont matché dans le texte."""
    return [raw for raw, compiled in patterns if compiled.search(text)]


def _is_excluded(text: str) -> bool:
    """Retourne True si un mot-clé d'exclusion est présent dans le texte."""
    return any(p.search(text) for p in _EXCLUSION)


def _compute_confidence(
    primary_hits: list[str],
    secondary_hits: list[str],
) -> tuple[int, bool]:
    """
    Calcule (confidence, action_required) selon les règles de combinaison.

    Règles :
      - Exclusion présente                               → (0, False)  [géré avant l'appel]
      - 0 primaire, < 2 secondaires                      → (0, False)
      - 0 primaire, ≥ 2 secondaires                      → (30, False)
      - 1 primaire seul (0 secondaire)                   → (70, False)
      - 1 primaire + ≥ 1 secondaire                      → (85, True)
      - 2 primaires                                      → (90, True)
      - ≥ 3 primaires                                    → (98, True)
    """
    np = len(primary_hits)
    ns = len(secondary_hits)

    if np == 0:
        if ns >= 2:
            return 30, False
        return 0, False
    if np == 1:
        if ns == 0:
            return 70, False
        return 85, True
    if np == 2:
        return 90, True
    return 98, True


def _extract_relevant_sentences(
    text: str,
    primary_compiled: list[re.Pattern[str]],
    secondary_compiled: list[re.Pattern[str]],
) -> str:
    """Retourne les phrases contenant au moins un pattern matché."""
    all_patterns = primary_compiled + secondary_compiled
    sentences = re.split(r"[.!?;\n]+", text)
    relevant: list[str] = []
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if any(p.search(sentence) for p in all_patterns):
            relevant.append(sentence)
    return " | ".join(relevant) if relevant else ""


@dataclass
class DetectionResult:
    """Résultat de la détection par mots-clés."""
    detected: bool
    confidence: int
    extracted_info: str
    action_required: bool
    matched_keywords: list[str] = field(default_factory=list)


class Detector:
    """Détecte les annonces de billets par analyse locale (mots-clés + regex)."""

    def __init__(self) -> None:
        # Timestamp de la dernière notification envoyée (pour le cooldown)
        self._last_notification_time: float = 0.0

    def analyze(self, text: str) -> DetectionResult:
        """
        Analyse un texte transcrit pour détecter une annonce de billets.

        Args:
            text: Texte transcrit à analyser.

        Returns:
            DetectionResult avec detected=False et confidence=0 si rien n'est trouvé.
        """
        if not text.strip():
            logger.debug("Texte vide, analyse ignorée.")
            return DetectionResult(
                detected=False, confidence=0, extracted_info="", action_required=False
            )

        # Vérification d'exclusion en priorité
        if _is_excluded(text):
            logger.debug("Contexte publicitaire détecté (mot-clé d'exclusion) — ignoré.")
            return DetectionResult(
                detected=False, confidence=0, extracted_info="", action_required=False
            )

        primary_hits   = _find_matches(text, _PRIMARY)
        secondary_hits = _find_matches(text, _SECONDARY)

        confidence, action_required = _compute_confidence(primary_hits, secondary_hits)
        detected = confidence >= 70  # seuil minimal pour comptabiliser une détection

        matched_keywords = primary_hits + secondary_hits

        extracted_info = ""
        if detected or confidence == 30:
            p_comp = [c for r, c in _PRIMARY   if r in primary_hits]
            s_comp = [c for r, c in _SECONDARY if r in secondary_hits]
            extracted_info = _extract_relevant_sentences(text, p_comp, s_comp)

        if confidence >= 70:
            logger.info(
                f"Détection positive — confidence={confidence} "
                f"action_required={action_required} "
                f"mots-clés={matched_keywords}"
            )
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
        )

    def should_notify(self, result: DetectionResult) -> bool:
        """
        Détermine si une notification doit être envoyée.

        Conditions :
        - confidence > 80
        - action_required = True
        - Pas de notification envoyée dans les DETECTION_COOLDOWN_MINUTES dernières minutes
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
