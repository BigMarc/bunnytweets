# BunnyTweets - Twitter Multi-Account Automation

A fully automated Twitter/X multi-account management system. Posts content from Google Drive, performs scheduled retweets, and uses anti-detect browsers (GoLogin or Dolphin Anty) for browser isolation. Comes with a **web dashboard** for easy configuration and live monitoring.

---

## Table of Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
  - [Step 1: Clone the Repository](#step-1-clone-the-repository)
  - [Step 2: Create a Virtual Environment](#step-2-create-a-virtual-environment)
  - [Step 3: Install Dependencies](#step-3-install-dependencies)
  - [Step 4: Run the Setup Wizard](#step-4-run-the-setup-wizard)
- [Configuration](#configuration)
  - [Option A: Web Dashboard (Recommended)](#option-a-web-dashboard-recommended)
  - [Option B: Setup Wizard (CLI)](#option-b-setup-wizard-cli)
  - [Option C: Manual YAML Editing](#option-c-manual-yaml-editing)
- [Anti-Detect Browser Setup](#anti-detect-browser-setup)
  - [GoLogin Setup (Default)](#gologin-setup-default)
  - [Dolphin Anty Setup (Alternative)](#dolphin-anty-setup-alternative)
- [Google Drive Setup (Optional)](#google-drive-setup-optional)
- [Usage](#usage)
  - [Starting the Web Dashboard](#starting-the-web-dashboard)
  - [Starting the Desktop App](#starting-the-desktop-app)
  - [Starting the Automation (CLI)](#starting-the-automation-cli)
  - [All CLI Commands](#all-cli-commands)
- [Web Dashboard Guide](#web-dashboard-guide)
  - [Dashboard Page](#dashboard-page)
  - [Settings Page](#settings-page)
  - [Accounts Page](#accounts-page)
  - [Generator Page](#generator-page)
  - [Analytics Page](#analytics-page)
  - [Logs Page](#logs-page)
- [How It Works](#how-it-works)
  - [Posting Flow](#posting-flow)
  - [Retweet Flow](#retweet-flow)
  - [Scheduling](#scheduling)
- [Configuration Reference](#configuration-reference)
  - [settings.yaml](#settingsyaml)
  - [accounts.yaml](#accountsyaml)
- [Environment Variables](#environment-variables)
- [Desktop App (Build from Source)](#desktop-app-build-from-source)
- [Docker Deployment](#docker-deployment)
- [Project Structure](#project-structure)
- [Troubleshooting](#troubleshooting)

---

## Features

- **Multi-Account Support** - Manage as many Twitter/X accounts as you want, running in parallel
- **Anti-Detect Browser Integration** - Each account runs in its own isolated browser profile with a unique fingerprint. Supports **GoLogin** (default) and **Dolphin Anty**
- **Web Dashboard** - Full browser-based UI for configuration, live monitoring, log viewing, and manual controls
- **Google Drive Sync** - Automatically downloads and posts images/videos from assigned Google Drive folders
- **Scheduled Posting** - Configure exact posting times per account (e.g., 09:00, 15:00, 20:00)
- **Content Generator** - Manage title categories and CTA (call-to-action) self-comment texts via the dashboard
- **Automated Retweeting** - Retweets from configurable target profiles with daily limits and time windows
- **Auto-Reply** - Automatically reply to tweets from target profiles using per-account reply templates
- **Human-Like Simulation** - Browsing sessions that scroll, like, and read tweets to mimic real user behavior
- **Duplicate Protection** - Already-retweeted tweets and already-posted files are tracked in the database and never processed twice
- **Analytics Dashboard** - Visual charts for daily activity, success/failure rates, and per-account stats
- **Discord Notifications** - Webhook alerts for errors, paused accounts, and auto-recovery events
- **Auto-Recovery** - Crashed browser profiles are automatically restarted and re-wired
- **State Tracking** - SQLite database for reliable state management across restarts
- **Interactive Setup Wizard** - Step-by-step CLI wizard for first-time configuration
- **Human-Like Behavior** - Randomized delays for typing, clicking, and page loads to avoid detection
- **Per-Account Logging** - Separate log files for each account plus a main log, with daily rotation
- **Desktop App** - Run as a native desktop app with a system tray icon (macOS `.app` / Windows `.exe`)
- **Docker-Ready** - Deploy with Docker Compose in minutes

---

## Requirements

Before installing BunnyTweets, make sure you have:

1. **Python 3.10 or higher** - Check with `python3 --version`
2. **An anti-detect browser** - Either one:
   - [GoLogin](https://gologin.com/) (recommended, set as default) - Desktop app must be installed and running
   - [Dolphin Anty](https://dolphin-anty.com/) - Desktop app must be installed and running
3. **A GoLogin or Dolphin Anty API token** - Used to start/stop browser profiles programmatically
4. **Twitter/X accounts** - Each account must be logged in inside a browser profile (one profile per account)
5. **(Optional) Google Cloud project** with the Drive API enabled - Only needed if you want to post media from Google Drive

---

## Installation

### Step 1: Clone the Repository

```bash
# Repository klonen
git clone https://github.com/BigMarc/bunnytweets /opt/bunnytweets
cd /opt/bunnytweets
```

You can clone it anywhere you like. `/opt/bunnytweets` is just a suggestion for server deployments.

### Step 2: Create a Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate
```

On Windows:
```bash
python -m venv venv
venv\Scripts\activate
```

### Step 3: Install Dependencies

```bash
pip install -r requirements.txt
```

This installs all required packages: Flask (web dashboard), Selenium (browser automation), SQLAlchemy (database), APScheduler (job scheduling), and more.

### Step 4: Run the Setup Wizard

```bash
python main.py --setup
```

The interactive wizard will walk you through:

1. **Choose your browser provider** - GoLogin (default) or Dolphin Anty
2. **Enter your API token** - The token from your browser provider's settings
3. **Set host and port** - Press Enter to accept defaults (`localhost:36912` for GoLogin, `localhost:3001` for Dolphin Anty). These are the default ports used by the desktop apps, you don't need to change them
4. **Set your timezone** - e.g., `America/New_York`, `Europe/Berlin`, `Asia/Tokyo`
5. **Google Drive credentials** (optional) - You can paste your OAuth JSON or provide a file path. Skip this if you don't plan to use Google Drive for posting
6. **Add your accounts** - For each account, you'll provide:
   - Account name (e.g., `MyMainAccount`)
   - Twitter username (e.g., `@myhandle`)
   - Browser profile ID (from your GoLogin or Dolphin Anty app)
   - Google Drive folder ID (optional - press Enter to skip)
   - Posting schedule (comma-separated times like `09:00, 15:00, 20:00`)
   - Retweet settings (daily limit, target profiles, time windows)

The wizard creates two config files:
- `config/settings.yaml` - Global settings
- `config/accounts.yaml` - Account configurations

After the wizard finishes, verify your setup:

```bash
python main.py --test
```

This tests the connection to your browser provider API and shows if everything is configured correctly.

---

## Configuration

There are three ways to configure BunnyTweets. Choose whichever you prefer:

### Option A: Web Dashboard (Recommended)

The easiest way to manage everything. Launch the dashboard and configure through your browser:

```bash
python main.py --web
```

Then open **http://localhost:8080** in your browser. You can edit all settings, manage accounts, view logs, and control the automation engine - all from the web UI. See the [Web Dashboard Guide](#web-dashboard-guide) section for details.

### Option B: Setup Wizard (CLI)

For first-time setup or if you prefer the terminal:

```bash
# Full setup (creates both config files from scratch)
python main.py --setup

# Add a new account to an existing configuration
python main.py --add-account
```

### Option C: Manual YAML Editing

For advanced users who prefer editing config files directly:

```bash
# Copy example files
cp config/settings.yaml.example config/settings.yaml
cp config/accounts.yaml.example config/accounts.yaml

# Edit with your favorite editor
nano config/settings.yaml
nano config/accounts.yaml
```

See the [Configuration Reference](#configuration-reference) section for all available options.

---

## Anti-Detect Browser Setup

BunnyTweets uses anti-detect browsers to run each Twitter account in an isolated browser profile with a unique fingerprint. This prevents Twitter from linking your accounts together.

### GoLogin Setup (Default)

GoLogin is the default browser provider. Here's how to set it up:

**Step 1: Install GoLogin**
1. Go to [gologin.com](https://gologin.com/) and create an account
2. Download and install the GoLogin desktop application
3. Launch GoLogin and sign in

**Step 2: Get Your API Token**
1. In the GoLogin app, go to **Settings** (gear icon)
2. Navigate to the **API** section
3. Copy your API token - you'll need this during setup

**Step 3: Create Browser Profiles**
1. In GoLogin, click **"Create Profile"** (or **"+ New Profile"**)
2. Give it a name (e.g., the Twitter account username)
3. Configure the profile settings as desired (OS, browser version, etc.)
4. Click **"Create"**
5. Repeat for each Twitter account

**Step 4: Log In to Twitter**
1. In GoLogin, click **"Run"** next to the profile to launch the browser
2. Navigate to [twitter.com](https://twitter.com) (or [x.com](https://x.com))
3. Log in to the Twitter account for this profile
4. Close the browser - GoLogin saves the session automatically
5. Repeat for each profile

**Step 5: Get Profile IDs**
1. You can find your profile IDs in the GoLogin app URL bar when viewing a profile
2. Or via the API:
   ```bash
   curl -H "Authorization: Bearer YOUR_API_TOKEN" https://api.gologin.com/browser/v2
   ```
3. Note down each profile ID - you'll need them when adding accounts

**Step 6: Keep GoLogin Running**
- The GoLogin desktop app must be running whenever BunnyTweets is active
- GoLogin exposes a local API on `http://localhost:36912` that BunnyTweets uses to start/stop profiles
- You do NOT need to keep the browser windows open - BunnyTweets starts them automatically

### Dolphin Anty Setup (Alternative)

If you prefer Dolphin Anty:

**Step 1: Install Dolphin Anty**
1. Go to [dolphin-anty.com](https://dolphin-anty.com/) and create an account
2. Download and install the desktop application
3. Launch Dolphin Anty and sign in

**Step 2: Get Your API Token**
1. In Dolphin Anty, go to **Settings**
2. Find and copy your API token

**Step 3: Create Browser Profiles**
1. Click **"Create Profile"**
2. Configure the profile as needed
3. Repeat for each Twitter account

**Step 4: Log In to Twitter**
1. Launch each profile, navigate to Twitter, and log in
2. Close the browser - the session is saved

**Step 5: Get Profile IDs**
```bash
curl http://localhost:3001/v1.0/browser_profiles | python3 -m json.tool
```

**Step 6: Keep Dolphin Anty Running**
- The app must be running on `http://localhost:3001` while BunnyTweets operates

**Switching Between Providers**

You can switch your browser provider at any time:
- **Web Dashboard**: Go to Settings > General > Browser Provider
- **CLI**: Edit `config/settings.yaml` and change `browser_provider` to `"gologin"` or `"dolphin_anty"`
- **Environment Variable**: Set `BROWSER_PROVIDER=dolphin_anty`

---

## Google Drive Setup (Optional)

Google Drive integration lets you post media (images/videos) to Twitter by simply uploading files to a Google Drive folder. This step is **completely optional** - skip it if you don't need automated media posting.

### Step 1: Create a Google Cloud Project

1. Go to [console.cloud.google.com](https://console.cloud.google.com/)
2. Click **"Select a project"** at the top > **"New Project"**
3. Enter a name (e.g., "BunnyTweets") and click **"Create"**

### Step 2: Enable the Google Drive API

1. In your project, go to **APIs & Services > Library**
2. Search for **"Google Drive API"**
3. Click on it, then click **"Enable"**

### Step 3: Create a Service Account

1. Go to **APIs & Services > Credentials**
2. Click **"+ Create Credentials"** at the top
3. Select **"Service Account"** (NOT "OAuth Client ID")
4. Enter a name (e.g., "bunnytweets-drive"), click **"Create and Continue"**
5. Skip the optional permission steps, click **"Done"**
6. Click on the newly created service account in the list
7. Go to the **"Keys"** tab
8. Click **"Add Key" > "Create new key" > "JSON"**
9. A `.json` file will be downloaded - these are your credentials

### Step 4: Save the Credentials

There are three ways to save your Google credentials:

**Option A: During Setup Wizard**
When running `python main.py --setup`, the wizard will ask if you want to set up Google Drive. You can either paste the JSON content or provide the file path.

**Option B: Copy Manually**
```bash
mkdir -p config/credentials
cp ~/Downloads/your-credentials-file.json config/credentials/google_credentials.json
```

**Option C: Via Web Dashboard**
Go to Settings > Google Drive > Credentials File and set the path.

### Step 5: Share Your Drive Folders

1. Open the downloaded JSON file and find the `"client_email"` field. It looks like:
   ```
   bunnytweets-drive@your-project.iam.gserviceaccount.com
   ```
2. Go to Google Drive in your browser
3. For each folder you want BunnyTweets to monitor:
   - Right-click the folder > **"Share"**
   - Add the `client_email` address as a **Viewer**
   - Click **"Send"**

### Step 6: Get Your Folder IDs

1. Open the folder in Google Drive
2. The URL looks like: `https://drive.google.com/drive/folders/1ABCdefGHIjklMNO`
3. The part after `/folders/` is your `folder_id`
4. You'll enter this when adding accounts (in the wizard, web dashboard, or accounts.yaml)

### How Media Files Are Processed

When BunnyTweets checks a Drive folder, it groups files by their base name (without extension):

| Files in Drive | Result |
|---|---|
| `post1.jpg` | Tweet with image, no text |
| `post1.jpg` + `post1.txt` | Tweet with image AND the text from the .txt file |
| `video.mp4` | Tweet with video, no text |
| `video.mp4` + `video.txt` | Tweet with video AND text |
| `standalone.txt` | Skipped (text-only files are not posted) |

Supported file types: `jpg`, `png`, `gif`, `webp`, `mp4`, `mov`, `txt`

---

## Usage

### Starting the Web Dashboard

```bash
python main.py --web
```

This starts the BunnyTweets web dashboard at **http://localhost:8080**. From here you can:
- View live status of all accounts
- Edit global settings and account configurations
- Start/stop the automation engine
- Manually trigger posts and retweets
- View and search through log files in real time

To use a different port:
```bash
python main.py --web --port 8080
```

### Starting the Desktop App

For a native desktop experience with a system tray icon:

```bash
python main.py --desktop
```

This launches the web dashboard **and** a system tray icon. Your default browser opens automatically to `http://localhost:8080`. The tray icon provides quick access to:

- **Open Dashboard** - Opens the web UI in your browser (also triggered by double-clicking the icon)
- **Start / Stop Engine** - Control the automation engine
- **Quit** - Gracefully shuts everything down

You can also run the desktop launcher directly:

```bash
python desktop.py                  # System tray + auto-open browser
python desktop.py --headless       # No tray (useful for CI / Docker)
python desktop.py --no-browser     # Tray, but don't auto-open browser
python desktop.py --port 9000      # Use a different port
```

See [Desktop App (Build from Source)](#desktop-app-build-from-source) to package it as a standalone `.app` (macOS) or `.exe` (Windows).

### Starting the Automation (CLI)

If you prefer running without the web dashboard:

```bash
python main.py
```

This starts the automation engine directly in the terminal. It will:
1. Load your configuration from `config/settings.yaml` and `config/accounts.yaml`
2. Authenticate with your browser provider (GoLogin or Dolphin Anty)
3. Start a browser profile for each enabled account
4. Verify that each account is logged in to Twitter
5. Schedule all posting and retweet jobs
6. Run continuously until you press `Ctrl+C`

### All CLI Commands

| Command | Description |
|---------|-------------|
| `python main.py` | Start the automation engine (all enabled accounts) |
| `python main.py --web` | Launch the web dashboard (http://localhost:8080) |
| `python main.py --desktop` | Launch the desktop app (dashboard + system tray) |
| `python main.py --web --port 8080` | Launch the dashboard on a custom port |
| `python main.py --setup` | Run the interactive first-time setup wizard |
| `python main.py --add-account` | Add a new account to your existing config |
| `python main.py --status` | Show current status of all accounts |
| `python main.py --test` | Test connections to browser provider, Drive, and database |

---

## Web Dashboard Guide

The web dashboard provides a complete browser-based interface for managing BunnyTweets.

### Dashboard Page (`/`)

The main overview page shows:

- **Engine Status** - Whether the automation engine is running, stopped, starting, or stopping. A large Start/Stop button lets you control the engine
- **Stats Bar** - Total accounts, active accounts, scheduled jobs count, and queued tasks
- **Account Cards** - Each account shows:
  - Name and Twitter username
  - Status badge (green = idle, blue = running, yellow = paused, red = error)
  - Last post timestamp
  - Last retweet timestamp
  - Retweet progress bar (e.g., 2/3 today)
  - Error message (if any)
  - **"Post Now"** button - Manually trigger a posting cycle for this account
  - **"Retweet Now"** button - Manually trigger a retweet cycle for this account
- **Scheduled Jobs Table** - Lists all scheduled jobs with their next run times

The dashboard polls for updates every 5 seconds, so status changes appear automatically without refreshing the page.

### Settings Page (`/settings`)

Edit all global settings through organized form sections:

| Section | What You Can Configure |
|---------|----------------------|
| **General** | Browser provider (GoLogin/Dolphin Anty), timezone |
| **GoLogin** | Host, port, API token |
| **Dolphin Anty** | Host, port, API token |
| **Google Drive** | Credentials file path, download directory |
| **Browser** | Implicit wait, page load timeout, headless mode |
| **Delays** | Action delay min/max, typing speed min/max, page load delay min/max |
| **Error Handling** | Max retries, retry backoff, pause duration |
| **Logging** | Log level, retention days, per-account logs |
| **Discord** | Webhook URL, thread ID, enable/disable notifications |
| **Database** | Database file path |

API tokens are masked in the form. Leave the token field empty to keep your current token - it will only update if you type a new value.

If the engine is running when you save settings, a banner reminds you to restart the engine for changes to take effect.

### Accounts Page (`/accounts`)

Manage all your Twitter accounts:

- **Account Table** - Lists all accounts with their name, username, profile ID, status, enabled/disabled toggle, posting status, and retweet settings
- **Toggle Switch** - Enable/disable any account instantly (saves immediately via AJAX)
- **Edit Button** - Opens the account form pre-filled with current settings
- **Delete Button** - Removes the account (with confirmation dialog)
- **"Add Account" Button** - Opens a blank account form

**The Account Form includes:**

| Section | Fields |
|---------|--------|
| **Basic Info** | Account name (read-only after creation), enabled checkbox |
| **Twitter** | Username, browser profile ID |
| **Google Drive** | Folder ID (optional), check interval in minutes |
| **Posting** | Enabled checkbox, schedule times (comma-separated HH:MM), default text |
| **Retweeting** | Enabled checkbox, daily limit, strategy (latest/random) |
| **Target Profiles** | Dynamic rows - add/remove target usernames with priorities |
| **Time Windows** | Dynamic rows - add/remove start/end time pairs |
| **Human Simulation** | Enabled checkbox, session duration min/max, daily sessions limit, daily likes limit, time windows |
| **Reply to Replies** | Enabled checkbox, daily limit, time windows |
| **CTA Texts** | Add/remove call-to-action self-comment texts (saved via AJAX) |
| **Reply Templates** | Add/remove per-account reply templates (saved via AJAX) |

### Generator Page (`/generator`)

Manage reusable content for automated posting:

- **Title Categories** - Create and delete categories (e.g., "Motivational", "Product", "Engagement"). The "Global" category cannot be deleted
- **Titles** - Add tweet text to categories. When posting, BunnyTweets picks a random title from the relevant category
- **Global Target Accounts** - Shared pool of target usernames for retweeting. These can be used across all accounts in addition to per-account targets

### Analytics Page (`/analytics`)

Visual dashboard with charts powered by Chart.js:

- **Daily Activity** - Bar chart of posts, retweets, replies, and simulations over time
- **Success / Failure Rates** - Breakdown of task outcomes
- **Per-Account Stats** - Activity distribution across your accounts
- Data is fetched from `/api/analytics` and rendered client-side

### Logs Page (`/logs`)

A real-time log viewer with a terminal-like appearance:

- **File Selector** - Dropdown to choose between log files, grouped into "Main Logs" (automation_YYYY-MM-DD.log) and "Account Logs" (AccountName_YYYY-MM-DD.log)
- **Search** - Type to highlight matching text in the log output
- **Auto-Scroll** - Toggle to automatically scroll to the bottom as new logs appear
- **Live Tailing** - New log lines appear every 2 seconds without page refresh

---

## How It Works

### Posting Flow

1. At the scheduled posting time (or at each Drive sync interval), BunnyTweets checks the Google Drive folder for the account
2. New files (not yet processed) are downloaded to a local temp directory
3. Files with the same base name are grouped together:
   - `photo.jpg` + `photo.txt` becomes one tweet with image and text
   - `video.mp4` alone becomes a video tweet with no text
4. Media files are validated (size limits, supported formats)
5. The tweet is composed via Selenium - text is typed character-by-character with human-like delays
6. Media files are uploaded through Twitter's file input
7. The post button is clicked
8. The file is marked as "processed" in the database so it won't be posted again
9. Downloaded files are cleaned up from the temp directory

### Retweet Flow

1. The system checks configured time windows to see if retweeting is currently allowed
2. It checks the daily retweet counter for the account against the configured limit
3. It visits each target profile (ordered by priority) on Twitter
4. For each target, it scrapes the latest tweets and their URLs
5. Each tweet is checked against the database to skip already-retweeted ones
6. When an eligible tweet is found, the retweet button is clicked
7. The retweet is recorded in the database (for duplicate protection)
8. The daily counter is incremented
9. Maximum retweets per day is configurable per account (default: 3)

### Scheduling

BunnyTweets uses APScheduler for all timing:

- **Posting Jobs** - Cron-based jobs that fire at the exact times you configure (e.g., 09:00, 15:00, 20:00)
- **Drive Sync Jobs** - Interval-based jobs that check for new files every N minutes
- **Retweet Jobs** - Distributed randomly across your time windows. If you set a daily limit of 3 and have 3 time windows, each window gets approximately 1 retweet at a random time within that window
- **Simulation Jobs** - Human-like browsing sessions distributed across configured time windows
- **Reply Jobs** - Auto-reply tasks distributed across their own time windows
- **CTA Check** - Every 5 minutes, checks if any account has a pending CTA self-comment due (posted >55 min ago)
- **Health Checks** - Every 5 minutes, verifies each browser is still alive and responsive. Auto-recovery kicks in if a browser is unresponsive

All jobs are managed by a thread-safe queue that ensures only one task runs per account at a time (preventing Selenium race conditions).

---

## Configuration Reference

### settings.yaml

```yaml
# Default timezone for all schedules (IANA timezone name)
timezone: "America/New_York"

# Browser provider: "gologin" (default) or "dolphin_anty"
browser_provider: "gologin"

# GoLogin Local API connection (desktop app must be running)
gologin:
  host: "localhost"        # GoLogin desktop runs locally
  port: 36912              # GoLogin default port (don't change unless you customized it)
  api_token: ""            # Your API token from GoLogin dashboard > Settings > API

# Dolphin Anty Local API connection (alternative provider)
dolphin_anty:
  host: "localhost"        # Dolphin Anty runs locally
  port: 3001               # Dolphin Anty default port
  api_token: ""            # Your API token from Dolphin Anty settings

# Google Drive API settings (optional)
google_drive:
  credentials_file: "config/credentials/google_credentials.json"
  download_dir: "data/downloads"

# Selenium / Browser settings
browser:
  implicit_wait: 10        # How long Selenium waits for elements (seconds)
  page_load_timeout: 30    # Max time for a page to load (seconds)
  headless: false          # Set to true on VPS without display

# Anti-detection delays (seconds) - randomized between min and max
delays:
  action_min: 2.0          # Minimum wait between actions (clicking, etc.)
  action_max: 5.0          # Maximum wait between actions
  typing_min: 0.05         # Minimum delay per keystroke
  typing_max: 0.15         # Maximum delay per keystroke
  page_load_min: 3.0       # Minimum wait after navigation
  page_load_max: 7.0       # Maximum wait after navigation

# Error handling
error_handling:
  max_retries: 3           # Retries before pausing an account
  retry_backoff: 5         # Seconds between retries (multiplied each time)
  pause_duration_minutes: 60  # How long to pause a failed account

# Logging
logging:
  level: "INFO"            # DEBUG, INFO, WARNING, ERROR, CRITICAL
  retention_days: 30       # How long to keep log files
  per_account_logs: true   # Create separate log files per account

# Discord webhook notifications (troubleshooting alerts)
discord:
  webhook_url: ""          # Webhook URL for your Discord channel
  thread_id: ""            # Thread ID if posting to a specific thread (optional)
  enabled: false           # Enable/disable notifications

# Database
database:
  path: "data/database/automation.db"  # SQLite database location
```

### accounts.yaml

```yaml
accounts:
  - name: "MyMainAccount"    # Unique name for this account
    enabled: true             # Set to false to skip this account

    twitter:
      username: "@myhandle"   # Your Twitter/X username
      profile_id: "abc123"   # Browser profile ID from GoLogin or Dolphin Anty

    google_drive:             # Optional - remove this section to skip Drive integration
      folder_id: "1ABCdefGHIjklMNO"   # Google Drive folder ID
      check_interval_minutes: 15       # How often to check for new files
      file_types: ["jpg", "png", "gif", "webp", "mp4", "mov", "txt"]

    posting:
      enabled: true
      schedule:
        - time: "09:00"      # Posts at 9 AM in your configured timezone
        - time: "15:00"      # Posts at 3 PM
        - time: "20:00"      # Posts at 8 PM
      default_text: ""       # Fallback text if no .txt file accompanies the media

    retweeting:
      enabled: true
      daily_limit: 3         # Max retweets per day for this account
      target_profiles:       # Whose tweets to retweet
        - username: "@target1"
          priority: 1        # Lower number = checked first
        - username: "@target2"
          priority: 2
      time_windows:          # When retweeting is allowed
        - start: "09:00"
          end: "12:00"
        - start: "14:00"
          end: "17:00"
        - start: "19:00"
          end: "22:00"
      strategy: "latest"     # "latest" = retweet newest tweet, "random" = random selection

    # Human-like browsing simulation (anti-detection)
    human_simulation:
      enabled: true
      session_duration_min: 30   # Session length range in minutes
      session_duration_max: 60
      daily_sessions_limit: 2    # Max simulation sessions per day
      daily_likes_limit: 30      # Max likes per day across all sessions
      time_windows:              # When simulation can run
        - start: "08:00"
          end: "12:00"
        - start: "18:00"
          end: "23:00"
```

---

## Environment Variables

All settings can be overridden with environment variables (useful for Docker or CI/CD):

| Variable | Description | Default |
|----------|-------------|---------|
| `BROWSER_PROVIDER` | Browser provider to use | `gologin` |
| `GOLOGIN_TOKEN` | GoLogin API token | (from settings.yaml) |
| `GOLOGIN_HOST` | GoLogin API host | `localhost` |
| `GOLOGIN_PORT` | GoLogin API port | `36912` |
| `DOLPHIN_ANTY_TOKEN` | Dolphin Anty API token | (from settings.yaml) |
| `DOLPHIN_ANTY_HOST` | Dolphin Anty API host | `localhost` |
| `DOLPHIN_ANTY_PORT` | Dolphin Anty API port | `3001` |
| `GOOGLE_CREDENTIALS_FILE` | Path to Google credentials JSON | `config/credentials/google_credentials.json` |
| `TZ` | System timezone | `America/New_York` |

Example `.env` file:
```bash
BROWSER_PROVIDER=gologin
GOLOGIN_TOKEN=your_token_here
GOOGLE_CREDENTIALS_FILE=config/credentials/google_credentials.json
TZ=America/New_York
```

---

## Desktop App (Build from Source)

You can package BunnyTweets as a standalone desktop application — a `.app` bundle on macOS or a `.exe` on Windows. No Python installation required on the target machine.

### Prerequisites

```bash
pip install pyinstaller>=6.0 pystray>=0.19.5
```

### Building

**macOS / Linux:**
```bash
./scripts/build.sh
```

**Windows:**
```bat
scripts\build.bat
```

### Output

| Platform | Output | Install |
|----------|--------|---------|
| macOS | `dist/BunnyTweets.app` | Drag to `/Applications` |
| Windows | `dist/BunnyTweets/BunnyTweets.exe` | Run directly or wrap with [Inno Setup](https://jrsoftware.org/isinfo.php) |

### Creating a macOS .dmg

```bash
hdiutil create -volname BunnyTweets -srcfolder dist/BunnyTweets.app -ov -format UDZO dist/BunnyTweets.dmg
```

### Automated Builds (GitHub Actions)

A CI workflow (`.github/workflows/build-desktop.yml`) automatically builds both macOS and Windows artifacts:

- **On version tags** (`git tag v1.0.0 && git push --tags`) — builds both platforms and creates a GitHub Release with the `.dmg` and `.zip` attached
- **Manual trigger** — run the workflow from the Actions tab at any time

### Clean Up

```bash
./scripts/build.sh clean    # macOS / Linux
scripts\build.bat clean     # Windows
```

---

## Docker Deployment

### Quick Start with Docker

```bash
# Build and start
cd /opt/bunnytweets
docker compose up -d

# View logs
docker compose logs -f

# Stop
docker compose down
```

### Docker Compose Configuration

The `docker-compose.yml` uses host networking so the container can reach:
- GoLogin/Dolphin Anty on the host machine (localhost:36912 or localhost:3001)
- The browser debug ports opened by the anti-detect browser

```yaml
version: "3.8"
services:
  bunnytweets:
    build: .
    volumes:
      - ./config:/app/config    # Config files persist on host
      - ./data:/app/data        # Database, logs, downloads persist
    environment:
      - TZ=America/New_York
      - GOLOGIN_HOST=host.docker.internal  # or localhost with host networking
      - GOLOGIN_PORT=36912
    network_mode: "host"
    restart: unless-stopped
```

### Running the Web Dashboard in Docker

To run the web dashboard instead of the CLI automation:

```yaml
# In docker-compose.yml, change the command:
    command: ["python", "main.py", "--web", "--port", "8080"]
    ports:
      - "8080:8080"
```

### VPS Setup Script

For Ubuntu/Debian servers, there's a convenience script:

```bash
chmod +x setup_vps.sh
sudo ./setup_vps.sh
```

This installs Python, Chrome, and all system dependencies needed for Selenium.

---

## Project Structure

```
bunnytweets/
├── main.py                          # Entry point (CLI args: --web, --desktop, --setup, etc.)
├── desktop.py                       # Desktop launcher (system tray + Flask)
├── bunnytweets.spec                 # PyInstaller build spec (.app / .exe)
├── requirements.txt                 # Python dependencies
├── Dockerfile                       # Docker build configuration
├── docker-compose.yml               # Docker Compose deployment
├── setup_vps.sh                     # VPS setup script (Ubuntu/Debian)
├── scripts/
│   ├── build.sh                     # macOS / Linux build script
│   └── build.bat                    # Windows build script
├── .github/
│   └── workflows/
│       └── build-desktop.yml        # CI: cross-platform desktop builds + releases
├── .env.example                     # Environment variables template
├── config/
│   ├── settings.yaml.example        # Global settings template
│   ├── accounts.yaml.example        # Account config template
│   ├── settings.yaml                # Your settings (gitignored)
│   ├── accounts.yaml                # Your accounts (gitignored)
│   └── credentials/                 # Google Drive credentials (gitignored)
│       └── google_credentials.json
├── src/
│   ├── core/
│   │   ├── config_loader.py         # Loads and merges YAML config + env vars
│   │   ├── database.py              # SQLAlchemy models and query methods
│   │   ├── logger.py                # Loguru logging setup (main + per-account)
│   │   ├── notifier.py              # Discord webhook notifications
│   │   └── setup_wizard.py          # Interactive CLI setup wizard
│   ├── web/                         # Flask web dashboard
│   │   ├── __init__.py              # App factory (create_app)
│   │   ├── state.py                 # AppState: bridge between Flask and automation engine
│   │   ├── routes/
│   │   │   ├── dashboard.py         # GET / — main overview
│   │   │   ├── settings.py          # GET/POST /settings — config editor
│   │   │   ├── accounts.py          # CRUD /accounts — account management
│   │   │   ├── generator.py         # /generator — title categories + global targets
│   │   │   ├── analytics.py         # /analytics — visual charts dashboard
│   │   │   ├── logs.py              # GET /logs — log viewer + tail API
│   │   │   ├── actions.py           # POST /api/actions/* — engine control + manual triggers
│   │   │   └── api.py               # GET /api/* — JSON status + analytics endpoints
│   │   ├── templates/               # Jinja2 HTML templates (Bootstrap 5 dark theme)
│   │   │   ├── base.html            # Layout: navbar, engine indicator, toasts
│   │   │   ├── dashboard.html       # Account cards, engine controls, jobs table
│   │   │   ├── settings.html        # Settings form (accordion sections)
│   │   │   ├── accounts.html        # Account list with toggles
│   │   │   ├── account_form.html    # Add/edit account form (dynamic rows)
│   │   │   ├── generator.html       # Title categories and global targets
│   │   │   ├── analytics.html       # Analytics charts (Chart.js)
│   │   │   └── logs.html            # Log viewer (terminal-style)
│   │   └── static/
│   │       ├── css/style.css        # Custom dark theme styles
│   │       └── js/
│   │           ├── dashboard.js     # Status polling (5s), engine/trigger actions
│   │           ├── accounts.js      # Toggle, delete, dynamic form rows
│   │           ├── generator.js     # Category/title/target CRUD
│   │           ├── analytics.js     # Chart.js rendering + data fetching
│   │           └── logs.js          # Log tailing (2s), search highlighting
│   ├── gologin/
│   │   └── api_client.py            # GoLogin Local REST API client (port 36912)
│   ├── dolphin_anty/
│   │   ├── api_client.py            # Dolphin Anty Local API client (port 3001)
│   │   ├── chromedriver_resolver.py  # ChromeDriver version resolution
│   │   └── profile_manager.py       # Provider-agnostic Selenium profile manager
│   ├── google_drive/
│   │   ├── drive_client.py          # Google Drive API client
│   │   ├── file_monitor.py          # Watches Drive folders for new files
│   │   └── media_handler.py         # Groups and validates media files
│   ├── twitter/
│   │   ├── automation.py            # Low-level Selenium operations (type, click, navigate)
│   │   ├── poster.py                # High-level posting orchestration (Drive -> Tweet)
│   │   ├── retweeter.py             # High-level retweet orchestration
│   │   ├── replier.py               # Auto-reply to tweets from target profiles
│   │   └── human_simulator.py       # Human-like browsing simulation sessions
│   └── scheduler/
│       ├── job_manager.py           # APScheduler wrapper (cron + interval jobs)
│       └── queue_handler.py         # Thread-safe task queue (1 task per account)
├── data/
│   ├── database/
│   │   └── automation.db            # SQLite database (auto-created)
│   ├── downloads/                   # Temporary media downloads (auto-cleaned)
│   └── logs/                        # Log files (daily rotation, 30-day retention)
│       ├── automation_YYYY-MM-DD.log  # Main log
│       └── AccountName_YYYY-MM-DD.log # Per-account logs
└── tests/
    ├── test_config_loader.py        # Config loading and validation tests
    ├── test_database.py             # Database model and query tests
    ├── test_media_handler.py        # Media file grouping and validation tests
    └── test_queue_handler.py        # Task queue concurrency tests
```

---

## Troubleshooting

### Browser Won't Start

**Check if your browser provider is running:**
- GoLogin: The desktop app must be open. Test with:
  ```bash
  curl http://localhost:36912
  ```
- Dolphin Anty: The desktop app must be open. Test with:
  ```bash
  curl http://localhost:3001/v1.0/browser_profiles
  ```

**Check your profile ID:**
- Make sure the `profile_id` in your account config matches an actual profile in your browser app
- GoLogin profile IDs look like: `64a3b2c1d0e9f8a7b6c5d4e3`
- Dolphin Anty profile IDs are numeric: `12345678`

**Check your API token:**
- Run `python main.py --test` to verify authentication
- GoLogin tokens come from: Dashboard > Settings > API
- Dolphin Anty tokens come from: Settings page in the app

### "Not Logged In" Error

This means the browser profile opened, but Twitter doesn't have an active session:

1. Open the profile manually in your browser app (GoLogin or Dolphin Anty)
2. Navigate to [twitter.com](https://twitter.com) or [x.com](https://x.com)
3. Log in to your Twitter account
4. Close the browser - the session cookies are saved in the profile
5. Restart BunnyTweets

### Google Drive Files Not Being Posted

1. **Check credentials**: Is `config/credentials/google_credentials.json` present and valid?
2. **Check folder sharing**: Did you share the Drive folder with the service account's `client_email`?
3. **Check folder ID**: Is the `folder_id` in your account config correct?
4. **Check file types**: Are your files in the supported formats? (jpg, png, gif, webp, mp4, mov, txt)
5. **Check the logs**: Run `python main.py --web`, go to the Logs page, and look for Drive-related errors

### Rate Limits

Twitter has rate limits:
- Maximum 300 tweets per 3 hours
- Maximum 2,400 tweets per day
- Retweets count as tweets
- If you hit a rate limit, BunnyTweets will log the error and automatically pause the account

### Web Dashboard Not Loading

1. Make sure Flask is installed: `pip install flask==3.0.0`
2. Check if port 8080 is available: `lsof -i :8080`
3. Try a different port: `python main.py --web --port 9000`
4. Check the terminal output for error messages

### View Logs

**Via Web Dashboard:**
```bash
python main.py --web
# Then go to http://localhost:8080/logs
```

**Via Terminal:**
```bash
# Main log (today)
tail -f data/logs/automation_$(date +%Y-%m-%d).log

# Specific account log
tail -f data/logs/MyMainAccount_$(date +%Y-%m-%d).log
```

### Reset Everything

If you want to start fresh:
```bash
# Remove config (you'll need to re-run --setup)
rm config/settings.yaml config/accounts.yaml

# Remove database (clears all state - processed files, retweet history, etc.)
rm data/database/automation.db

# Remove logs
rm data/logs/*.log

# Re-run setup
python main.py --setup
```
