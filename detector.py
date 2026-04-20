"""
detector.py — Détection locale par mots-clés et expressions régulières.
Aucun appel API externe : analyse entièrement en mémoire.
"""

import logging
import re
import time
from dataclasses import dataclass, field

import config

logger = logging.getLogger(__name__)

# ── Groupes de mots-clés ──────────────────────────────────────────────────────
# Chaque groupe représente une catégorie sémantique distincte.
# Trouver des correspondances dans plusieurs groupes augmente la confidence.

# Groupe 1 — Émission / lieu cible
_PATTERNS_CIBLE: list[str] = [
    r"la\s+derni[eè]re",
    r"l['']europ[eé]en",
    r"europ[eé]en\b",
]

# Groupe 2 — Billetterie / places / billets
_PATTERNS_BILLET: list[str] = [
    r"\bbillet(?:s|terie)?\b",
    r"\bplace(?:s)?\b",
    r"\bticket(?:s)?\b",
    r"\breservation\b",
    r"\br[eé]servation\b",
    r"\br[eé]server\b",
]

# Groupe 3 — Action / disponibilité
_PATTERNS_ACTION: list[str] = [
    r"\ben\s+vente\b",
    r"\bdisponible(?:s)?\b",
    r"\b[àa]\s+partir\s+de\b",
    r"\bd[eè]s\s+(?:le|ce|maintenant|aujourd)",
    r"\bouverture\b",
    r"\bachat\b",
    r"\bacheter\b",
    r"\boutilisez?\b",
    r"\bprocurez?[-\s]vous\b",
]

# Groupe 4 — Sites / liens de billetterie
_PATTERNS_SITE: list[str] = [
    r"\bfnac(?:\.com)?\b",
    r"\bdigitick\b",
    r"\bshotgun\b",
    r"\bbilletweb\b",
    r"\bticketmaster\b",
    r"\bweezevent\b",
    r"\blivenation\b",
    r"\bhelloasso\b",
    r"https?://\S+",          # tout lien URL
]

# Compilation des groupes en objets regex (insensible à la casse, accents inclus)
_GROUPS: list[tuple[str, list[re.Pattern[str]]]] = [
    ("cible",  [re.compile(p, re.IGNORECASE) for p in _PATTERNS_CIBLE]),
    ("billet", [re.compile(p, re.IGNORECASE) for p in _PATTERNS_BILLET]),
    ("action", [re.compile(p, re.IGNORECASE) for p in _PATTERNS_ACTION]),
    ("site",   [re.compile(p, re.IGNORECASE) for p in _PATTERNS_SITE]),
]


def _confidence_from_match_count(count: int) -> int:
    """Calcule la confidence selon le nombre de groupes ayant matché."""
    if count >= 3:
        return 95
    if count == 2:
        return 75
    if count == 1:
        return 50
    return 0


def _extract_matched_sentences(text: str, matched_patterns: list[re.Pattern[str]]) -> str:
    """
    Retourne les phrases du texte qui contiennent au moins un pattern matché.
    Utilisé pour remplir extracted_info avec le contexte exact.
    """
    sentences = re.split(r"[.!?;\n]+", text)
    relevant: list[str] = []
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        for pattern in matched_patterns:
            if pattern.search(sentence):
                relevant.append(sentence)
                break  # une seule fois par phrase
    return " | ".join(relevant) if relevant else ""


@dataclass
class DetectionResult:
    """Résultat de la détection par mots-clés."""
    detected: bool
    confidence: int
    extracted_info: str
    action_required: bool
    matched_groups: list[str] = field(repr=False, default_factory=list)


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

        matched_groups: list[str] = []
        all_matched_patterns: list[re.Pattern[str]] = []

        # Parcourir chaque groupe et vérifier si au moins un pattern matche
        for group_name, patterns in _GROUPS:
            for pattern in patterns:
                if pattern.search(text):
                    matched_groups.append(group_name)
                    all_matched_patterns.extend(patterns)  # pour l'extraction du contexte
                    break  # un seul match suffit par groupe

        confidence = _confidence_from_match_count(len(matched_groups))
        detected = confidence >= 50  # au moins 1 groupe matché

        # extracted_info : phrases contenant les mots-clés détectés
        extracted_info = ""
        if detected:
            extracted_info = _extract_matched_sentences(text, all_matched_patterns)

        # action_required : vrai si on a à la fois un élément cible ET billet/action/site
        has_cible = "cible" in matched_groups
        has_billet_or_action = bool(
            {"billet", "action", "site"} & set(matched_groups)
        )
        action_required = has_cible and has_billet_or_action

        if detected:
            logger.debug(
                f"Groupes matchés : {matched_groups} — "
                f"confidence={confidence} — action_required={action_required}"
            )

        return DetectionResult(
            detected=detected,
            confidence=confidence,
            extracted_info=extracted_info,
            action_required=action_required,
            matched_groups=matched_groups,
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
