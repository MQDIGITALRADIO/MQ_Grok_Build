MQ Radio — first-run install (Mac)
====================================

You downloaded an unsigned / ad-hoc signed CI build (market preview).
Apple Gatekeeper will block it until you clear quarantine once.

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
Open Terminal and paste:

  xattr -cr "/Applications/MQ Radio.app"
  codesign --force --deep --sign - "/Applications/MQ Radio.app"

Then right-click → Open, or System Settings → Privacy & Security → Open Anyway.

Manual Gatekeeper (without the .command helper)
-----------------------------------------------
  xattr -cr "/Applications/MQ Radio.app"
  codesign --force --deep --sign - "/Applications/MQ Radio.app"
  open "/Applications/MQ Radio.app"

Apple Developer ID signing comes later — until then this helper is normal.

First launch
------------
- MQ Radio starts the On-Air engine at http://127.0.0.1:8080
- Station data: ~/Library/Application Support/MQ Radio/
- Drop .wav / .mp3 / .flac / .mp4 onto the desk to build a library
- Settings ⚙ → audio routes + FM/Digital processing
- Clocks / Library buttons build the Living Log

Not yet broadcast-bar
---------------------
- Real AU/AAX plugin hosting (Settings shows banner; native chain still runs)
- Full Liquidsoap Master Control graph (handoff stub ships; install Liquidsoap separately — see packaging/liquidsoap/README.md)
- This build is a market preview for desk workflow + packaging

Need help: MQ DIGITAL RADIO / repo MQDIGITALRADIO/MQ_Grok_Build
