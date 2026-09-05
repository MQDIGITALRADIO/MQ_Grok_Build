# MQ Radio Automation — Milestone 1

Modular broadcast automation for **MQ DIGITAL RADIO**.  
One app UX; playout engines underneath so **UI crash ≠ station dead air**.

Control surface (HOME / On-Air prototype) is separate from **MQ Engine** (background playout service).

## Architecture

```mermaid
flowchart TB
  subgraph UI["Control Surface (HOME / STUDIO)"]
    OA[On-Air / Living Log Web]
    CLI[CLI]
  end

  subgraph Core["MQ Application Core"]
    LIB[library]
    MD[music_director]
    SCH[scheduler]
    LL[living_log]
    VT[voice_tracker stub]
    PROD[production stub]
    SM[stream_manager stub]
    REM[remote stub]
  end

  subgraph Engine["MQ Engine adapters"]
    MOCK[MockEngine]
    LS[LiquidsoapEngine stub]
  end

  DB[(SQLite)]

  OA --> LL
  OA --> MOCK
  CLI --> LIB
  CLI --> MD
  CLI --> SCH
  CLI --> MOCK
  SCH --> DB
  LIB --> DB
  LL --> DB
  MOCK --> DB
  LS -.-> DB
```

**HOME** = Master Control 24/7 · **STUDIO** = live/remote contribution only (M2+).

Deterministic **scheduler** commits the **Living Log** ahead of airtime. AI never picks the next song live.

Broadcast language: clocks, categories, Living Log, ETMs — not Spotify language.

## Quick start

```bash
cd mq-radio-automation

# optional venv
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"     # or: pip install -r requirements.txt && pip install -e .

# Initialise DB, seed demo library + GENERAL clock + MQ DIGITAL rules
python -m mq_radio init-db
python -m mq_radio seed-demo

# Generate today's 24h Living Log (scored vs separation — not random)
python -m mq_radio generate-log
python -m mq_radio show-log --limit 40

# Step MockEngine through the committed log
python -m mq_radio engine-step
python -m mq_radio engine-step --action play

# On-Air web prototype
python -m mq_radio serve --host 127.0.0.1 --port 8080
# open http://127.0.0.1:8080/
```

### CLI commands

| Command | Purpose |
|---------|---------|
| `init-db` | Create/migrate SQLite schema |
| `scan [--path DIR]` | Index audio into library |
| `seed-demo` | Categories, GENERAL clock, MQ DIGITAL rules, synthetic WAV fixtures |
| `generate-log [--date YYYY-MM-DD] [--force]` | Build 24h Living Log; preserves MANUAL unless `--force` |
| `show-log [--date] [--limit N]` | Print log |
| `engine-step [--action step\|play\|stop\|skip]` | MockEngine advance |
| `serve [--port 8080]` | On-Air prototype |

## M1 vs roadmap

| Area | M1 (this zip) | Later |
|------|---------------|--------|
| Library / scanner | WAV + sidecar JSON, demo fixtures | Full tagging, APRA/PPCA workflows |
| Scheduler | Clock expansion, separation scoring, MANUAL preserve | Multi-clock grids, fills, hard ETMs |
| Engine | MockEngine + Liquidsoap stub | Real Liquidsoap / stream chain |
| UI | On-Air Living Log prototype | Full HOME + STUDIO surfaces |
| Voice / production / remote | Package stubs | Voice tracker, production cart, remotes |
| Stream manager | Stub | Encoders, mounts, failover |

## Package layout

```
mq_radio/
  library/          # scan & ingest
  music_director/   # seed, rules helpers
  scheduler/        # clock expansion + scored log generate
  living_log/       # query Living Log
  voice_tracker/    # stub
  production/       # stub
  stream_manager/   # stub
  remote/           # stub
  engine/           # MockEngine + LiquidsoapEngine stub
  db/               # SQLite + migrations
  web/              # On-Air prototype
  cli/              # mq-radio commands
```

## Event types & timing

**Events:** MUSIC, SWEEPER, ID, PROMO, VOICE_TRACK, BED, SHOW, LIVE, COMMAND, ETM, BREAK, FILLER  

**Chain:** AUTO · MIX · CUT · MANUAL · HOLD  

**Timing:** FLOAT · SOFT · HARD · RESET · HIT · TIME_WINDOW

## Tests

```bash
pip install pytest
pytest -q
```

## Data

Default DB: `data/mq_radio.db`  
Demo audio: `fixtures/demo_audio/` (synthetic short WAVs + JSON metadata)

## Notes

- Playout is behind an adapter; the UI talks to Living Log / MockEngine only.
- Scheduler is deterministic given library + rules + clock — not live AI selection.
- Inspired by Zetta/NETIA *workflows*; not a clone of proprietary UI/IP.

## Mac install (DMG)


### One-time: enable the DMG builder (needs workflow file on GitHub)


The GitHub OAuth token used to push code does **not** include the `workflow` scope, so the Actions file lives in-repo as a template:


`packaging/ci/macos-dmg.yml`


**Matt — do this once in the browser (signed in as MQDIGITALRADIO):**


1. Open https://github.com/MQDIGITALRADIO/MQ_Grok_Build/new/main?filename=.github/workflows/macos-dmg.yml

2. Copy the full contents of `packaging/ci/macos-dmg.yml` from the repo and paste into the editor.

3. Commit directly to `main` (message: `Add macOS DMG workflow`).

4. Open Actions → **macOS DMG** → the run starts automatically (or click **Run workflow**).

5. When green, open the run → Artifacts → download **MQ-Radio-macOS-DMG**.


Optional later: `gh auth refresh -s workflow` so future pushes can update workflows from git.


### Install the DMG on your Mac

1. Open the GitHub Actions run for **macOS DMG** on the `main` branch:
   https://github.com/MQDIGITALRADIO/MQ_Grok_Build/actions/workflows/macos-dmg.yml
2. Download the artifact **MQ-Radio-macOS-DMG** (a `.dmg` file).
3. Open the DMG and drag **MQ Radio** into **Applications**.
4. First launch (unsigned build): Finder → Applications → **right-click MQ Radio → Open** → confirm Open.
   Apple Gatekeeper blocks unsigned apps until you do this once. Apple Developer signing comes later.
5. MQ Radio opens the On-Air UI. First run auto-creates a demo library and Living Log.

Station data: `~/Library/Application Support/MQ Radio/` (Electron userData).

### What the Mac app does

- Double-click app window (no Terminal)
- Bundled engine serves On-Air at `http://127.0.0.1:8080`
- Quitting the app stops the engine

Rebuilds run automatically on push to `main` via `.github/workflows/macos-dmg.yml`.

