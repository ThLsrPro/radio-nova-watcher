# Radio Nova Watcher

Application Python qui écoute en continu le flux live de Radio Nova, transcrit la parole
en temps réel via **Groq API (whisper-large-v3)** et détecte toute annonce de mise en vente
de places pour l'émission **"La dernière"** enregistrée à l'Européen (Paris).
Une notification push est envoyée via **ntfy.sh** dès la détection.

Conçu pour tourner chaque dimanche en automatique sur **GitHub Actions**.

---

## Contrôle manuel

Le watcher peut être mis en pause ou déclenché manuellement sans toucher au code.
Le mécanisme repose sur un fichier `control.json` stocké dans le Gist privé.

### Via le dashboard

1. Ouvrir le dashboard GitHub Pages
2. Dans la barre "Contrôle", saisir votre `GIST_TOKEN` et cliquer **Enregistrer**
   (le token est stocké uniquement dans `localStorage`, jamais transmis ailleurs)
3. **Mettre en pause** : cliquer "⏸ Pause" — la surveillance dominicale sera annulée
4. **Reprendre** : cliquer "▶ Reprendre" — la surveillance reprend normalement
5. **Lancer maintenant** : cliquer "⚡ Lancer" — déclenche immédiatement le workflow
   GitHub Actions via l'API (nécessite que le token ait le scope `workflow`)

### Via le terminal (scripts/trigger.py)

```bash
source venv/bin/activate

# Afficher le statut actuel
python scripts/trigger.py --status

# Mettre en pause
python scripts/trigger.py --pause

# Reprendre
python scripts/trigger.py --resume

# Déclencher manuellement (pose manual_trigger=true dans le Gist)
python scripts/trigger.py --start
# Puis déclencher le workflow via l'onglet Actions de GitHub
```

### Fonctionnement de control.json

Fichier JSON stocké dans le Gist sous le nom `control.json` :

```json
{
  "status": "active",        // "active" ou "paused"
  "manual_trigger": false,   // true = lancer même si en pause
  "updated_at": "2026-04-20T18:00:00",
  "updated_by": "dashboard"  // "dashboard" ou "script"
}
```

Logique au démarrage de `main.py` :
- `status == "paused"` ET `manual_trigger == false` → notification ntfy + arrêt propre
- `manual_trigger == true` → reset à false dans le Gist → surveillance normale
- `status == "active"` → surveillance normale

---

## Prérequis système (exécution locale)

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

### 1. Choisir un nom de topic

Choisissez quelque chose d'**imprévisible** pour éviter que d'autres s'y abonnent :
```
radionova-alerte-thomas-x7k2
```

### 2. S'abonner sur mobile

- Téléchargez l'app **ntfy** : [iOS](https://apps.apple.com/app/ntfy/id1625396347) / [Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy)
- Ouvrez l'app → **+** → entrez votre topic → **Subscribe**

### 3. Vérifier dans le navigateur

Accédez à `https://ntfy.sh/{VOTRE_TOPIC}` pour voir les notifications sans application.

### 4. Option avancée — auto-hébergement

```bash
docker run -p 80:80 binwiederhier/ntfy serve
```
Puis renseignez `NTFY_SERVER=https://ntfy.monserveur.fr` dans `.env`.

---

## Remplissage du fichier `.env`

```dotenv
# Clé API Groq
GROQ_API_KEY=gsk_...

# Topic ntfy (choisissez un nom imprévisible)
NTFY_TOPIC=radionova-alerte-thomas-x7k2

# Archivage Gist (optionnel — voir section dédiée)
GIST_TOKEN=ghp_...
GIST_ENABLED=true

# Optionnel — valeurs par défaut déjà configurées
# NTFY_SERVER=https://ntfy.sh
# CHUNK_DURATION_SECONDS=15
# DETECTION_COOLDOWN_MINUTES=30
```

> **Ne commitez jamais votre fichier `.env`**

---

## Lancement local

```bash
source venv/bin/activate
python main.py
```

Au démarrage, le programme effectue une série de **health checks** et envoie
une notification ntfy récapitulative :

```
============================================================
  Radio Nova Watcher — Surveillance en temps réel
============================================================
  Flux radio     : http://radionova.ice.infomaniak.ch/radionova-256.aac
  Transcription  : Groq whisper-large-v3
  Durée chunk    : 15s
  Cooldown       : 30 min
  Topic ntfy     : https://ntfy.sh/radionova-alerte-thomas-x7k2
============================================================

── Health checks ─────────────────────────────────────
  ✅ Internet OK
  ✅ Flux Radio Nova accessible
  ✅ Groq API operationnelle
  ✅ FFmpeg disponible (6.1)
──────────────────────────────────────────────────────

[14:32:01] Et maintenant on reste sur Radio Nova…
[14:32:17] Les billets pour La dernière à l'Européen sont disponibles…
```

À l'arrêt (**Ctrl+C**), une notification de fin est envoyée avec le résumé de session.

---

## Test de notification

```bash
python main.py --test-notification
```

---

## Déploiement GitHub Actions

Le workflow `.github/workflows/radio_watcher.yml` lance la surveillance automatiquement
**chaque dimanche à 18h00 (heure de Paris)** sans serveur à gérer.

### 1. Créer le repo GitHub

```bash
git init
git remote add origin https://github.com/votre-user/radio-nova-watcher.git
git add .
git commit -m "Initial commit"
git push -u origin main
```

> Repo **privé** recommandé pour ne pas exposer le nom de votre topic ntfy.

### 2. Ajouter les secrets GitHub

Dans votre repo : **Settings → Secrets and variables → Actions → New repository secret**

| Secret | Valeur |
|--------|--------|
| `GROQ_API_KEY` | Votre clé Groq |
| `NTFY_TOPIC` | Votre topic ntfy |
| `NTFY_SERVER` | `https://ntfy.sh` (ou votre serveur) |
| `RADIO_STREAM_URL` | URL du flux (optionnel) |
| `CHUNK_DURATION_SECONDS` | `15` (optionnel) |
| `DETECTION_COOLDOWN_MINUTES` | `30` (optionnel) |

### 3. Déclenchement automatique

Le workflow se déclenche chaque dimanche à **17h00 UTC** (= 18h00 Paris en hiver).
En période d'heure d'été (CEST = UTC+2), modifier le cron en `"0 16 * * 0"`.

### 4. Déclenchement manuel

**Actions → Radio Nova Watcher → Run workflow** pour tester sans attendre le dimanche.

### 5. Suivi en temps réel

L'onglet **Actions** du repo affiche les logs en direct pendant l'exécution.

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
2024-03-15 14:32:18 [INFO] notifier — Notification ntfy envoyée (HTTP 200) → https://ntfy.sh/…
```

---

## Archivage sur GitHub Gist

Chaque session est archivée automatiquement dans un **Gist privé** (transcriptions complètes, détections, stats).

### 1. Créer le token GitHub

**github.com → Settings → Developer settings → Personal access tokens → Generate new token**
- Durée : selon vos préférences
- Scope à cocher : **gist** uniquement (rien d'autre)

Copiez le token (`ghp_...`) dans `.env` sous `GIST_TOKEN` et mettez `GIST_ENABLED=true`.

### 2. Premier lancement

Au démarrage, le Gist `radio-nova-watcher-data` est créé automatiquement dans votre compte.
L'ID s'affiche dans le terminal.

### 3. Données archivées

- `sessions.json` : historique complet de toutes les sessions
- `dashboard_data.json` : stats agrégées pour le dashboard

---

## Dashboard GitHub Pages

Visualisation de l'historique en dark mode, accessible sur mobile.

### 1. Activer GitHub Pages

Dans votre repo GitHub : **Settings → Pages → Source : Deploy from a branch**
- Branch : `main`
- Folder : `/docs`

Le dashboard sera disponible sur : `https://<votre-user>.github.io/radio-nova-watcher/`

### 2. URL du Gist dans le dashboard

Après le premier run avec `GIST_ENABLED=true`, le job `deploy-pages` met à jour automatiquement
`docs/index.html` avec l'URL raw du Gist et pousse sur `main`.
GitHub Pages se met à jour dans la foulée.

En local (pour tester avant de pousser) :
```bash
python docs/generate_dashboard.py "https://gist.githubusercontent.com/..."
```

---

## Fonctionnalités avancées

### Watchdog de flux
Si le flux radio s'interrompt plus de 2 minutes, une notification ntfy est envoyée
et des tentatives de reconnexion sont lancées automatiquement (backoff : 10s → 20s → 40s → 80s → 160s).
En cas d'échec définitif, le script se termine proprement avec une alerte.

### Analyse contextuelle multi-chunks
La détection ne se fait pas chunk par chunk mais sur une fenêtre glissante de **3 chunks consécutifs**
(~45 secondes d'audio). Une annonce à cheval sur deux chunks est ainsi capturée.

Un mode **"alerte partielle"** est activé quand la confidence est entre 50 et 84 :
les 3 chunks suivants sont analysés avec un seuil abaissé (60) pour confirmer ou infirmer.

### Check automatique du samedi
Chaque samedi à 18h (Paris), le workflow `weekly_check` lance `healthcheck.py` :
- Vérifie internet, flux radio, API Groq (transcription réelle), FFmpeg et ntfy
- Envoie un rapport ntfy "✅ Tout est prêt pour demain" ou "⚠️ Problème détecté"
- Exécutable en local : `python healthcheck.py`

## Architecture

```
radio-nova-watcher/
├── .github/
│   └── workflows/
│       └── radio_watcher.yml  # Dimanche : surveillance / Samedi : check
├── docs/
│   ├── index.html             # Dashboard GitHub Pages (dark mode, responsive)
│   └── generate_dashboard.py  # Met à jour l'URL Gist dans index.html
├── main.py                    # Boucle principale + health checks
├── audio_capture.py           # Capture FFmpeg + watchdog de flux
├── transcriber.py             # Transcription Groq (whisper-large-v3)
├── detector.py                # Détection mots-clés + contexte multi-chunks
├── notifier.py                # Notifications push via ntfy.sh
├── archiver.py                # Archivage des sessions sur GitHub Gist
├── healthcheck.py             # Check pré-émission autonome (samedi)
├── quota_monitor.py           # Suivi quotas Groq
├── config.py                  # Variables d'environnement
├── .env                       # Votre configuration (à créer, ne pas committer)
├── .env.example               # Template (sans valeurs réelles)
├── requirements.txt           # Dépendances Python
├── logs/
│   ├── transcriptions.log
│   └── app.log
└── tmp_chunks/                # Chunks WAV temporaires (nettoyés automatiquement)
```
