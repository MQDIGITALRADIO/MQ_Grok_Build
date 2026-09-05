"""Voice tracker + AI announcer (M2) — scripts & log placement; no TTS yet."""

from mq_radio.voice_tracker.inserter import generate_ai_breaks
from mq_radio.voice_tracker.script_generator import (
    VARIATIONS,
    choose_variation,
    daypart_for_hour,
    generate_script,
)
from mq_radio.voice_tracker.service import (
    approve_ai_breaks,
    attach_vt_to_events,
    list_vt,
    script_for_transition,
)

STUB = False

__all__ = [
    "VARIATIONS",
    "STUB",
    "approve_ai_breaks",
    "attach_vt_to_events",
    "choose_variation",
    "daypart_for_hour",
    "generate_ai_breaks",
    "generate_script",
    "list_vt",
    "script_for_transition",
]
