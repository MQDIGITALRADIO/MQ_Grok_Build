# MQ Radio — Broadcast acceptance checklist (paying-client bar)

Cross-check vs Maestro / early Zetta / Netia Radio-Assist / mAirList / StationPlaylist / WideOrbit-class desks.
**Rule:** no stub counts as done. Function + clear hybrid Maestro clarity + Netia landscape UI.
**Triple-check:** each item must pass manual verify + automated test where possible.

## P0 — Must work now (Matt-reported + on-air trust)
- [x] Import audio (wav/mp3/flac/mp4) via DROP + Browse — library cart created, visible in LIBRARY
- [x] VU / LEDs dark when idle; only move when actually PLAY / ON AIR with audio
- [x] Every control has clear English label (PLAY STOP SKIP NEXT, Import audio, Library, Clocks, Settings…)
- [x] Hybrid UI: Maestro-clear transport/log/decks + modern Netia-landscape shell (not Win95 beige)
- [x] PLAY plays an ingested cart through Program path with playable_url (web e2e; Mac hear-through verify)
- [ ] AUTO advances on end-pulse / segue; ASSIST/LIVE talk-up VOCALS IN works
- [ ] Living Log edit: select, Delete, Insert, Replace; survives regenerate for MANUAL/VT
- [ ] Hotkeys: fire cart (library or in-place path); inject over program / queue next
- [ ] VT Record → trim → save → attach to log; Segment Editor cuts long files
- [ ] Segue Editor: markers + duck + real audition + dual-deck crossfade

## P1 — Pro desk parity (Maestro / Netia / mAirList class)
- [ ] Cart decks A/B/C fully readable (title/artist/time/ending)
- [ ] Cartwall / hotkey bank multi-page, color/type, reorder, persist
- [ ] Clocks + daypart grid + weekday/weekend packs; generate hour/24h
- [ ] Categories + library manager; FILLER pool for ETM/HIT/HARD
- [ ] TO TIME / ETM / HIT fill stretch
- [ ] Intro / outro / end-pulse markers editable; defaults on ingest
- [ ] Voice tracking (manual + AI script/approve path); Downloads/VT inbox ingest
- [ ] Multi-bus: Program, Monitor, Headphones, Aux, Mix-minus↔Aux in, Stream, Record
- [ ] Mix-minus Program−Aux subtract when Aux live
- [ ] Native FM / Digital processing templates + transmission mode
- [ ] Studio clock, ELAPSED/REMAINING, ending type
- [ ] Library root on external drive + inbox ingest; hotkeys play in-place

## P2 — Above comparable / market package
- [ ] Real AU insert host (empty = native); not scaffold-only
- [ ] Liquidsoap / Master Control live chain (not handoff docs only)
- [ ] CoreAudio PCM multi-bus (not enum + best-effort only)
- [ ] Apple Developer ID signed + notarized Mac build (or documented Gatekeeper path that always works)
- [ ] Aircheck / compliance logger
- [ ] Traffic / commercial log + separation rules (basic)
- [ ] Remote VT / contribution feed
- [ ] Multi-station / networked Living Log (optional later)
- [ ] RDS / now-playing export
- [ ] Role permissions / multi-user (optional later)

## Triple-check protocol
1. Automated: full pytest green
2. Manual web desk: import → library → insert log → PLAY → hear → STOP; VU idle dark
3. Manual Mac ZIP: Gatekeeper helper → same path on real devices

## Package size (Matt)
- Target Mac ZIP/DMG **≥ ~500 MB**, aiming **~1 GB** class with *real* bundled substance (ffmpeg, Liquidsoap/Master Control bits, engine, sample beds, processing assets, docs).
- Do **not** pad with empty/junk files.
- Primary music/VT library remains on external **MQ Digital** drive (not forced inside .app).

## Status matrix (code-backed — update every ship)

| Item | Status | Evidence |
|------|--------|----------|
| P0 Import wav/mp3/flac/mp4 (DROP + Browse) | **Done** | `/api/library/ingest` + `/api/ingest`; multipart `filename*`; Electron JSON `path`; UI Import audio; `tests/test_ingest_api_and_vu_idle.py` |
| P0 VU idle dark | **Done** | `_synthetic_vu` + client `applyVu` force 0 when not playing; same test |
| P0 Clear English labels | **Done** | PLAY/STOP/SKIP/NEXT, Import audio, Library, Clocks, Settings, Refresh |
| P0 Hybrid UI (Maestro + Netia landscape) | **Done** | `.desk-hybrid` modern dark landscape shell + big transport; not Win95 beige |
| P0 PLAY ingested cart → playable_url | **Done** | ingest → log insert → play → status `playable_url`; e2e test |
| P0 AUTO end-pulse / ASSIST talk-up | **Partial** | Engine + VOCALS IN present; keep regression-testing on Mac |
| P0 Living Log edit Delete/Insert/Replace | **Partial** | APIs + UI exist; verify after import workflow |
| P0 Hotkeys fire / inject | **Partial** | Bank + path fire in place; Mac path via preload |
| P0 VT record / Segment Editor | **Partial** | UI + APIs; needs Mac audio device pass |
| P0 Segue Editor audition + dual-deck | **Partial** | Markers/duck/audition present; Mac hear-through |
| P1 Decks A/B/C readable | **Partial** | Hybrid cards; ending/timers in |
| P1 Cartwall multi-page | **Partial** | Hotkey bank pages exist |
| P1 Clocks + daypart packs | **Partial** | Clock editor + daypart UI |
| P1 Categories / FILLER | **Partial** | Library manager + filler pool |
| P1 TO TIME / ETM | **Partial** | Studio clock panel |
| P1 Multi-bus + mix-minus subtract | **Partial** | Browser subtract live; CoreAudio PCM still P2 |
| P1 Native FM/Digital + TX mode | **Partial** | Browser processor + WAV stub |
| P2 Real AU host | **Missing** | Scaffold + banner only — do not claim done |
| P2 Live Liquidsoap graph | **Missing** | Handoff v3 docs/templates only |
| P2 CoreAudio PCM multi-bus | **Missing** | Enum + best-effort streams |
| P2 Apple notarized DMG | **Missing** | Gatekeeper helper path only |
| P2 Aircheck / traffic / RDS / multi-user | **Missing** | Not started |

**P2 rule:** never tick Done with stubs.

## Mac package size target (substance, not padding)

Matt bar: installer **~500MB–1GB+** signals a real broadcast product. Empty/junk padding is forbidden.

| Bundle | Status | Notes |
|--------|--------|-------|
| MQRadioEngine (PyInstaller) | Partial | Core engine in app |
| ffmpeg / ffprobe (static) | Planned | Required for mp4/flac extract; brew or vendored under `desktop/resources/runtime/` |
| Liquidsoap runtime | Planned | Pair with handoff v3; operator graph later |
| Richer demo beds / imaging | Planned | IDs, sweepers, beds under `data/demo_audio` (not full music library) |
| Docs + Gatekeeper helper | Done | README-INSTALL + Open MQ Radio.command |
| Music library | **External** | MQ Digital drive / Settings library root — never stuff commercial music into the .app |

CI (`packaging/ci/macos-dmg.yml` / electron-builder): after P0 green, stage runtime binaries + demo beds into `extraResources` and assert ZIP/DMG size ≥ 400MB (soft) with listing checks for ffmpeg + liquidsoap + beds.


