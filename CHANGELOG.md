# Changelog — MQ Radio Automation

Lean build log for Matt. SHAs are on `main` (`MQDIGITALRADIO/MQ_Grok_Build`).

## Overnight package grind 2026-09-06 (substance + P1 desk depth)

| SHA | Theme |
|-----|--------|
| *(this commit)* | Package bulk: ffmpeg/ffprobe + demo beds + Master Control; P1 hotkey/pulse/talk-up harden |

**Package (≥500MB–1GB real substance):** `packaging/scripts/stage_mac_resources.sh` downloads darwin static **ffmpeg/ffprobe**, generates minutes of real PCM **demo beds**, stages **Master Control** Liquidsoap handoff pack. electron-builder `extraResources` + CI soft size ≥400MB with ZIP listing checks. Electron prepends `Resources/runtime` to PATH; Python `resolve_ffmpeg()`. Music library stays external. No junk padding. CI YAML uses printf (no broken heredocs). Desktop **0.1.2**.

**P1 desk depth:** Hotkey hear-through retry + status oneshot backup; inject_mode never coerced from boolean; AUTO end-pulse window floor; ASSIST VOCALS IN for MUSIC/PROMO; segment VT attach errors surfaced. pytest coverage for runtime resolve + pulse/inject.

**Still not Done (do not fake):** Real AU host, live Liquidsoap Harbor graph, CoreAudio PCM multi-bus subtract, Apple notarized DMG.

## Market-ready P0 2026-09-06 (import · VU idle · hybrid desk)

| SHA | Theme |
|-----|--------|
| *(this commit)* | P0: Import audio fixed, VU idle dark, hybrid Maestro/Netia UI, PLAY+ingest e2e |
| `0cc10a9` | macos-dmg.yml YAML fix |
| `b37dc4f` | Packaging 0.1.1 + desk harden + Liquidsoap v3 |

**Import:** DROP / Import audio → `/api/library/ingest` (multipart + `filename*`) and Electron JSON `path` via `/api/ingest`. Clear ffmpeg / library-root errors in the strip.

**VU:** Idle LEDs fully dark (0). Animate only when playing / ON AIR.

**Hybrid UI:** `.desk-hybrid` modern landscape shell + big PLAY/STOP/SKIP/NEXT; plain-English Library / Clocks / Settings / Import audio.

**PLAY:** Ingest → Living Log insert → PLAY yields `playable_url` (pytest e2e).

**Package size target:** grow Mac ZIP/DMG toward **500MB–1GB+** with real ffmpeg / Liquidsoap / demo beds (see `packaging/SIZE_TARGET.md`) — no junk padding; music library stays external.

**AU host:** Still scaffold only.

## Market-ready pass 2026-09-06 (first-run UX + status harden)

| SHA | Theme |
|-----|--------|
| (folded) | Welcome tip + version badge + status null-guards |
| `0cc10a9` | Fix macos-dmg.yml YAML (heredoc) |
| `b37dc4f` | Packaging 0.1.1 + desk harden + Liquidsoap v3 |

**First-run / market UX:** Dismissible On-Air welcome tip (localStorage) pointing to DROP AUDIO, CLOCKS, LIBRARY, Settings, and Mac Gatekeeper `Open MQ Radio.command` ZIP tip.

**Stability:** `/api/status` poll null-guards (partial/offline); Living Log fetch failure no longer blank the desk; play continues when media is missing (clear `engine-msg`).

**Version badge:** Titlebar shows packaging **0.1.1** · short build SHA via `/api/version`.

**AU host:** Still scaffold only — no fake host (**market preview**).

## Market-ready pass 2026-09-06 (packaging + desk harden + Liquidsoap v3)

| SHA | Theme |
|-----|--------|
| `b37dc4f` | Packaging 0.1.1 + Gatekeeper README; desk empty/error harden; Liquidsoap handoff v3 operator install |
| `39f2081` | AU insert load/process scaffold + Settings inactive banner |
| `c5c48a3` | Mix-minus Program−Aux subtract + transmission DSP depth |

**Packaging:** Desktop **0.1.1**. Canonical `packaging/macos/Open MQ Radio.command` + beginner-clear **`README-INSTALL.txt`** staged into ZIP/DMG (CI verifies ZIP listing). Same files mirrored under `desktop/resources/` and listed in electron-builder `extraResources`. Gatekeeper notes in README rewritten for first-time operators.

**Desk hardening:** Living Log / Clock Editor / Library Manager empty-state hints for new users; ingest surfaces HTTP/non-JSON/empty-file errors in the strip; Settings audio save awaits server confirm and reports issues; null-safe Settings open/close.

**Transmission / Liquidsoap:** Handoff **v3** regenerates FM/Digital + `transmission_mode` + `operator_install` (`brew install liquidsoap` Master Control path). Still a stub graph — not a live Liquidsoap operator process.

**AU host:** No fake progress — scaffold + inactive banner only (**market preview**).

### Still deferred (not DMG / broadcast bar)
- Real **AU/AAX hosting** (Mac native binary / Electron addon — not faked)
- Live Liquidsoap Master Control graph + Harbor/Telnet from engine
- CoreAudio **PCM** mix-minus subtract on dual devices
- Apple Developer ID signed DMG (ad-hoc / Gatekeeper helper only)

## Away session 2026-09-06 (AU insert interface + Settings UX)

| SHA | Theme |
|-----|--------|
| *(this commit)* | AU insert `load`/`process` scaffold + Settings inactive banner |
| `c5c48a3` | Mix-minus Program−Aux subtract + transmission DSP depth |
| `8172f9e` | Multi-bus CoreAudio/mock router + AU insert architecture stub |

**AU insert (not a host):** `mq_radio/engine/au_insert.py` defines `load(name) → process(buffer)` — raises `AuHostNotAvailable` / `NotImplementedError` until a real Mac host exists (never silent passthrough). `desktop/au_insert/README.md` documents the Electron native-addon path. Settings shows **Native chain active — AU host not loaded** when an AU is selected, with docs link. Status adds `operator_message` / `docs` / `docs_url`. Native MQ chain still runs.

### Still deferred (not DMG-bar met)
- Real **AU/AAX hosting** (plugin DSP on Program bus — interface + warning only)
- Mac/Liquidsoap **full** transmission chain (browser Program processor + WAV peak/AGC stub + handoff stub — not a live Liquidsoap operator graph)
- CoreAudio **PCM** mix-minus subtract on dual devices (browser graph is live subtract today)

## Away session 2026-09-06 (mix-minus subtract + TX DSP)

| SHA | Theme |
|-----|--------|
| *(this commit)* | Browser mix-minus Program−Aux subtract + transmission DSP depth |
| `8172f9e` | Multi-bus CoreAudio/mock router + AU insert architecture stub |
| `dc26a8b` | Program CoreAudio / mock audio output router + `/api/status` `audio_route` |
| `3464662` | Real Mac CoreAudio device enum bridge + Settings wire-up |

**Mix-minus subtract:** Browser On-Air Web Audio builds `program_processed − aux_return` when Aux capture is live; status `mix_minus.subtract_active` (via `POST /api/audio/mix-minus`). Fallback pairing-only when no Aux capture. Mac engine path documented (`program − aux → mix_minus device`); CoreAudio PCM subtract still engine milestone.

**Transmission DSP depth:** Settings **transmission_mode** toggle (desk vs aggressive FM/Digital) on the browser Program processor — audible difference (FM pre-emphasis denser / Digital cleaner). Server peak/AGC stub `transmission_dsp.process_wav_file` + `POST /api/settings/processing/wav-stub`. Liquidsoap handoff **v2** JSON/liq regenerated to match templates + mix-minus Mac notes.

### Still deferred (not DMG-bar met)
- Real **AU/AAX hosting** (plugins not loaded — architecture + `au_insert_inactive` warning only)
- Mac/Liquidsoap **full** transmission chain (browser Program processor + WAV peak/AGC stub + handoff stub — not a live Liquidsoap operator graph)
- CoreAudio **PCM** mix-minus subtract on dual devices (browser graph is live subtract today)

## Away session 2026-09-06 (continued)

| SHA | Theme |
|-----|--------|
| `8172f9e` | Multi-bus CoreAudio/mock router + AU insert architecture stub |
| `dc26a8b` | Program CoreAudio / mock audio output router + `/api/status` `audio_route` |
| `3464662` | Real Mac CoreAudio device enum bridge + Settings wire-up |

**Multi-bus routing:** `audio_router` treats **Program as primary** and opens best-effort CoreAudio/PortAudio streams for Headphones, Aux, **Monitor, Mix-minus, Stream, Record** when `sounddevice` resolves devices (Mac). Linux/CI mock records all buses in status. Mix-minus status: `{out, aux_in, paired}` (browser subtract added in later commit).

**AU insert architecture (not a host):** Program path documented as `source → [AU insert if set] → native processing → device`. Selected AU **name** persists in Settings. Without an AU host, `audio_route.au_insert.warning = au_insert_inactive` and **native still runs**. Electron note for a future host in `desktop/main.js`.

### Still deferred (not DMG-bar met)
- Real **AU/AAX hosting** (plugins not loaded — architecture + warning only)
- Mac/Liquidsoap **full** transmission operator chain (browser TX mode + WAV stub + handoff v2 are in)
- Mix-minus **CoreAudio PCM** subtract (browser Web Audio subtract is in; Mac dual-device still later)

## Away session 2026-09-06

Wave from On-Air desk depth through daypart weekday packs (HEAD was `35c686c` before this polish commit).

| SHA | Theme |
|-----|--------|
| `5dd4629` | Ingest / VU / Segment Editor / VT take / processing / routing |
| `957e4bb` | End-pulse AUTO, Web Audio processing/VU/ramps, hotkey play |
| `28199cd` | Overlapping dual-deck segue (A/B + Segue markers) |
| `639b2b4` | Real segue audition, editable end-pulse, Gatekeeper helper |
| `8f926dd` | Server-side VT trim, hotkey engine inject, Liquidsoap handoff stub |
| `815303a` | ASSIST VOCALS IN, Living Log filter, TO TIME/ETM |
| `e1eb135` | GENERAL+OVERNIGHT clocks, hour generate, MANUAL VT survive |
| `c5a2813` | Clock Editor UI + hard ETM/HIT fills |
| `b79b683` | Category/Library Manager + FILLER cart pool for ETM fills |
| `4283ec6` | Daypart designer: hour→clock grid + clone clocks |
| `35c686c` | Per-weekday `day_mask` packs for Daypart Designer |

**This polish:** Electron preload `webUtils.getPathForFile` for hotkey absolute-path drops (Mac app); web still pastes path. Hotkey drop targets slot under cursor. Default hotkey slots always include `path` + `inject_mode`.

### Still deferred (not DMG-bar met)
- **AU/AAX hosting** (insert slot + optional `auval` name list only)
- Transmission-path **DSP** / mix-minus subtract — see newer section above (closed further since)
- Opening CoreAudio **streams** — later commits open multi-bus streams on Mac

Do **not** treat the unsigned/ad-hoc Mac DMG as broadcast-ready until AU host + full Mac TX chain bar is closed.
