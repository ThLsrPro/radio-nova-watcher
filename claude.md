# Radio Nova Watcher

## Objectif
Application Python qui écoute en continu le flux live de Radio Nova,
transcrit la parole en temps réel et détecte toute annonce de mise en vente
de places pour l'émission "La dernière" enregistrée à l'Européen (Paris).
Une notification push est envoyée via ntfy.sh dès la détection.
Conçu pour tourner automatiquement chaque dimanche sur GitHub Actions.

## Flux audio
URL : http://radionova.ice.infomaniak.ch/radionova-256.aac

## Stack technique
- Python 3.11+
- FFmpeg (capture et segmentation du flux AAC)
- Groq API / whisper-large-v3 (transcription cloud, sans GPU)
- Détection locale par mots-clés et expressions régulières (pas d'API externe)
- ntfy.sh (notifications push via HTTP POST)
- GitHub Actions (exécution automatique chaque dimanche à 18h Paris)

## Structure du projet
- main.py                            → boucle principale + health checks au démarrage
- audio_capture.py                   → capture FFmpeg
- transcriber.py                     → transcription via Groq API
- detector.py                        → détection locale par mots-clés / regex
- notifier.py                        → notifications push via ntfy.sh
- quota_monitor.py                   → suivi des quotas Groq (local + CI)
- config.py                          → variables d'environnement
- .github/workflows/radio_watcher.yml → workflow GitHub Actions

## Health checks au démarrage
Avant de lancer la surveillance, main.py vérifie :
1. Connexion internet (ping ntfy.sh)
2. Accès au flux radio (HEAD sur RADIO_STREAM_URL)
3. Groq API (liste des modèles)
4. FFmpeg (ffmpeg -version)
Une notification ntfy récapitule les résultats.

## Notifications ntfy
- Démarrage : résultats des health checks
- Alerte détection : info extraite + transcription brute + confidence
- Arrêt : durée, chunks traités, nombre de détections

## Quota monitoring (quota_monitor.py)
- Suivi en mémoire (session) + fichier JSON local (logs/quota_tracker.json)
- Reset automatique des compteurs jour/mois
- En CI (GitHub Actions, CI=true) : tracking mémoire uniquement, pas d'I/O fichier
- Seuils d'alerte ntfy : 400 req/jour, 300 req/mois, 600 min audio/mois
- Alerte dédiée sur erreur 429 Groq + pause 60s avant retry
- Résumé quota affiché dans les notifications de démarrage et de fin

## Conventions
- Code commenté en français
- Type hints Python partout
- Logs dans logs/transcriptions.log
- Variables sensibles dans .env (jamais dans le code)

## Commandes utiles
# Activer l'environnement virtuel
source venv/bin/activate

# Lancer l'application
python main.py

# Tester la notification ntfy
python main.py --test-notification
