"""Broadcast timing / chain / event type enumerations."""

from enum import Enum


class EventType(str, Enum):
    MUSIC = "MUSIC"
    SWEEPER = "SWEEPER"
    ID = "ID"
    PROMO = "PROMO"
    VOICE_TRACK = "VOICE_TRACK"
    BED = "BED"
    SHOW = "SHOW"
    LIVE = "LIVE"
    COMMAND = "COMMAND"
    ETM = "ETM"
    BREAK = "BREAK"
    FILLER = "FILLER"


class ChainMode(str, Enum):
    """How the engine advances from one log event to the next."""

    AUTO = "AUTO"  # seamless segue when previous ends
    MIX = "MIX"  # overlap / crossfade
    CUT = "CUT"  # hard cut at end
    MANUAL = "MANUAL"  # wait for operator
    HOLD = "HOLD"  # hold until released


class TimingMode(str, Enum):
    """How a slot / event relates to wall-clock time."""

    FLOAT = "FLOAT"  # soft schedule, can drift
    SOFT = "SOFT"  # prefer airtime, tolerate small drift
    HARD = "HARD"  # must hit airtime
    RESET = "RESET"  # hard reset to clock at this point
    HIT = "HIT"  # hit exact time (ETM-style)
    TIME_WINDOW = "TIME_WINDOW"  # must air within window


class LogStatus(str, Enum):
    DRAFT = "DRAFT"
    COMMITTED = "COMMITTED"
    ON_AIR = "ON_AIR"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


class ManualFlag(str, Enum):
    AUTO = "AUTO"
    MANUAL = "MANUAL"  # preserved on regenerate unless --force
