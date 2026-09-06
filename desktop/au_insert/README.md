# Program AU insert — Electron / native host (future)

> **Status:** architecture + Settings persistence only.  
> **Not** a working Audio Unit host. Do **not** claim the DMG bar met.

## Program path

```
source → [AU insert if set] → native processing → device
```

When Settings selects an AU (`insert.slot` like `au:aufx:dely:appl`) and no host
is loaded, the engine sets:

- `audio_route.au_insert.warning = "au_insert_inactive"`
- `audio_route.au_insert.operator_message = "native chain active — AU host not loaded"`
- **Native** MQ chain (AGC→EQ→Multiband→Exciter→Limiter) **still runs**

Plugins are **never** silently bypassed as if they processed audio.

## Python contract (shipped)

See `mq_radio/engine/au_insert.py`:

```python
from mq_radio.engine.au_insert import load, host_available, AuHostNotAvailable

ins = load("AUDelay", slot="au:aufx:dely:appl")
assert host_available() is False
ins.process(pcm_buffer)  # raises AuHostNotAvailable
```

Optional `probe_pyobjc()` reports whether AudioUnit/AudioToolbox/AVFAudio
imports on Mac CI — diagnostic only; it does not open a render graph.

## Strongest practical next steps (Mac)

Depth over speed — pick **one** real path; do not fake DSP in Python alone.

### A. Electron native addon (recommended for DMG)

1. Add a Node-API / `node-addon-api` addon under this folder (e.g. `au_host.cc`).
2. Host a single effect AU via `AVAudioEngine` + `AVAudioUnit` (or AUGraph / `AudioUnitSetProperty` render callback).
3. Expose IPC from `desktop/main.js`:
   - `au:list` → names (or reuse engine `auval` list)
   - `au:load(slot)` / `au:unload`
   - `au:process` is **wrong** for realtime — prefer an in-graph tap on the Program bus
4. Flip engine `host_available` only when the addon reports a loaded unit **and** the Program graph is actually routed through it.
5. Package the `.node` binary into the Mac DMG / `extraResources`.

Realtime audio must stay on the Core Audio render thread (C/C++/ObjC++). Do not
process AU PCM in the Python GIL or Electron main process.

### B. Python helper via pyobjc (research / CI probe)

`pyobjc` can import AudioUnit frameworks for **enumeration and experiments**, but
a production Program-bus host wants a compiled render callback (ctypes/`CFUNCTYPE`
or a small ObjC++ helper), not pure Python in the realtime path. Use pyobjc to:

- Confirm frameworks on Mac CI (`probe_pyobjc()`)
- Prototype offline offline bounce tests — **not** live On-Air

### C. External host bridge

Run a tiny Swift/ObjC helper that hosts the selected AU and exchanges audio over
a shared ring buffer / Mach port with the Electron Program path. Highest
isolation; more packaging work.

## What already works (honest)

| Piece | State |
|-------|--------|
| Settings insert slot + `auval` names | Yes (Mac enum) |
| Persist `insert.name` / `insert.slot` | Yes |
| `au_insert_inactive` warning + native still runs | Yes |
| Settings UX banner + docs link | Yes |
| `load` / `process` interface | Yes (raises) |
| Real plugin DSP on Program bus | **No** |

## Settings UX copy

When an AU is selected and the host is down, Operators see:

**Native chain active — AU host not loaded** (plus selected slot/name when known)

Status also exposes `unavailable_reason` (`au_host_not_loaded` / `au_unavailable_platform`) and `unavailable_message`. `process()` / `process_buffer()` always raise — never silent passthrough.

with a link back to this README.
