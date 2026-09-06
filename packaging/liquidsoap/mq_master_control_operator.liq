# MQ Radio — Master Control operator sketch (Liquidsoap)
# Handoff version 3 — pair with processing_handoff.json
# STATUS: operator pack / dry-run target — NOT a live Harbor graph
# Install on the TX Mac: brew install liquidsoap && liquidsoap --version
# Desk keeps Living Log + On-Air; this script is for Master Control TX only.
# Do not claim live Harbor Done until LiquidsoapEngine wires Telnet/Harbor.

# --- Dry-run markers (parsed by mq_radio.production.master_control) ---
# MQ_RADIO_OPERATOR_PACK=1
# MQ_RADIO_HANDOFF_VERSION=3
# MQ_RADIO_LIVE_HARBOR=0
# MQ_RADIO_TOPOLOGY=AGC>EQ>Multiband>Exciter>Limiter

# settings.init.allow_root.set(false)

# --- Suggested Harbor inputs (wire when TX host is ready) ---
# program = input.harbor("mq.program", port=8005, headers=[], buffer=0.5)
# aux = input.harbor("mq.aux", port=8006, headers=[], buffer=0.5)
# mix_minus = program  # when wired: program - aux (polarity invert aux, sum)

# --- Processing chain (public practice — not an Optimod clone) ---
# Map stages from processing_handoff.json / template_fm.json / template_digital.json
# Honour transmission_mode (denser FM / cleaner Digital) and output.preemphasis.
# AGC → EQ → Multiband → Exciter → Peak Limiter
# See mq_processing_stub.liq for current param mirrors from the desk.

# program = compress(...)       # AGC
# program = eq(...)             # EQ
# program = compress.multiband(...)
# program = dry_wet(...)        # mild exciter
# program = limit(...)          # peak limiter
# # FM only: preemphasis(...)

# --- Outputs (examples — operator edits host/password/mount) ---
# output.icecast(%mp3, host="127.0.0.1", port=8000, password="hackme",
#   mount="mq-fm", program)
# output.ao(program)  # or CoreAudio soundcard sink on Mac

# --- Operator check ---
# liquidsoap --check mq_master_control_operator.liq
# (Expect warnings on commented-only sketches; use a filled .liq for --check green.)
