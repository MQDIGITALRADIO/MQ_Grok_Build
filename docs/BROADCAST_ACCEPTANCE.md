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
- [x] Living Log edit: select, Delete, Insert, Replace; survives regenerate for MANUAL/VT
- [ ] Hotkeys: fire cart (library or in-place path); inject over program / queue next
- [ ] VT Record → trim → save → attach to log; Segment Editor cuts long files
- [ ] Segue Editor: markers + duck + real audition + dual-deck crossfade

## P1 — Pro desk parity (Maestro / Netia / mAirList class)
- [ ] Cart decks A/B/C fully readable (title/artist/time/ending)
- [ ] Cartwall / hotkey bank multi-page, color/type, reorder, persist
- [x] Clocks + daypart grid + weekday/weekend packs; generate hour/24h
- [x] Categories + library manager; FILLER pool for ETM/HIT/HARD
- [x] TO TIME / ETM / HIT fill stretch
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
- Target Mac ZIP/DMG **≥ ~500 MB**, aiming **~1 GB** class with *real* bundled substance (ffmpeg, Liquidsoap/Master Control bits, engine, sample beds, processing assets, docs). Desktop **0.1.2** stages **~637MB** substance class (ffmpeg + demo beds + Master Control + engine — not junk padding).
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
| P0 AUTO end-pulse / ASSIST talk-up | **Partial** | `finish_if_due` + `/api/pulse` (body `date` honored); ASSIST GO clears + advances; timing exposes `in_intro`/`talk_up_remaining_ms`/`vocals_in`; pytest desk harden; Mac hear-through still verify |
| P0 Living Log edit Delete/Insert/Replace | **Done** | Service + `/api/log/{delete,insert,replace}`; insert clamps `after_position`; MANUAL/VT survive soft regenerate; API e2e in `tests/test_desk_harden_partials.py` |
| P0 Hotkeys fire / inject | **Partial** | `/api/hotkey/fire` + status message (missing path); `/api/hotkeys/reorder` + color persist + F-key rekey; desk drag/Up-Down; Mac path via preload still verify |
| P0 VT record / Segment Editor | **Partial** | Segment invalid window / missing track errors; ffmpeg cut + markers-only; VT attach; needs Mac audio device pass |
| P0 Segue Editor audition + dual-deck | **Partial** | Dual-deck engine crossfade **Done** without Mac audio (`test_dual_deck_segue` + P1 e2e: overlap flip, fade clear). Audition/hear-through still Mac verify — keep Partial |
| P1 Decks A/B/C readable | **Partial** | Hybrid cards; ending/timers in |
| P1 Cartwall multi-page | **Partial** | Pages + reorder/persist/color; status feedback on fire |
| P1 Clocks + daypart packs | **Done** | Clock editor + daypart packs; clone/save/daypart HTTP e2e; generate_hour uses map; `tests/test_daypart_designer.py` + `tests/test_p1_library_clocks_etm_deck.py` |
| P1 Categories / FILLER | **Done** | Library manager categories HTTP; FL filler pool; pick/insert toward ETM; ingest edges; `tests/test_categories_and_filler_pool.py` + `tests/test_p1_library_clocks_etm_deck.py` |
| P1 TO TIME / ETM | **Done** | Studio clock TO TIME/ETM; hard HIT fill stretch/compress/filler; `to_time_payload`; `tests/test_clock_editor_and_etm_fill.py` + living_log ETM + P1 e2e |
| P1 Multi-bus + mix-minus subtract | **Partial** | Browser subtract live; CoreAudio PCM still P2 |
| P1 Native FM/Digital + TX mode | **Partial** | Browser processor + WAV stub |
| P2 Real AU host | **Missing** | Scaffold + banner only — do not claim done |
| P2 Live Liquidsoap graph | **Missing** | Handoff v3 + Master Control pack bundled; no live Harbor/Telnet operator graph |
| P2 CoreAudio PCM multi-bus | **Missing** | Enum + best-effort streams |
| P2 Apple notarized DMG | **Missing** | Gatekeeper helper path only |
| P2 Aircheck / traffic / RDS / multi-user | **Missing** | Not started |

**P2 rule:** never tick Done with stubs.

## Mac package size target (substance, not padding)

Matt bar: installer **~500MB–1GB+** signals a real broadcast product. Empty/junk padding is forbidden.

| Bundle | Status | Notes |
|--------|--------|-------|
| MQRadioEngine (PyInstaller) | Partial | Core engine in app (CI PyInstaller) |
| ffmpeg / ffprobe (static) | **Done** | darwin-arm64 staged via `packaging/scripts/stage_mac_resources.sh` → `desktop/resources/runtime/`; Electron PATH + `resolve_ffmpeg()` |
| Liquidsoap runtime | Partial | Master Control pack + handoff v3 bundled; brew `liquidsoap` binary copied when present on macOS CI — live Harbor graph still Missing |
| Richer demo beds / imaging | **Done** | Minutes of real PCM under `desktop/resources/demo_beds` (generator; CI ~400MB+) — not music library |
| Docs + Gatekeeper helper | Done | README-INSTALL + Open MQ Radio.command |
| Music library | **External** | MQ Digital drive / Settings library root — never stuff commercial music into the .app |

CI (`.github/workflows/macos-dmg.yml` + `packaging/ci/macos-dmg.yml`): stage runtime + beds into `extraResources`; soft-warn if ZIP &lt; 400MB; listing checks for ffmpeg + demo_beds. No junk padding. Heredocs avoided (printf).


