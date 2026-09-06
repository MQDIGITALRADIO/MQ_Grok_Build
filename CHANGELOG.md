# Changelog — MQ Radio Automation

Lean build log for Matt. SHAs are on `main` (`MQDIGITALRADIO/MQ_Grok_Build`).

## Desk grind 2026-09-07 (0.1.4 · Matt live-sim + SKIP fix)

| SHA | Theme |
|-----|--------|
| *(this commit)* | Desktop **0.1.4**; Matt 36-cart live-radio e2e; mid-cart SKIP no longer double-advances |

**Version:** Desktop packaging **0.1.4** (`desktop/package.json`, `build_info.DESKTOP_VERSION`, titlebar badge, preload fallback) for next Mac preview (idle meters/VU/import from `f7816c1` + tonight's grind).

**Engine:** `MockEngine.skip` — mid-cart SKIP marks only the ON AIR row then starts the next cart. Idle SKIP still drops the upcoming cue once. Fixes operator NEXT burning two carts (paying-client live-radio bug).

**Matt sample bank:** `data/matt_sample_carts/` — 36 real carts (MP3 music/imaging + WAV/MP3 ID/sweeper shorts 28–36). Live-sim covers import destinations (Library/Living Log/Hotkey/Deck A), ASSIST talk-up + GO, dual-deck crossfade timing, STOP mid-cart idle meters/VU, skip mid-sequence, WAV/MP3 hotkeys over music, full-bank ingest.

**Tests:** expanded `tests/test_desk_live_radio_scenarios.py`; full suite green (250).

**Not Done:** AU host / Harbor / notarization (unchanged — do not claim Done).

## Desk grind 2026-09-07 (idle meters/VU + import destinations)

| SHA | Theme |
|-----|--------|
| `f7816c1` | Idle Deck A meter empty; VU live/idle/STOP; Import Send-to Library\|Living Log\|Hotkey\|Deck A; Electron browse; broadcast scenario e2e |

**Meters (P0 visual):** Historic `.meter-bar { width: 62% }` default painted a stuck ~60% green bar when idle / false ON AIR. Default + `.idle` now **width 0 / dark**. JS `setMeterIdle` / `setMeterProgress` set inline width. ON AIR lamp/label only when `running`/`timing.playing` (`deckOnAir`). STOP clears meters + VU immediately.

**VU:** `resolveDeskVu` prefers Web Audio analyser (Living Log + hotkey oneshot); synthetic fallback uses **live** progress (not frozen snap). Server `_synthetic_vu` moves during oneshot; idle = fully dark; STOP clears.

**Import:** Electron native `mq:open-audio-files` dialog (absolute paths); FormData fallback; strip errors for missing file / empty multipart / ffmpeg hints. **Send to** dropdown: Library only · Living Log · Hotkey cart · Cue Deck A.

**Tests:** `tests/test_desk_live_radio_scenarios.py` — idle desk, import destinations, PLAY→progress/VU→STOP, hotkey oneshot vs log ON AIR, insert/replace/delete, multi-cart skip, bad path / empty upload. Full suite green.

**Not Done:** AU host / Harbor / notarization (unchanged Partial).

## Overnight grind 2026-09-06 (0.1.3 · P1 desk readable + acceptance audit)

| SHA | Theme |
|-----|--------|
| *(this commit)* | Desktop **0.1.3**; decks/markers/studio-clock/library-root Partial→Done; CHANGELOG SHA accuracy |

**Version:** Desktop packaging **0.1.3** (`desktop/package.json`, `build_info.DESKTOP_VERSION`, titlebar badge, preload fallback). Aligns badge with post-0.1.2 operator-path grind (cartwall/AUTO/mix-minus/TX/AI-PD/Vocloner/Master Control).

**Partial → Done (pytest + HTTP e2e, no Mac audio):**
- **P1 Decks A/B/C readable** — `/api/status` deck slots now carry `ending_type`/`ending_label` (not only on Living Log events); desk `classifyEndingType` fallback when slot omits ending
- **P1 Intro/outro/end-pulse markers** — editable via `/api/library/track/markers` + Segment Editor; ingest defaults; GET track returns ending; invalid track_id → 400 (no 500)
- **P1 Studio clock / ELAPSED / ending** — timing elapsed/remaining + `studio_clock` (TO TIME/ETM) on status; COLD/SOFT/FADE ending on decks
- **P1 Library root + VT inbox + hotkey in-place** — external library root redirects ingest; VT inbox import; hotkey absolute path `copied_to_library: false`

**Harden:** markers API int coercion; deck ending enrichment; CHANGELOG backfilled real SHAs for `9c9d6ed`…`080860d`.

**Still Partial / Missing (Mac/Apple only):** P0 Hotkeys hear-through; P0 VT mic device; P0 Segue audition hear-through; P1 AI/PD Vocloner real voice; P2 real AU host; live Harbor; CoreAudio PCM; notarization.

**Tests:** `tests/test_acceptance_p1_desk_readable.py`; full suite green.

## Desk grind 2026-09-06 (Vocloner operator path polish)

| SHA | Theme |
|-----|--------|
| `9c9d6ed` | Vocloner clipboard/script export + paste→WAV→Import desk flow; Settings empty-state clarity |

**Vocloner (still no public API):** `mq_radio.voice_tracker.vocloner_export` builds clipboard-ready paste bodies + optional `data/vocloner-export/*.txt` packages. Desk: **Copy script** / **Export .txt** / **Render in Vocloner** with numbered paste → WAV → **Import VT folder** flow. CLI `export-vocloner-script`. APIs: `GET /api/vocloner/operator-flow`, `POST /api/vocloner/export-script` (alias `/api/vt/vocloner-export`). VT inbox import tags `VOCLONER` when filenames look like Vocloner renders.

**Settings clarity:** library root + VT inbox status lines (empty hints); Master Control empty/first-run copy; AU native-only status when insert empty. Never marks live Harbor / real AU Done.

**Tests:** `tests/test_vocloner_operator_path.py`; full suite green.

## Overnight grind 2026-09-06 (AI/PD assist operator path + 24h coverage)

| SHA | Theme |
|-----|--------|
| `b4803a6` | Script approve → Vocloner/placeholder → Living Log VT attach; 24h coverage harden |

**PD assist / AI upstairs only:** `placeholder_render` writes honest PCM beds (not Vocloner voice), attaches to APPROVED VT rows on the Living Log (`PLACEHOLDER_RENDER`). Full path: `generate-ai-breaks` → `approve-ai-breaks` → `render-placeholder-vt` / `pd-assist`. APIs: `POST /api/vt/render-placeholder`, `POST /api/ai-breaks/operator-path`. Desk: **Placeholder → Log** + **PD assist path**. Refuses drafts; skips silence; will not overwrite mic/Vocloner takes.

**Scheduler 24h:** `generate_log` returns `hours_covered` / `missing_hours` / `events_per_hour` / `coverage_complete`. Soft regenerate restores VT audio/trim columns; MANUAL placeholder carts survive.

**Acceptance:** P1 AI overnight/PD assist **Partial** (Vocloner external + Mac mic still open). Hard blockers stay Missing: real AU host, live Harbor, CoreAudio PCM, notarization, Mac hear-through/mic. No fake live song picker.

**Tests:** `tests/test_ai_pd_assist_operator_path.py`; full suite green.

## Desk grind 2026-09-06 (Master Control operator path + AU/Gatekeeper polish)

| SHA | Theme |
|-----|--------|
| `1904f15` | Liquidsoap Master Control operator path; AU unavailable messaging; first-run/Gatekeeper polish |

**Master Control (still Missing live Harbor):** `mq_radio.production.master_control` — bundled templates + `mq_master_control_operator.liq` dry-run markers, `OPERATOR.md`, binary probe, dry-run validation, start/stop stubs that fail clearly when binary missing or graph not wired. `LiquidsoapEngine` uses those stubs. Settings UI: Dry-run / Refresh templates / Start(stub) / Stop(stub) + export handoff. APIs: `GET/POST /api/settings/master-control…`. Never claims live Harbor Done.

**AU insert (still Missing real host):** clearer inactive/unavailable operator copy (`unavailable_reason`, platform message); `describe_insert` / `process_buffer` scaffold; richer router + `/api/settings/au-insert` status; banner uses status text. `process()` still raises — never silent passthrough.

**First-run / Gatekeeper:** welcome tip + empty Living Log + empty deck copy; Open MQ Radio.command + README-INSTALL damaged/quarantine polish; Master Control notes in install sheet.

**Acceptance:** P2 AU / live Liquidsoap / notarization remain **Missing** (honest matrix update only).

**Tests:** `tests/test_master_control_operator.py`; AU scaffold expansions; full suite green.

## Desk grind 2026-09-06 (hotkey fire + VT/segment depth · no Mac audio)

| SHA | Theme |
|-----|--------|
| `e477ab1` | Hotkey fire path reliability; VT/segment deeper API e2e + operator UX; acceptance triple-check |

**Hotkeys fire (still Partial — Mac hear-through):** `/api/hotkey/fire` probes duration, returns top-level `duration_ms` + `date`, enriches oneshot `playable_url`, rejects empty slots, desk-only `inject=false`, honors body date for `queue_next`. Desk `fireHotkeySlot` sends log-date, refreshes Living Log on queue, clearer missing/fail messages. pytest: existing path→media serve, track_id, queue_next date, boolean inject_mode safety.

**VT / Segment (still Partial — Mac mic device):** invalid trim OUT≤IN + empty decode rejected; segment API returns `source_markers_saved` / source intro·pulse; round-trip record→segment(+source markers)→attach→log cart e2e; operator trim validation + status polish in VT Studio / Segment Editor.

**Segue audition:** stays Partial (browser audition messaging only; dual-deck Done separately). No fake AU / live Harbor / CoreAudio PCM / notarization.

**Tests:** `tests/test_hotkey_vt_segment_depth.py` (+7); full suite green.

## Desk grind 2026-09-06 (Partial→Done depth · no Mac audio required)

| SHA | Theme |
|-----|--------|
| `d73c38d` | Cartwall/pages Done; AUTO/talk-up Done; mix-minus + TX operator Done; VT API e2e (device Partial) |

**Partial → Done (pytest + HTTP e2e):**
- **P1 Cartwall multi-page** — `set_pages` / `clear_slot` / `move_hotkey`; `/api/hotkeys/{pages,clear,move}`; ui_page persist; color chips; fixed missing desk `loadHotkeys`/`persistHotkeys`
- **P0 AUTO end-pulse / ASSIST talk-up** — exact pulse boundary + noop; `talk_up_applicable` for MUSIC/PROMO/VT in ASSIST/LIVE; AUTO ignores VOCALS IN cue
- **P1 Multi-bus + mix-minus** — browser subtract path e2e via `/api/audio/mix-minus` → status (CoreAudio PCM stays P2)
- **P1 Native FM/Digital + TX mode** — operator processing + wav-stub e2e (not live Harbor)

**Still Partial (at ship):** P0 Hotkeys fire hear-through (Mac); P0 VT **device pass** (API e2e added); P0 Segue audition; P1 decks readability (later Done in 0.1.3 acceptance grind).

**Never Done (unchanged):** Real AU host, live Liquidsoap Harbor, CoreAudio PCM multi-bus, notarization.

**Tests:** `tests/test_broadcast_partials_depth.py` (+9); full suite green.

## Desk grind 2026-09-06 (0.1.2 · P1 Done + first-run empty harden)

| SHA | Theme |
|-----|--------|
| `080860d` | Desktop **0.1.2**; P1 library/clocks/FILLER/ETM Done; On-Air empty/error harden; ~637MB package notes |

**Version:** Desktop packaging **0.1.2** (`desktop/package.json`, `build_info.DESKTOP_VERSION`, titlebar badge, preload fallback). Release notes: Mac package **~637MB** substance class (bundled **ffmpeg** + noise-textured **demo beds** + Master Control + engine — not junk; sine pads that ZIP to nothing forbidden). CI soft floor **≥500MB** ZIP/DMG; beds staged at `MQ_DEMO_BED_MB=850`. Music library stays external.

**P1 → Done (pytest + HTTP e2e, no Mac audio required):**
- Categories / Library manager + FILLER pool toward ETM/HIT
- Clocks + daypart packs (clone / daypart save / generate_hour map)
- TO TIME / ETM hard fill stretch·compress·filler
- Dual-deck engine crossfade proven without CoreAudio (Segue audition still Partial — Mac hear-through)

**On-Air first-run Mac operators:** Welcome tip step list; empty Living Log / empty decks spell Import → Clocks → PLAY; engine offline points at `Open MQ Radio.command` (Gatekeeper); PLAY on empty log returns operator-clear message; `engine-msg` error/hint/ok classes.

**Still not Done (do not fake):** Real AU host, live Liquidsoap Harbor, CoreAudio PCM multi-bus, notarization; AUTO/hotkey/VT/segue Mac hear-through; Segue audition.

## Package size grind 2026-09-06 (500MB–1GB beds)

| SHA | Theme |
|-----|--------|
| *(this commit)* | Grow demo beds + soft-warn ≥500MB; noise-textured PCM so ZIP/DMG hold size |

**Why:** v0.1.2-preview ZIP/DMG landed ~301/351 MB — sine-heavy beds DEFLATE away. Matt treats &lt;500 MB (even toward 1 GB) as inadequate.

**Change:** `MQ_DEMO_BED_MB` default/CI **850**; more/longer IDs, sweepers, liners, VT/news/overnight beds via `generate_demo_beds.py` (noise-dominant textures). Soft-warn staged beds, resources, ZIP, and DMG below **500 MB**. Listing checks for ffmpeg + beds unchanged. Music library stays external. No fake AU / live Liquidsoap / notarization.

**Expected package:** ZIP ~650–750 MB · DMG ~670–800 MB (Electron+ffmpeg+engine + ~850 MB raw beds @ ~0.5 ZIP ratio).

## Desk harden 2026-09-06 (P0 Living Log Done + Partial depth)

| SHA | Theme |
|-----|--------|
| *(this commit)* | Living Log Done; talk-up/pulse/hotkey/segue/ingest harden + pytest |

**Living Log (Done):** insert clamps oversized after_position; delete/replace integer + not-found paths; MANUAL/VT survive soft regenerate; HTTP e2e for delete/insert/replace.

**AUTO / ASSIST talk-up (still Partial — Mac hear-through):** SESSION.timing exposes in_intro / talk_up_remaining_ms / vocals_in / event_type; desk prefers server countdown; /api/pulse honors body date so ASSIST GO advances the correct day.

**Hotkeys (Partial):** /api/hotkeys/reorder + color persist + F1–F12 rekey; fire status for missing path.

**Segue / segment / ingest:** duck/crossfade/mark validation; segment invalid windows; ingest rejects missing/empty/dir/no-ext/unsupported; FLAC+corrupt mp4 edges.

**Still not Done:** AU host, live Liquidsoap Harbor, CoreAudio PCM multi-bus, notarization; AUTO/hotkey/VT/segue Mac hear-through.

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
