# Changelog — MQ Radio Automation

Lean build log for Matt. SHAs are on `main` (`MQDIGITALRADIO/MQ_Grok_Build`).

## Away session 2026-09-06 (continued)

| SHA | Theme |
|-----|--------|
| *(this commit)* | Real Mac CoreAudio device enum bridge + Settings wire-up |

**CoreAudio device enumeration:** Python engine lists real input/output names on macOS via `system_profiler SPAudioDataType` (optional `sounddevice` if installed). Linux/CI/web keep mock catalogue. API: `GET /api/audio/devices` → `{source: "coreaudio"|"mock", devices, input_devices, insert_options, …}`; Settings routing dropdowns populate from it. AU insert stays stub (`none` = native); on Mac, `auval -a` may append read-only AU names — hosting still deferred.

### Still deferred (not DMG-bar met)
- **AU/AAX hosting** (insert slot + optional name list only)
- Transmission-path **DSP** beyond Web Audio approx + Liquidsoap handoff stub
- Opening CoreAudio streams to selected devices (enum ≠ route)

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
