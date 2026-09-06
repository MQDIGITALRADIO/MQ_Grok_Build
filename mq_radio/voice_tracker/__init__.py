"""Voice tracker + AI announcer (M2) — scripts, placeholder render, log placement.

Real Vocloner voice remains clipboard/open-URL (no public API). Placeholder
PCM keeps Living Log playable until Vocloner WAV is attached. AI upstairs only.
"""

from mq_radio.voice_tracker.inserter import generate_ai_breaks
from mq_radio.voice_tracker.placeholder_render import (
    PLACEHOLDER_SOURCE,
    render_placeholder_vt,
    render_placeholders_for_date,
    run_pd_assist_operator_path,
    write_placeholder_wav,
)
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
    "PLACEHOLDER_SOURCE",
    "approve_ai_breaks",
    "attach_vt_to_events",
    "choose_variation",
    "daypart_for_hour",
    "generate_ai_breaks",
    "generate_script",
    "list_vt",
    "render_placeholder_vt",
    "render_placeholders_for_date",
    "run_pd_assist_operator_path",
    "script_for_transition",
    "write_placeholder_wav",
]
