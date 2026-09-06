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
- [x] AUTO advances on end-pulse / segue; ASSIST/LIVE talk-up VOCALS IN works
- [x] Living Log edit: select, Delete, Insert, Replace; survives regenerate for MANUAL/VT
- [ ] Hotkeys: fire cart (library or in-place path); inject over program / queue next
- [ ] VT Record → trim → save → attach to log; Segment Editor cuts long files
- [ ] Segue Editor: markers + duck + real audition + dual-deck crossfade

## P1 — Pro desk parity (Maestro / Netia / mAirList class)
- [x] Cart decks A/B/C fully readable (title/artist/time/ending)
- [x] Cartwall / hotkey bank multi-page, color/type, reorder, persist
- [x] Clocks + daypart grid + weekday/weekend packs; generate hour/24h
- [x] Categories + library manager; FILLER pool for ETM/HIT/HARD
- [x] TO TIME / ETM / HIT fill stretch
- [x] Intro / outro / end-pulse markers editable; defaults on ingest
- [ ] Voice tracking (manual + AI script/approve/placeholder→Log path); Downloads/VT inbox ingest — Vocloner real voice still external; Mac mic Partial
- [x] Multi-bus: Program, Monitor, Headphones, Aux, Mix-minus↔Aux in, Stream, Record
- [x] Mix-minus Program−Aux subtract when Aux live
- [x] Native FM / Digital processing templates + transmission mode
- [x] Studio clock, ELAPSED/REMAINING, ending type
- [x] Library root on external drive + inbox ingest; hotkeys play in-place

## P2 — Above comparable / market package
- [ ] Real AU insert host (empty = native); not scaffold-only — messaging/scaffold only
- [ ] Liquidsoap / Master Control live Harbor chain (operator pack + dry-run ≠ live)
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
- Target Mac ZIP/DMG **≥ ~500 MB**, aiming **~1 GB** class with *real* bundled substance (ffmpeg, Liquidsoap/Master Control bits, engine, sample beds, processing assets, docs). Desktop **0.1.3** stages **~637MB** substance class (ffmpeg + demo beds + Master Control + engine — not junk padding).
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
| P0 AUTO end-pulse / ASSIST talk-up | **Done** | Exact pulse boundary + noop; ASSIST `talk_up_applicable` (MUSIC/PROMO/VT); LIVE/ASSIST GO via `/api/pulse`; AUTO ignores talk-up cue; `tests/test_broadcast_partials_depth.py` + desk harden. Mac hear-through still verify on real devices |
| P0 Living Log edit Delete/Insert/Replace | **Done** | Service + `/api/log/{delete,insert,replace}`; insert clamps `after_position`; MANUAL/VT survive soft regenerate; API e2e in `tests/test_desk_harden_partials.py` |
| P0 Hotkeys fire / inject | **Partial** | Fire path hardened: real path → playable_url + media serve + status oneshot; track_id resolve; body `date` for queue_next; desk-only inject=false; empty reject; boolean inject_mode safe; duration probe. Desk passes log-date + refresh on queue. Mac hear-through / Electron path drop still verify — keep Partial |
| P0 VT record / Segment Editor | **Partial** | Deeper API e2e: record→segment(+source markers)→attach→log cart; invalid trim OUT≤IN + empty decode rejected; segment returns source_markers_saved; operator UX trim checks + status polish. **Mac mic device pass stays Partial** |
| P0 Segue Editor audition + dual-deck | **Partial** | Dual-deck engine crossfade **Done** without Mac audio. Segue context/save e2e + desk audition messaging (browser media / tone fallback). Audition/hear-through still Mac device verify — keep Partial |
| P1 Decks A/B/C readable | **Done** | Status `decks.program/a/b` carry title/artist/duration/elapsed/remaining + `ending_type`/`ending_label` (classify_ending); desk fillDeck + classifyEndingType fallback; studio_clock on `/api/status`; `tests/test_acceptance_p1_desk_readable.py` |
| P1 AI overnight / PD assist (script→approve→placeholder→Log) | **Partial** | Operator path Done in code: `generate_ai_breaks` → `approve_ai_breaks` → `render_placeholder_vt` / `pd-assist` + `/api/ai-breaks/operator-path` + `/api/vt/render-placeholder`; Living Log attach + soft-regen preserve. Vocloner remains clipboard/open URL (no API). Mac mic / real Vocloner WAV still verify — keep Partial (do not claim Done) |
| P1 Intro/outro/end-pulse markers | **Done** | `default_markers_for` on ingest; `/api/library/track/markers` + Segment Editor Save pulse; GET track returns ending; clamp ≤45%; bad id → 400; `tests/test_track_markers_and_segue_media.py` + acceptance e2e |
| P1 Studio clock / ELAPSED / ending | **Done** | Wallclock + TO TIME/ETM panel; `/api/status` timing elapsed/remaining + `studio_clock` payload; deck ending COLD/SOFT/FADE; Living Log `ending_label`; acceptance e2e |
| P1 Library root + VT inbox + hotkey in-place | **Done** | `/api/settings/library-root` redirect ingest; VT inbox import; hotkey absolute path no library copy (`copied_to_library: false`); `tests/test_end_pulse_and_ramps.py` + `test_routing_and_hotkeys.py` + acceptance e2e. Mac hear-through still P0 Partial |
| P1 Cartwall multi-page | **Done** | `set_pages`/`clear_slot`/`move_hotkey` + `/api/hotkeys/{pages,clear,move}`; ui_page persist; color chips; desk `loadHotkeys`/`persistHotkeys` fixed; `tests/test_broadcast_partials_depth.py` |
| P1 Clocks + daypart packs | **Done** | Clock editor + daypart packs; clone/save/daypart HTTP e2e; generate_hour uses map; `tests/test_daypart_designer.py` + `tests/test_p1_library_clocks_etm_deck.py` |
| P1 Categories / FILLER | **Done** | Library manager categories HTTP; FL filler pool; pick/insert toward ETM; ingest edges; `tests/test_categories_and_filler_pool.py` + `tests/test_p1_library_clocks_etm_deck.py` |
| P1 TO TIME / ETM | **Done** | Studio clock TO TIME/ETM; hard HIT fill stretch/compress/filler; `to_time_payload`; `tests/test_clock_editor_and_etm_fill.py` + living_log ETM + P1 e2e |
| P1 Multi-bus + mix-minus subtract | **Done** | Browser path: route all buses + `/api/audio/mix-minus` subtract_active reflected in `/api/status`; pairing + operator description. CoreAudio PCM multi-bus remains P2 Missing |
| P1 Native FM/Digital + TX mode | **Done** | Operator path: `/api/settings/processing` FM/Digital + `transmission_mode`; status `+TX`; `/api/settings/processing/wav-stub` peak/AGC preview. Not live Harbor (P2 Missing) |
| P2 Real AU host | **Missing** | Clearer inactive/unavailable messaging + load/process scaffold tests (`au_insert`); Settings banner + `/api/settings/au-insert` — **not** a real AU host |
| P2 Live Liquidsoap / Harbor | **Missing** | Operator path strengthened: bundled templates, `OPERATOR.md`, dry-run validation, start/stop stubs that fail clearly when binary missing / graph not wired (`master_control` + Settings UI). **Live Harbor still Missing** — do not claim Done |
| P2 CoreAudio PCM multi-bus | **Missing** | Enum + best-effort streams |
| P2 Apple notarized DMG | **Missing** | Gatekeeper helper + README-INSTALL polished (damaged/quarantine path); notarization still Missing |
| P2 Aircheck / traffic / RDS / multi-user | **Missing** | Not started |

**P2 rule:** never tick Done with stubs.

## Mac package size target (substance, not padding)

Matt bar: installer **~500MB–1GB+** signals a real broadcast product. Empty/junk padding is forbidden.

| Bundle | Status | Notes |
|--------|--------|-------|
| MQRadioEngine (PyInstaller) | Partial | Core engine in app (CI PyInstaller) |
| ffmpeg / ffprobe (static) | **Done** | darwin-arm64 staged via `packaging/scripts/stage_mac_resources.sh` → `desktop/resources/runtime/`; Electron PATH + `resolve_ffmpeg()` |
| Liquidsoap runtime | Partial | Operator pack: handoff v3 + `mq_master_control_operator.liq` markers, dry-run API, start/stop stubs; brew binary copied when present on macOS CI — **live Harbor still Missing** |
| Richer demo beds / imaging | **Done** | Minutes of real PCM under `desktop/resources/demo_beds` (generator; CI ~400MB+) — not music library |
| Docs + Gatekeeper helper | Done | README-INSTALL (damaged/quarantine) + Open MQ Radio.command first-run polish |
| Music library | **External** | MQ Digital drive / Settings library root — never stuff commercial music into the .app |

CI (`.github/workflows/macos-dmg.yml` + `packaging/ci/macos-dmg.yml`): stage runtime + beds into `extraResources`; soft-warn if ZIP &lt; 400MB; listing checks for ffmpeg + demo_beds. No junk padding. Heredocs avoided (printf).


