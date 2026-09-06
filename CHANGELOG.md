# Changelog — MQ Radio Automation

Lean build log for Matt. SHAs are on `main` (`MQDIGITALRADIO/MQ_Grok_Build`).

## Away session 2026-09-06 (continued)

| SHA | Theme |
|-----|--------|
| *(this commit)* | Multi-bus CoreAudio/mock router + AU insert architecture stub |
| `dc26a8b` | Program CoreAudio / mock audio output router + `/api/status` `audio_route` |
| `3464662` | Real Mac CoreAudio device enum bridge + Settings wire-up |

**Multi-bus routing:** `audio_router` treats **Program as primary** and opens best-effort CoreAudio/PortAudio streams for Headphones, Aux, **Monitor, Mix-minus, Stream, Record** when `sounddevice` resolves devices (Mac). Linux/CI mock records all buses in status. Mix-minus status: `{out, aux_in, paired}` (Aux-in pairing; DSP subtract later).

**AU insert architecture (not a host):** Program path documented as `source → [AU insert if set] → native processing → device`. Selected AU **name** persists in Settings. Without an AU host, `audio_route.au_insert.warning = au_insert_inactive` and **native still runs**. Electron note for a future host in `desktop/main.js`.

### Still deferred (not DMG-bar met)
- Real **AU/AAX hosting** (plugins not loaded — architecture + warning only)
- Transmission-path **DSP** beyond Web Audio approx + Liquidsoap handoff stub
- Mix-minus **DSP subtraction** (pairing recorded only)

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
- Transmission-path **DSP** beyond Web Audio approx + Liquidsoap handoff stub
- Opening CoreAudio **streams** to selected devices (enumeration ≠ routing)

Do **not** treat the unsigned/ad-hoc Mac DMG as broadcast-ready until AU host + transmission DSP bar is closed.
