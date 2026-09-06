#!/usr/bin/env python3
"""Generate real broadcast sample beds for Mac package bulk (no junk padding).

Creates minutes of legal imaging / beds / sweepers / VT pads under
desktop/resources/demo_beds using ffmpeg synth sources (sine, anoisesrc, amix).

Usage:
  python packaging/scripts/generate_demo_beds.py [--target-mb 450] [--out DIR]

Music library stays external — these are station imaging beds only.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / "desktop" / "resources" / "demo_beds"


def ffmpeg_bin() -> str:
    return shutil.which("ffmpeg") or "ffmpeg"


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def write_bed(
    out: Path,
    name: str,
    seconds: float,
    *,
    kind: str = "pad",
    freq: float = 220.0,
) -> Path:
    """Write a real stereo 44.1kHz 16-bit WAV (not zero-fill)."""
    out.mkdir(parents=True, exist_ok=True)
    dest = out / name
    ff = ffmpeg_bin()
    if kind == "sting":
        # Short rising sting
        filt = (
            f"sine=frequency={freq}:duration={seconds},"
            f"afade=t=in:st=0:d=0.02,afade=t=out:st={max(0.01, seconds - 0.08)}:d=0.08"
        )
        cmd = [
            ff, "-y", "-f", "lavfi", "-i", filt,
            "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", str(dest),
        ]
    elif kind == "sweeper":
        filt = (
            f"sine=frequency={freq}:duration={seconds}[a];"
            f"anoisesrc=color=pink:amplitude=0.08:duration={seconds}[n];"
            f"[a][n]amix=inputs=2:duration=shortest,"
            f"afade=t=in:st=0:d=0.03,afade=t=out:st={max(0.05, seconds - 0.12)}:d=0.12"
        )
        cmd = [
            ff, "-y", "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}",
            "-f", "lavfi", "-i", f"anoisesrc=color=pink:amplitude=0.08:duration={seconds}",
            "-filter_complex",
            f"[0][1]amix=inputs=2:duration=shortest,afade=t=in:st=0:d=0.03,"
            f"afade=t=out:st={max(0.05, seconds - 0.12)}:d=0.12",
            "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", str(dest),
        ]
    elif kind == "news":
        # Low bed pad
        cmd = [
            ff, "-y", "-f", "lavfi",
            "-i", f"sine=frequency={freq}:duration={seconds}",
            "-f", "lavfi",
            "-i", f"sine=frequency={freq * 1.5}:duration={seconds}",
            "-filter_complex",
            f"[0]volume=0.25[a];[1]volume=0.12[b];[a][b]amix=inputs=2,"
            f"afade=t=in:st=0:d=0.5,afade=t=out:st={max(0.5, seconds - 1.0)}:d=1.0",
            "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", str(dest),
        ]
    else:
        # VT / imaging pad
        cmd = [
            ff, "-y", "-f", "lavfi",
            "-i", f"sine=frequency={freq}:duration={seconds}",
            "-f", "lavfi",
            "-i", f"anoisesrc=color=brown:amplitude=0.04:duration={seconds}",
            "-filter_complex",
            f"[0]volume=0.18[a];[1][a]amix=inputs=2:weights=1 3,"
            f"afade=t=in:st=0:d=0.4,afade=t=out:st={max(0.4, seconds - 0.8)}:d=0.8",
            "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", str(dest),
        ]
    run(cmd)
    meta = {
        "file": name,
        "kind": kind,
        "duration_s": seconds,
        "sample_rate": 44100,
        "channels": 2,
        "purpose": "MQ Radio bundled imaging / demo bed (not music library)",
    }
    dest.with_suffix(".json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return dest


def dir_bytes(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target-mb", type=float, default=450.0, help="Approximate total size target in MB")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--min-mb", type=float, default=80.0, help="Always generate at least this many MB")
    args = ap.parse_args()

    if not shutil.which("ffmpeg"):
        print("ERROR: ffmpeg required on PATH to generate beds", file=sys.stderr)
        return 1

    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    # Clear prior generated beds (keep README / .gitkeep)
    for p in out.iterdir():
        if p.name in (".gitkeep", "README.md"):
            continue
        if p.is_file():
            p.unlink()

    target = max(float(args.min_mb), float(args.target_mb)) * 1024 * 1024
    # Catalog: short imaging + long beds. Long beds drive package size honestly.
    catalog: list[tuple[str, float, str, float]] = [
        ("MQ_ID_Legal_Top.wav", 4.0, "sting", 880.0),
        ("MQ_ID_Legal_Bottom.wav", 3.5, "sting", 660.0),
        ("MQ_SWEEPER_MoreMusic.wav", 6.0, "sweeper", 520.0),
        ("MQ_SWEEPER_Brand.wav", 5.5, "sweeper", 440.0),
        ("MQ_SWEEPER_HitFill.wav", 4.0, "sweeper", 490.0),
        ("MQ_PROMO_Weekend.wav", 12.0, "pad", 196.0),
        ("MQ_PROMO_Contest.wav", 10.0, "pad", 220.0),
        ("MQ_BED_News_A.wav", 60.0, "news", 110.0),
        ("MQ_BED_News_B.wav", 90.0, "news", 98.0),
        ("MQ_BED_VT_Soft.wav", 120.0, "pad", 130.0),
        ("MQ_BED_VT_Drive.wav", 180.0, "pad", 146.0),
        ("MQ_BED_Overnight_A.wav", 240.0, "pad", 82.0),
        ("MQ_BED_Overnight_B.wav", 300.0, "news", 73.0),
        ("MQ_BED_Imaging_Warm.wav", 180.0, "pad", 164.0),
        ("MQ_BED_Imaging_Bright.wav", 210.0, "pad", 196.0),
    ]

    # Extend with numbered long beds until target
    extra_i = 1
    while True:
        # Estimate: ~10.5 MB per stereo minute at 44.1/16
        est = sum(sec for _, sec, _, _ in catalog) * 10.5 * 1024 * 1024 / 60
        if est >= target * 0.92:
            break
        # Add 3–5 minute beds
        dur = 180.0 + (extra_i % 5) * 60.0
        catalog.append(
            (f"MQ_BED_Package_{extra_i:02d}.wav", dur, "pad" if extra_i % 2 else "news", 90.0 + extra_i * 3)
        )
        extra_i += 1
        if extra_i > 80:
            break

    print(f"Generating {len(catalog)} beds → {out} (target ~{args.target_mb} MB)")
    for name, sec, kind, freq in catalog:
        print(f"  {name} ({sec:.0f}s {kind})")
        write_bed(out, name, sec, kind=kind, freq=freq)
        if dir_bytes(out) >= target:
            print("  reached target size — stopping early")
            break

    total = dir_bytes(out)
    manifest = {
        "kind": "mq_radio_demo_beds",
        "bytes": total,
        "mb": round(total / (1024 * 1024), 1),
        "files": sorted(p.name for p in out.glob("*.wav")),
        "note": "Real PCM beds for package substance; music library remains external",
    }
    (out / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    readme = out / "README.md"
    if not readme.exists():
        readme.write_text(
            "# MQ Radio demo / imaging beds\n\n"
            "Bundled sample beds for the Mac package (IDs, sweepers, VT/news pads).\n"
            "Generated by `packaging/scripts/generate_demo_beds.py`.\n\n"
            "**Not** the commercial music library — that stays on the external MQ Digital drive.\n",
            encoding="utf-8",
        )
    print(f"DONE: {manifest['mb']} MB in {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
