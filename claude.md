# Radio Nova Watcher

## Objectif
Application Python qui écoute en continu le flux live de Radio Nova,
transcrit la parole en temps réel et détecte toute annonce de mise en vente
de places pour l'émission "La dernière" enregistrée à l'Européen (Paris).
Une notification push est envoyée via ntfy.sh dès la détection.

## Flux audio
URL : http://radionova.ice.infomaniak.ch/radionova-256.aac

## Stack technique
- Python 3.11+
- FFmpeg (capture et segmentation du flux AAC)
- OpenAI Whisper local (transcription, modèle "small")
- Détection locale par mots-clés et expressions régulières (pas d'API externe)
- ntfy.sh (notifications push via HTTP POST)

## Structure du projet
- main.py           → boucle principale
- audio_capture.py  → capture FFmpeg
- transcriber.py    → transcription Whisper
- detector.py       → détection locale par mots-clés / regex
- notifier.py       → envoi push via ntfy.sh
- config.py         → variables d'environnement

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
