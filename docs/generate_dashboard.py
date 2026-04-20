"""
generate_dashboard.py — Met à jour l'URL du Gist dans docs/index.html.

Appelé après chaque run de surveillance par le job deploy-pages.
Usage : python docs/generate_dashboard.py <gist_raw_url>
        python docs/generate_dashboard.py  (sans argument : efface l'URL)
"""

import re
import sys
from pathlib import Path

DASHBOARD = Path(__file__).parent / "index.html"
PLACEHOLDER = "GIST_RAW_URL_PLACEHOLDER"


def update_gist_url(new_url: str) -> None:
    """Remplace l'URL du Gist dans index.html."""
    content = DASHBOARD.read_text(encoding="utf-8")

    # Remplacer toute URL Gist existante ou le placeholder
    pattern = r'(const GIST_RAW_URL\s*=\s*")[^"]*(")'
    replacement = rf'\g<1>{new_url}\g<2>'

    new_content, count = re.subn(pattern, replacement, content)
    if count == 0:
        print(f"AVERTISSEMENT : pattern non trouvé dans {DASHBOARD}", file=sys.stderr)
        return

    DASHBOARD.write_text(new_content, encoding="utf-8")
    print(f"docs/index.html mis à jour avec l'URL Gist : {new_url[:60]}…")


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else PLACEHOLDER
    update_gist_url(url)
