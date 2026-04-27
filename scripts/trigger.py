"""
trigger.py — Contrôle manuel du watcher depuis le terminal.

Usage :
    python scripts/trigger.py --status    # Affiche le statut actuel
    python scripts/trigger.py --pause     # Met la surveillance en pause
    python scripts/trigger.py --resume    # Reprend la surveillance
    python scripts/trigger.py --start     # Déclenche manuellement au prochain run
"""

import argparse
import logging
import sys
from pathlib import Path

# Résoudre les imports depuis la racine du projet
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def cmd_status(archiver) -> None:
    ctrl = archiver.get_control()
    status = ctrl.get("status", "active")
    trigger = ctrl.get("manual_trigger", False)
    updated = ctrl.get("updated_at", "—")
    by = ctrl.get("updated_by", "—")

    print("\n── Statut du watcher ─────────────────────────────────")
    print(f"  Statut          : {'⏸ EN PAUSE' if status == 'paused' else '▶  ACTIF'}")
    print(f"  Déclenchement   : {'⚡ En attente' if trigger else 'Non'}")
    print(f"  Dernière modif  : {updated} (par {by})")
    print("──────────────────────────────────────────────────────\n")


def cmd_pause(archiver) -> None:
    from notifier import send_control_notification
    archiver.set_control(status="paused")
    logger.info("Surveillance mise en pause.")
    send_control_notification(
        "Mise en pause",
        "Le watcher ne se lancera pas au prochain dimanche.\n"
        "Pour reprendre : python scripts/trigger.py --resume"
    )
    cmd_status(archiver)


def cmd_resume(archiver) -> None:
    from notifier import send_control_notification
    archiver.set_control(status="active")
    logger.info("Surveillance réactivée.")
    send_control_notification(
        "Reprise de la surveillance",
        "Le watcher se lancera normalement dimanche prochain."
    )
    cmd_status(archiver)


def cmd_start(archiver) -> None:
    from notifier import send_control_notification
    # Réactiver en plus de poser le flag manual_trigger
    archiver.set_control(status="active", manual_trigger=True)
    logger.info("Déclenchement manuel programmé.")
    send_control_notification(
        "Declenchement manuel programme",
        "manual_trigger=true defini dans le Gist.\n"
        "Declenchez le workflow via GitHub Actions (workflow_dispatch) pour lancer immediatement."
    )
    cmd_status(archiver)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Radio Nova Watcher — Contrôle manuel via le Gist."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--status",  action="store_true", help="Affiche le statut actuel")
    group.add_argument("--pause",   action="store_true", help="Met la surveillance en pause")
    group.add_argument("--resume",  action="store_true", help="Reprend la surveillance")
    group.add_argument("--start",   action="store_true", help="Déclenche manuellement")
    args = parser.parse_args()

    from archiver import GistArchiver
    archiver = GistArchiver()

    if not archiver.is_enabled:
        logger.error("Gist désactivé (GIST_ENABLED=false ou GIST_TOKEN absent) — impossible de contrôler le watcher.")
        sys.exit(1)

    if args.status:
        cmd_status(archiver)
    elif args.pause:
        cmd_pause(archiver)
    elif args.resume:
        cmd_resume(archiver)
    elif args.start:
        cmd_start(archiver)


if __name__ == "__main__":
    main()
