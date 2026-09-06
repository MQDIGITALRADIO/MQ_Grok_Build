# MQ Radio — Liquidsoap processing handoff stub
# Template: FM | Topology: AGC → EQ → Multiband → Exciter → Limiter
# STATUS: stub — wire real operators in Mac/Liquidsoap milestone.
# NOT an Optimod clone. Params mirror data/processing.json / native desk.
#
# Suggested program chain (pseudo / documented):
#   program = input  # harbor / playlist / request.queue
#   program = mq_agc(program, ...)
#   program = mq_eq(program, ...)
#   program = mq_multiband(program, ...)
#   program = mq_exciter(program, ...)
#   program = mq_limiter(program, ...)
#   output.icecast(%mp3, ... , program)  # or FM encoder path
#
# enabled=True  path=FM  preemphasis=True us=50
#
# AGC: target_db=-15.0 drive_db=7.0 attack_ms=50.0 release_ms=900.0 gate_db=-42.0 enabled=True
# EQ: low_shelf 120.0Hz/1.5dB · presence 3200.0Hz/1.5dB · air 10000.0Hz/0.75dB · high_cut 15000.0Hz
# Multiband: bands=4 crossovers_hz=[200.0, 800.0, 3200.0] drive_db=[3.5, 4.5, 4.0, 3.0] release_ms=[400.0, 250.0, 180.0, 120.0] couple=True
# Exciter: amount=0.3 harmonics=0.35 mix=0.22 enabled=True
# Limiter: ceiling_dbfs=-1.0 release_ms=35.0 lookahead_ms=3.0 isr=False enabled=True
#
# See packaging/liquidsoap/README.md and processing_handoff.json for full templates.
