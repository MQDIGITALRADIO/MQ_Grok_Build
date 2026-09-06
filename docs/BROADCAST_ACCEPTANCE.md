# MQ Radio — Broadcast acceptance checklist (paying-client bar)

Cross-check vs Maestro / early Zetta / Netia Radio-Assist / mAirList / StationPlaylist / WideOrbit-class desks.
**Rule:** no stub counts as done. Function + clear hybrid Maestro clarity + Netia landscape UI.
**Triple-check:** each item must pass manual verify + automated test where possible.

## P0 — Must work now (Matt-reported + on-air trust)
- [ ] Import audio (wav/mp3/flac/mp4) via DROP + Browse — library cart created, visible in LIBRARY
- [ ] VU / LEDs dark when idle; only move when actually PLAY / ON AIR with audio
- [ ] Every control has clear English label (PLAY STOP SKIP NEXT, Import audio, Library, Clocks, Settings…)
- [ ] Hybrid UI: Maestro-clear transport/log/decks + modern Netia-landscape shell (not Win95 beige)
- [ ] PLAY plays an ingested cart through Program path with audible output (web + Mac app)
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
