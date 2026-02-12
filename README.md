# BunnyTweets – Twitter Multi-Account Automation

Automatisches Twitter/X Multi-Account Management System. Postet Content aus Google Drive, fuehrt gezielt Retweets durch und nutzt Dolphin Anty fuer Browser-Isolation.

## Features

- **Multi-Account**: Beliebig viele Twitter-Accounts parallel verwalten
- **Dolphin Anty Integration**: Jeder Account laeuft in eigenem Browser-Profil mit eigenem Fingerprint
- **Google Drive Sync**: Automatischer Download und Post von Bildern/Videos aus zugewiesenen Drive-Ordnern
- **Geplantes Posten**: Konfigurierbare Posting-Zeiten pro Account
- **Automatisches Retweeten**: 3 Retweets/Tag von konfigurierbaren Ziel-Profilen, verteilt ueber Zeitfenster
- **Duplikat-Schutz**: Bereits geretweetete Tweets werden nicht erneut geteilt
- **State Tracking**: SQLite-Datenbank fuer zuverlaessiges State-Management
- **Docker-ready**: Einfaches Deployment via Docker Compose

## Voraussetzungen

- Python 3.10+
- [Dolphin Anty](https://dolphin-anty.com/) (lokal installiert und laufend)
- Google Cloud Projekt mit aktivierter Drive API (Service Account)
- Twitter-Accounts, die in Dolphin Anty Profilen eingeloggt sind

## Installation

### Option A: Direkt auf dem Server

```bash
# Repository klonen
git clone https://github.com/BigMarc/bunnytweets /opt/bunnytweets
cd /opt/bunnytweets

# VPS-Setup ausfuehren (Ubuntu/Debian, als root)
chmod +x setup_vps.sh
sudo ./setup_vps.sh

# Oder manuell:
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Option B: Docker

```bash
cd /opt/bunnytweets
docker compose up -d
```

## Konfiguration

### 1. Settings

```bash
cp config/settings.yaml.example config/settings.yaml
```

Wichtige Einstellungen in `config/settings.yaml`:

| Feld | Beschreibung |
|------|-------------|
| `timezone` | Standard-Zeitzone (Default: `America/New_York`) |
| `dolphin_anty.host` | Dolphin Anty Host (Default: `localhost`) |
| `dolphin_anty.port` | Dolphin Anty Port (Default: `3001`) |
| `google_drive.credentials_file` | Pfad zur Service-Account JSON-Datei |
| `delays.*` | Min/Max Verzoegerungen fuer Anti-Detection |
| `logging.level` | Log-Level: DEBUG, INFO, WARNING, ERROR |

### 2. Accounts

```bash
cp config/accounts.yaml.example config/accounts.yaml
```

Jeder Account braucht:

- **name**: Eindeutiger Name
- **twitter.dolphin_profile_id**: Die Profil-ID aus Dolphin Anty
- **google_drive.folder_id**: Google Drive Ordner-ID
- **posting.schedule**: Liste von Uhrzeiten
- **retweeting.target_profiles**: Ziel-Profile fuer Retweets
- **retweeting.time_windows**: Zeitfenster fuer Retweets

### 3. Google Drive API Setup

> **Wichtig:** Du brauchst einen **Service Account** (NICHT "OAuth 2.0 Client ID").
> Ein Service Account arbeitet automatisch im Hintergrund ohne Browser-Login –
> genau das, was eine Automation braucht.

**Schritt 1 – Google Cloud Projekt erstellen**
1. Gehe zu https://console.cloud.google.com/
2. Klicke oben auf "Projekt auswaehlen" > "Neues Projekt"
3. Gib einen Namen ein (z.B. "BunnyTweets"), klicke "Erstellen"

**Schritt 2 – Google Drive API aktivieren**
1. Im Projekt: Gehe zu **APIs & Services > Bibliothek**
2. Suche nach "Google Drive API"
3. Klicke darauf, dann auf **Aktivieren**

**Schritt 3 – Service Account erstellen**
1. Gehe zu **APIs & Services > Anmeldedaten** (Credentials)
2. Klicke oben auf **+ Anmeldedaten erstellen**
3. Waehle **Dienstkonto** (Service Account) – NICHT "OAuth-Client-ID"
4. Gib einen Namen ein (z.B. "bunnytweets-drive"), klicke "Erstellen"
5. Ueberspringe die optionalen Berechtigungsschritte, klicke "Fertig"
6. Klicke auf das neu erstellte Dienstkonto in der Liste
7. Gehe zum Tab **Schluessel** (Keys)
8. Klicke **Schluessel hinzufuegen > Neuen Schluessel erstellen > JSON**
9. Eine `.json`-Datei wird heruntergeladen – das sind deine Zugangsdaten
10. Speichere sie als `config/credentials/google_credentials.json` im Projekt

**Schritt 4 – Drive-Ordner mit dem Service Account teilen**
1. Oeffne die heruntergeladene JSON-Datei und finde das Feld `"client_email"` – es sieht so aus:
   ```
   bunnytweets-drive@dein-projekt.iam.gserviceaccount.com
   ```
2. Gehe zu Google Drive im Browser
3. Fuer jeden Ordner, den BunnyTweets lesen soll:
   - Rechtsklick auf den Ordner > **Freigeben**
   - Fuege die `client_email`-Adresse als Betrachter (Viewer) hinzu
   - Klicke "Senden"

**Schritt 5 – Ordner-ID ermitteln**
- Oeffne den Ordner in Google Drive
- Die URL sieht so aus: `https://drive.google.com/drive/folders/1ABCdefGHIjklMNO`
- Der Teil nach `/folders/` ist deine `folder_id` fuer `accounts.yaml`

### 4. Dolphin Anty Setup

1. Installiere und starte Dolphin Anty
2. Erstelle fuer jeden Twitter-Account ein eigenes Browser-Profil
3. Logge dich in jedem Profil manuell bei Twitter ein (einmalig)
4. Notiere die Profil-IDs (sichtbar in der URL oder ueber die API)
5. Die Local API laeuft standardmaessig auf `http://localhost:3001`

Profil-IDs finden:
```bash
curl http://localhost:3001/v1.0/browser_profiles | python3 -m json.tool
```

## Verwendung

### Automation starten

```bash
# Alle aktiven Accounts
python main.py

# Status anzeigen
python main.py --status

# Verbindungstest
python main.py --test
```

### Was passiert beim Start?

1. Konfiguration wird geladen
2. Fuer jeden aktivierten Account wird das Dolphin Anty Profil gestartet
3. Selenium verbindet sich mit dem Browser
4. Login-Status wird geprueft (muss bereits eingeloggt sein)
5. Scheduler plant alle Jobs (Posting, Retweets, Drive-Sync)
6. System laeuft im Hintergrund bis Ctrl+C oder SIGTERM

### Posting-Ablauf

1. Zur geplanten Zeit (oder beim Drive-Sync-Intervall) prueft das System den Google Drive Ordner
2. Neue Dateien werden heruntergeladen
3. Dateien mit gleichem Dateinamen (ohne Extension) werden gruppiert:
   - `post1.jpg` + `post1.txt` = Ein Tweet mit Bild und Text
   - `standalone.mp4` = Video-Tweet ohne Text
4. Medien werden validiert (Groesse, Format)
5. Tweet wird per Selenium gepostet
6. Datei wird als "verarbeitet" markiert

### Retweet-Ablauf

1. System prueft die konfigurierten Zeitfenster
2. Besucht die Profile der Ziel-Accounts
3. Waehlt den neuesten, noch nicht geretweeteten Tweet
4. Fuehrt den Retweet durch
5. Speichert den Retweet in der Datenbank (Duplikat-Schutz)
6. Maximal 3 Retweets pro Tag (konfigurierbar)

## Projektstruktur

```
bunnytweets/
├── config/
│   ├── accounts.yaml.example
│   ├── settings.yaml.example
│   └── credentials/
├── src/
│   ├── core/              # Config, Logger, Database
│   ├── dolphin_anty/      # API Client, Profile Manager
│   ├── google_drive/      # Drive Client, File Monitor, Media Handler
│   ├── twitter/           # Automation, Poster, Retweeter
│   └── scheduler/         # Job Manager, Queue Handler
├── data/
│   ├── downloads/         # Temp. heruntergeladene Medien
│   ├── logs/              # Log-Dateien
│   └── database/          # SQLite State-DB
├── tests/
├── main.py
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── setup_vps.sh
```

## Troubleshooting

### Browser startet nicht

- Pruefen ob Dolphin Anty laeuft: `curl http://localhost:3001/v1.0/browser_profiles`
- Profil-ID korrekt in `accounts.yaml`?
- Port-Konflikte pruefen

### "Not logged in" Fehler

- Dolphin Anty Profil manuell oeffnen und bei Twitter einloggen
- Session-Cookies werden automatisch gespeichert

### Google Drive Dateien werden nicht erkannt

- Service Account hat Zugriff auf den Ordner? (Ordner muss geteilt sein)
- `credentials_file` Pfad korrekt?
- `folder_id` stimmt?

### Rate Limits

- Twitter erlaubt max. 300 Tweets/3h und 2400/Tag
- Retweets zaehlen als Tweets
- Bei Rate-Limit-Fehlern pausiert das System automatisch

### Logs pruefen

```bash
# Hauptlog
tail -f data/logs/automation_$(date +%Y-%m-%d).log

# Account-spezifisch
tail -f data/logs/MyMainAccount_$(date +%Y-%m-%d).log
```

## Umgebungsvariablen

| Variable | Beschreibung |
|----------|-------------|
| `DOLPHIN_ANTY_TOKEN` | API-Token fuer Dolphin Anty (optional) |
| `DOLPHIN_ANTY_HOST` | Host ueberschreiben (Default: localhost) |
| `DOLPHIN_ANTY_PORT` | Port ueberschreiben (Default: 3001) |
| `GOOGLE_CREDENTIALS_FILE` | Pfad zur Google Credentials JSON |
| `TZ` | Zeitzone (Default: America/New_York) |
