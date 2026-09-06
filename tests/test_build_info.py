"""Build / version badge helpers."""

from mq_radio.web.build_info import DESKTOP_VERSION, build_sha, version_payload


def test_desktop_version_is_market_014():
    assert DESKTOP_VERSION == "0.1.4"


def test_build_sha_nonempty_short():
    sha = build_sha()
    assert isinstance(sha, str)
    assert 1 <= len(sha) <= 40
    assert " " not in sha


def test_version_payload_label():
    p = version_payload()
    assert p["version"] == "0.1.4"
    assert p["sha"]
    assert p["label"] == f"{p['version']} · {p['sha']}"
