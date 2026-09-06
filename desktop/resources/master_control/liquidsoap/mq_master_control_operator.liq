# MQ Radio — Master Control operator sketch (Liquidsoap)
# Pair with processing_handoff.json (FM / Digital + transmission_mode).
# Install Liquidsoap on the TX Mac: brew install liquidsoap
# This file is bundled for operators — not auto-started by the desk.

# settings.init.allow_root.set(false)

# program = input.harbor("mq.program", port=8005, headers=[], buffer=0.5)
# aux = input.harbor("mq.aux", port=8006, headers=[], buffer=0.5)
# mix_minus = program  # minus aux when wired: program - aux

# Chain (public practice topology — not an Optimod clone):
# AGC → EQ → Multiband → Exciter → Peak Limiter
# See packaging/liquidsoap/mq_processing_stub.liq for param mirrors.

# output.icecast(%mp3, host="127.0.0.1", port=8000, password="hackme",
#   mount="mq-fm", program)
