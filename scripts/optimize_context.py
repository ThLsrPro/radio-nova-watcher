#!/usr/bin/env python3
"""
optimize_context.py — Analyse et optimisation de CLAUDE.md pour Claude Code.

Usage :
    python scripts/optimize_context.py              # rapport seul
    python scripts/optimize_context.py --notify     # rapport + ntfy si économie > 20%
    python scripts/optimize_context.py --apply      # supprime les doublons de lignes vides

Rapport :
    CLAUDE.md : X lignes · Y tokens estimés
    Redondances détectées : [liste]
    Sections trop longues : [liste]
    Économie potentielle  : X%
"""

import os
import re
import sys
from collections import Counter
from pathlib import Path

ROOT    = Path(__file__).parent.parent
# Support claude.md (macOS insensible à la casse) et CLAUDE.md
CLAUDE_MD = ROOT / "CLAUDE.md"
if not CLAUDE_MD.exists():
    CLAUDE_MD = ROOT / "claude.md"

MAX_LINES         = 150
MAX_SECTION_LINES = 20
REDUND_THRESHOLD  = 4    # répétitions avant d'être signalé
ECONOMY_THRESHOLD = 20   # % d'économie pour déclencher la notification ntfy


# ── Analyse ───────────────────────────────────────────────────────────────

def count_tokens(text: str) -> int:
    """Estimation rapide : 1 token ≈ 4 caractères."""
    return max(1, len(text) // 4)


STOPWORDS = {
    # Français
    "le","la","les","de","du","des","un","une","en","et","ou","à","au","aux",
    "par","pour","dans","sur","avec","est","sont","que","qui","ne","pas","se",
    "si","ce","il","elle","ils","elles","on","nous","vous","je","tu","cette",
    "tout","plus","très","lors","leur","leurs","dont","mais","donc","car","même",
    # Anglais (code/commentaires)
    "the","of","to","in","is","and","or","a","an","for","on","with","are","be",
    "this","that","it","as","at","by","from","but","not","its","all","has",
}


def find_redundant_words(text: str) -> list[str]:
    """Mots significatifs répétés plus de REDUND_THRESHOLD fois."""
    words  = re.findall(r"\b[a-zA-ZÀ-ÿ]{4,}\b", text.lower())
    counts = Counter(w for w in words if w not in STOPWORDS)
    return [w for w, c in counts.most_common(15) if c > REDUND_THRESHOLD]


def find_long_sections(lines: list[str]) -> list[str]:
    """Sections dépassant MAX_SECTION_LINES lignes de contenu."""
    long_sects: list[str]  = []
    current_title: str     = ""
    content_lines: int     = 0

    for line in lines:
        if re.match(r"^#{1,4}\s", line):
            if current_title and content_lines > MAX_SECTION_LINES:
                long_sects.append(f"{current_title.strip()} ({content_lines} lignes)")
            current_title = line
            content_lines = 0
        else:
            if line.strip():
                content_lines += 1

    if current_title and content_lines > MAX_SECTION_LINES:
        long_sects.append(f"{current_title.strip()} ({content_lines} lignes)")

    return long_sects


def estimate_economy(lines: list[str]) -> int:
    """
    Estime le pourcentage d'économie potentielle.

    Critères :
    - Lignes vides en doublon (supprimables)
    - Lignes de prose longue (> 60 chars, non-code) → raccourcissables d'environ 30%
    """
    saveable_chars = 0
    total_chars    = max(1, sum(len(l) + 1 for l in lines))  # +1 pour newline

    prev_blank = False
    for line in lines:
        is_blank = line.strip() == ""

        # Lignes vides consécutives → supprimables
        if is_blank and prev_blank:
            saveable_chars += 1
        prev_blank = is_blank

        # Lignes de prose longue (pas headers, pas code, pas tableaux)
        stripped = line.strip()
        if (
            len(stripped) > 60
            and not stripped.startswith(("#", "-", "|", "`", "!", "["))
            and not re.match(r"^python|^source|^\$", stripped)
        ):
            saveable_chars += len(stripped) // 3  # ~33% raccourcissable

    return min(99, round(saveable_chars * 100 / total_chars))


# ── Optimisation ──────────────────────────────────────────────────────────

def apply_basic_cleanup(lines: list[str]) -> list[str]:
    """
    Optimisations automatiques sûres :
    - Supprime les lignes vides consécutives (garde au plus une)
    - Supprime les espaces de fin de ligne
    """
    result: list[str] = []
    prev_blank = False

    for line in lines:
        stripped   = line.rstrip()
        is_blank   = stripped == ""

        if is_blank and prev_blank:
            continue  # supprime la ligne vide en doublon

        result.append(stripped)
        prev_blank = is_blank

    return result


# ── Notification ntfy ─────────────────────────────────────────────────────

def send_ntfy_alert(economy: int) -> None:
    """Envoie une notification ntfy si NTFY_TOPIC est configuré."""
    import urllib.request

    server = os.getenv("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    topic  = os.getenv("NTFY_TOPIC", "")
    if not topic:
        print("  NTFY_TOPIC absent — notification ignorée.")
        return

    body = (
        f"CLAUDE.md pourrait etre reduit de {economy}%\n"
        f"Lancez : python scripts/optimize_context.py --apply"
    ).encode("utf-8")

    req = urllib.request.Request(f"{server}/{topic}", data=body, method="POST")
    req.add_header("Title",    "Optimisation contexte suggeree")
    req.add_header("Priority", "default")
    req.add_header("Tags",     "memo,tools")

    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            print(f"  Notification ntfy envoyée (HTTP {resp.status}).")
    except Exception as exc:
        print(f"  Notification ntfy échouée : {exc}")


# ── Point d'entrée ────────────────────────────────────────────────────────

def main() -> None:
    do_notify = "--notify" in sys.argv
    do_apply  = "--apply"  in sys.argv

    if not CLAUDE_MD.exists():
        print(f"Erreur : fichier CLAUDE.md introuvable dans {ROOT}")
        sys.exit(1)

    text  = CLAUDE_MD.read_text(encoding="utf-8")
    lines = text.splitlines()

    tokens     = count_tokens(text)
    redundant  = find_redundant_words(text)
    long_sects = find_long_sections(lines)
    economy    = estimate_economy(lines)
    over_limit = len(lines) > MAX_LINES

    # ── Rapport ──
    print()
    print(f"CLAUDE.md : {len(lines)} lignes · {tokens} tokens estimés")
    print(f"Limite {MAX_LINES} lignes      : {'⚠️  DÉPASSÉE' if over_limit else '✅ OK'}")
    print(f"Redondances détectées  : {', '.join(redundant) if redundant else 'aucune'}")
    print(f"Sections trop longues  : {', '.join(long_sects) if long_sects else 'aucune'}")
    print(f"Économie potentielle   : {economy}%")

    # ── Application des optimisations ──
    if do_apply:
        optimized = apply_basic_cleanup(lines)
        saved     = len(lines) - len(optimized)
        CLAUDE_MD.write_text("\n".join(optimized) + "\n", encoding="utf-8")
        print(f"\n✅ Nettoyage appliqué — {saved} ligne(s) supprimée(s).")
        if saved > 0:
            new_tokens = count_tokens("\n".join(optimized))
            print(f"   Tokens : {tokens} → {new_tokens} (−{tokens - new_tokens})")

    # ── Notification ntfy ──
    if do_notify:
        if economy > ECONOMY_THRESHOLD:
            print(f"\nÉconomie {economy}% > {ECONOMY_THRESHOLD}% — envoi notification ntfy…")
            send_ntfy_alert(economy)
        else:
            print(f"\nÉconomie {economy}% ≤ {ECONOMY_THRESHOLD}% — pas de notification.")

    print()


if __name__ == "__main__":
    main()
