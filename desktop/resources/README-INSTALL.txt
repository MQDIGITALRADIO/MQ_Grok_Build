MQ Radio — first-run install (Mac)
====================================

You downloaded an unsigned / ad-hoc signed CI build (market preview).
Apple Gatekeeper will block it until you clear quarantine once.
Apple Developer ID signing + notarization is still Missing (acceptance P2).

PREFERRED (easiest)
-------------------
1. Unzip the ZIP (recommended over DMG), or open the DMG.
2. Drag "MQ Radio.app" into Applications.
3. Double-click "Open MQ Radio.command" in the same folder as this README.
   - It clears quarantine (xattr), ad-hoc codesigns, then opens the app.
   - Safe to run again if macOS still complains.
4. If macOS still asks: right-click MQ Radio → Open → confirm Open.

If macOS says the app is "damaged"
----------------------------------
That usually means quarantine attributes — not a corrupt download.
Open Terminal and paste:

  xattr -cr "/Applications/MQ Radio.app"
  codesign --force --deep --sign - "/Applications/MQ Radio.app"

Then right-click → Open, or System Settings → Privacy & Security → Open Anyway.
Or just re-run Open MQ Radio.command.

Manual Gatekeeper (without the .command helper)
-----------------------------------------------
  xattr -cr "/Applications/MQ Radio.app"
  codesign --force --deep --sign - "/Applications/MQ Radio.app"
  open "/Applications/MQ Radio.app"

First launch
------------
- MQ Radio starts the On-Air engine at http://127.0.0.1:8080
- Station data: ~/Library/Application Support/MQ Radio/
- Empty Living Log / empty decks / empty cartwall are normal until you import + generate
- Drop .wav / .mp3 / .flac / .mp4 (or Import audio) to build a library
- Clocks → Generate hour (or Sample hour) fills the Living Log
- Settings → audio routes before going live, then PLAY
- If the desk says engine offline: run Open MQ Radio.command, reopen, Refresh
- Package substance (~637MB class): bundled ffmpeg + demo beds + Master Control
  templates + engine (music library stays external on MQ Digital drive)

Master Control (Liquidsoap) — operator path only
------------------------------------------------
- Templates ship under Resources/master_control/liquidsoap/
- Settings → Master Control: Dry-run validate / Start(stub) / Stop(stub)
- Start fails clearly if liquidsoap is missing: brew install liquidsoap
- Live Harbor / Telnet graph is NOT wired — do not treat TX as live from the desk

Not yet broadcast-bar
---------------------
- Real AU/AAX plugin hosting (Settings banner; native chain still runs)
- Full Liquidsoap Master Control live Harbor graph
- Apple notarized DMG
- This build is a market preview for desk workflow + packaging

Need help: MQ DIGITAL RADIO / repo MQDIGITALRADIO/MQ_Grok_Build
