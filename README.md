# Radio Nova Watcher

Application Python qui écoute en continu le flux live de Radio Nova, transcrit la parole
en temps réel et détecte toute annonce de mise en vente de places pour l'émission
**"La dernière"** enregistrée à l'Européen (Paris). Une notification push est envoyée
via **ntfy.sh** dès la détection.

---

## Prérequis système

| Outil | Version minimale | Installation |
|-------|-----------------|--------------|
| Python | 3.11+ | [python.org](https://www.python.org) |
| FFmpeg | 4.x+ | `brew install ffmpeg` (macOS) / `apt install ffmpeg` (Linux) |
| pip | récent | inclus avec Python |

Vérifications :
```bash
python3 --version   # Python 3.11+
ffmpeg -version     # FFmpeg 4.x+
```

---

## Installation pas à pas

```bash
# 1. Cloner ou télécharger le projet
cd radio-nova-watcher

# 2. Créer et activer l'environnement virtuel
python3 -m venv venv
source venv/bin/activate        # macOS / Linux
# venv\Scripts\activate         # Windows

# 3. Installer les dépendances
pip install -r requirements.txt

# 4. Copier le template d'environnement
cp .env.example .env
```

---

## Configuration des notifications ntfy

ntfy.sh est un service de notifications push **gratuit, sans compte, sans inscription**.
Le principe : vous publiez sur un topic, les abonnés reçoivent la notification.

### 1. Choisir un nom de topic

Le topic est simplement une chaîne de caractères dans l'URL.
Choisissez quelque chose d'**imprévisible** pour éviter que d'autres s'y abonnent :

```
radionova-alerte-thomas-x7k2
```

### 2. S'abonner sur mobile

- Téléchargez l'app **ntfy** : [iOS](https://apps.apple.com/app/ntfy/id1625396347) / [Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy)
- Ouvrez l'app → **+** → entrez votre topic → **Subscribe**

### 3. Vérifier dans le navigateur

Accédez à `https://ntfy.sh/{VOTRE_TOPIC}` pour voir les notifications en temps réel
sans application.

### 4. Option avancée — auto-hébergement

Pour plus de confidentialité, ntfy peut être auto-hébergé :
```bash
docker run -p 80:80 binwiederhier/ntfy serve
```
Puis renseignez `NTFY_SERVER=https://ntfy.monserveur.fr` dans `.env`.

---

## Remplissage du fichier `.env`

Ouvrez `.env` et ajustez les variables :

```dotenv
# Nom unique de votre topic (rendez-le imprévisible)
NTFY_TOPIC=radionova-alerte-thomas-x7k2

# Serveur ntfy (laisser par défaut ou pointer vers votre instance)
NTFY_SERVER=https://ntfy.sh

# Optionnel — valeurs par défaut déjà configurées
# WHISPER_MODEL=small
# CHUNK_DURATION_SECONDS=15
# DETECTION_COOLDOWN_MINUTES=30
```

> **Ne commitez jamais votre fichier `.env`** — le nom de topic y est inscrit.

---

## Lancement

```bash
# Activer l'environnement virtuel si ce n'est pas déjà fait
source venv/bin/activate

# Lancer la surveillance
python main.py
```

Vous verrez dans le terminal toutes les transcriptions en temps réel :

```
============================================================
  Radio Nova Watcher — Surveillance en temps réel
============================================================
  Flux radio     : http://radionova.ice.infomaniak.ch/radionova-256.aac
  Modèle Whisper : small
  Durée chunk    : 15s
  Cooldown       : 30 min
  Topic ntfy     : https://ntfy.sh/radionova-alerte-thomas-x7k2
============================================================

[14:32:01] Et maintenant on reste sur Radio Nova avec la suite de la programmation…
[14:32:17] Les billets pour La dernière à l'Européen sont disponibles dès maintenant…
```

Arrêt propre : **Ctrl+C**

---

## Test de notification

Pour vérifier que la configuration ntfy est correcte sans lancer la surveillance :

```bash
python main.py --test-notification
```

Le terminal affiche l'URL du topic. Une notification de test apparaît sur votre mobile
et/ou dans le navigateur.

---

## Format des logs

### `logs/transcriptions.log` — transcriptions brutes
```
[2024-03-15 14:32:01] [chunk_000042.wav] Et maintenant on reste sur Radio Nova…
[2024-03-15 14:32:17] [chunk_000043.wav] Les billets pour La dernière sont disponibles…
```

### `logs/app.log` — logs applicatifs
```
2024-03-15 14:32:00 [INFO] __main__ — Initialisation des modules…
2024-03-15 14:32:05 [INFO] __main__ — Tous les modules sont prêts. Démarrage de la surveillance.
2024-03-15 14:32:17 [INFO] detector — Détection positive ! confidence=95 action_required=True
2024-03-15 14:32:17 [INFO] __main__ — Envoi de la notification ntfy…
2024-03-15 14:32:18 [INFO] notifier — Notification ntfy envoyée (HTTP 200) → https://ntfy.sh/…
2024-03-15 14:32:18 [INFO] __main__ — Notification envoyée avec succès.
```

---

## Architecture

```
radio-nova-watcher/
├── main.py           # Boucle principale de surveillance
├── audio_capture.py  # Capture FFmpeg + segmentation en chunks WAV
├── transcriber.py    # Transcription Whisper (modèle "small", langue fr)
├── detector.py       # Détection locale par mots-clés et regex
├── notifier.py       # Envoi push via ntfy.sh
├── config.py         # Variables d'environnement
├── .env              # Votre configuration (à créer, ne pas committer)
├── .env.example      # Template (sans valeurs réelles)
├── requirements.txt  # Dépendances Python
├── logs/
│   ├── transcriptions.log
│   └── app.log
└── tmp_chunks/       # Chunks WAV temporaires (nettoyés automatiquement)
```
