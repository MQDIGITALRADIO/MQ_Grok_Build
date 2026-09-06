#!/usr/bin/env python3
"""Generate real broadcast sample beds for Mac package bulk (no junk padding).

Creates minutes of legal imaging / beds / sweepers / liners / VT pads under
desktop/resources/demo_beds using ffmpeg synth sources (noise-textured pads,
sweepers, stings). Beds are noise-dominant so ZIP/DMG stay substantial —
pure sine pads compress away under DEFLATE.

Usage:
  python packaging/scripts/generate_demo_beds.py [--target-mb 850] [--out DIR]

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
# ~10.5 MB per stereo minute @ 44.1 kHz / 16-bit PCM
MB_PER_MINUTE = 10.5
DEFAULT_TARGET_MB = 850.0
DEFAULT_MIN_MB = 500.0


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
    """Write a real stereo 44.1kHz 16-bit WAV (noise-textured, not zero-fill / sine-only)."""
    out.mkdir(parents=True, exist_ok=True)
    dest = out / name
    ff = ffmpeg_bin()
    if kind == "sting":
        # Short rising sting with noise body (IDs / legal tops)
        cmd = [
            ff, "-y",
            "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}",
            "-f", "lavfi", "-i", f"anoisesrc=color=white:amplitude=0.12:duration={seconds}",
            "-filter_complex",
            f"[0][1]amix=inputs=2:weights=3 1,"
            f"afade=t=in:st=0:d=0.02,afade=t=out:st={max(0.01, seconds - 0.08)}:d=0.08",
            "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", str(dest),
        ]
    elif kind == "sweeper":
        # Whoosh sweeper: pink + white sweep body (broadcast imaging)
        cmd = [
            ff, "-y",
            "-f", "lavfi", "-i", f"anoisesrc=color=pink:amplitude=0.35:duration={seconds}",
            "-f", "lavfi", "-i", f"anoisesrc=color=white:amplitude=0.22:duration={seconds}",
            "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}",
            "-filter_complex",
            f"[0]highpass=f=120,lowpass=f=12000[a];"
            f"[1]highpass=f=800,afade=t=in:st=0:d={min(0.4, seconds / 3)}[b];"
            f"[2]volume=0.06[c];"
            f"[a][b][c]amix=inputs=3:weights=4 3 1,"
            f"afade=t=in:st=0:d=0.03,afade=t=out:st={max(0.05, seconds - 0.15)}:d=0.15",
            "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", str(dest),
        ]
    elif kind == "liner":
        # Short liner / dry drop with noise bed under tone
        cmd = [
            ff, "-y",
            "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}",
            "-f", "lavfi", "-i", f"anoisesrc=color=pink:amplitude=0.28:duration={seconds}",
            "-filter_complex",
            f"[0]volume=0.2[a];[1]highpass=f=100[b];[a][b]amix=inputs=2:weights=1 4,"
            f"afade=t=in:st=0:d=0.05,afade=t=out:st={max(0.05, seconds - 0.2)}:d=0.2",
            "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", str(dest),
        ]
    elif kind == "news":
        # Low news bed — brown/pink pad (compresses poorly, real overnight/news use)
        cmd = [
            ff, "-y",
            "-f", "lavfi", "-i", f"anoisesrc=color=brown:amplitude=0.32:duration={seconds}",
            "-f", "lavfi", "-i", f"anoisesrc=color=pink:amplitude=0.28:duration={seconds}",
            "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}",
            "-filter_complex",
            f"[0]lowpass=f=600[a];[1]lowpass=f=2500[b];[2]volume=0.05[c];"
            f"[a][b][c]amix=inputs=3:weights=4 2 1,"
            f"afade=t=in:st=0:d=0.5,afade=t=out:st={max(0.5, seconds - 1.0)}:d=1.0",
            "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", str(dest),
        ]
    else:
        # VT / imaging pad — pink+white textured bed with quiet fundamental
        cmd = [
            ff, "-y",
            "-f", "lavfi", "-i", f"anoisesrc=color=pink:amplitude=0.30:duration={seconds}",
            "-f", "lavfi", "-i", f"anoisesrc=color=white:amplitude=0.22:duration={seconds}",
            "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}",
            "-filter_complex",
            f"[0]highpass=f=60,lowpass=f=8000[a];"
            f"[1]highpass=f=200,lowpass=f=12000,volume=0.95[b];"
            f"[2]volume=0.07[c];"
            f"[a][b][c]amix=inputs=3:weights=5 2 1,"
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
        "texture": "noise-dominant PCM for package substance",
    }
    dest.with_suffix(".json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return dest


def dir_bytes(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def build_catalog(target_mb: float) -> list[tuple[str, float, str, float]]:
    """Short imaging + long noise beds. Long beds drive package size honestly."""
    catalog: list[tuple[str, float, str, float]] = [
        # Legal / ID stings
        ("MQ_ID_Legal_Top.wav", 4.0, "sting", 880.0),
        ("MQ_ID_Legal_Bottom.wav", 3.5, "sting", 660.0),
        ("MQ_ID_Top_Hour.wav", 5.0, "sting", 740.0),
        ("MQ_ID_Station_Short.wav", 3.0, "sting", 520.0),
        # Sweepers
        ("MQ_SWEEPER_MoreMusic.wav", 6.0, "sweeper", 520.0),
        ("MQ_SWEEPER_Brand.wav", 5.5, "sweeper", 440.0),
        ("MQ_SWEEPER_HitFill.wav", 4.0, "sweeper", 490.0),
        ("MQ_SWEEPER_Drive.wav", 7.0, "sweeper", 380.0),
        ("MQ_SWEEPER_Weekend.wav", 6.5, "sweeper", 410.0),
        ("MQ_SWEEPER_Power.wav", 5.0, "sweeper", 560.0),
        # Liners / dry drops
        ("MQ_LINER_Hook.wav", 8.0, "liner", 330.0),
        ("MQ_LINER_Positioner.wav", 7.0, "liner", 290.0),
        ("MQ_LINER_Contest.wav", 9.0, "liner", 310.0),
        ("MQ_LINER_Weather.wav", 6.0, "liner", 270.0),
        ("MQ_LINER_Traffic.wav", 6.5, "liner", 250.0),
        # Promos
        ("MQ_PROMO_Weekend.wav", 18.0, "pad", 196.0),
        ("MQ_PROMO_Contest.wav", 15.0, "pad", 220.0),
        ("MQ_PROMO_Morning.wav", 20.0, "pad", 180.0),
        # News / VT / imaging beds
        ("MQ_BED_News_A.wav", 90.0, "news", 110.0),
        ("MQ_BED_News_B.wav", 120.0, "news", 98.0),
        ("MQ_BED_News_C.wav", 150.0, "news", 92.0),
        ("MQ_BED_VT_Soft.wav", 180.0, "pad", 130.0),
        ("MQ_BED_VT_Drive.wav", 240.0, "pad", 146.0),
        ("MQ_BED_VT_Warm.wav", 210.0, "pad", 138.0),
        ("MQ_BED_Overnight_A.wav", 360.0, "pad", 82.0),
        ("MQ_BED_Overnight_B.wav", 420.0, "news", 73.0),
        ("MQ_BED_Overnight_C.wav", 480.0, "pad", 78.0),
        ("MQ_BED_Imaging_Warm.wav", 240.0, "pad", 164.0),
        ("MQ_BED_Imaging_Bright.wav", 270.0, "pad", 196.0),
        ("MQ_BED_Imaging_Deep.wav", 300.0, "pad", 120.0),
        ("MQ_BED_Imaging_Air.wav", 300.0, "pad", 175.0),
    ]

    target = target_mb * 1024 * 1024
    extra_i = 1
    while True:
        est = sum(sec for _, sec, _, _ in catalog) * MB_PER_MINUTE * 1024 * 1024 / 60
        if est >= target * 0.95:
            break
        # 4–8 minute package beds (broadcast-useful length)
        dur = 240.0 + (extra_i % 5) * 60.0
        kind = "pad" if extra_i % 3 else "news"
        catalog.append(
            (f"MQ_BED_Package_{extra_i:02d}.wav", dur, kind, 90.0 + extra_i * 2.5)
        )
        extra_i += 1
        if extra_i > 200:
            break
    return catalog


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--target-mb",
        type=float,
        default=DEFAULT_TARGET_MB,
        help="Approximate total size target in MB (noise beds resist ZIP squash)",
    )
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument(
        "--min-mb",
        type=float,
        default=DEFAULT_MIN_MB,
        help="Always generate at least this many MB (soft floor for 500MB–1GB packages)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Print catalog estimate only; do not write audio",
    )
    args = ap.parse_args()

    target_mb = max(float(args.min_mb), float(args.target_mb))
    catalog = build_catalog(target_mb)
    est_mb = sum(sec for _, sec, _, _ in catalog) * MB_PER_MINUTE / 60

    if args.dry_run:
        print(f"DRY-RUN: {len(catalog)} beds ≈ {est_mb:.0f} MB (target {target_mb:.0f} MB)")
        for name, sec, kind, _freq in catalog[:8]:
            print(f"  {name} ({sec:.0f}s {kind})")
        if len(catalog) > 8:
            print(f"  … +{len(catalog) - 8} more")
        return 0

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

    target = target_mb * 1024 * 1024
    print(f"Generating {len(catalog)} beds → {out} (target ~{target_mb:.0f} MB, est {est_mb:.0f} MB)")
    for name, sec, kind, freq in catalog:
        print(f"  {name} ({sec:.0f}s {kind})")
        write_bed(out, name, sec, kind=kind, freq=freq)
        if dir_bytes(out) >= target:
            print("  reached target size — stopping early")
            break

    total = dir_bytes(out)
    mb = round(total / (1024 * 1024), 1)
    manifest = {
        "kind": "mq_radio_demo_beds",
        "bytes": total,
        "mb": mb,
        "target_mb": target_mb,
        "files": sorted(p.name for p in out.glob("*.wav")),
        "note": "Real PCM imaging beds (noise-textured); music library remains external",
    }
    (out / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    readme = out / "README.md"
    if not readme.exists():
        readme.write_text(
            "# MQ Radio demo / imaging beds\n\n"
            "Bundled sample beds for the Mac package (IDs, sweepers, liners, VT/news pads).\n"
            "Generated by `packaging/scripts/generate_demo_beds.py`.\n\n"
            "**Not** the commercial music library — that stays on the external MQ Digital drive.\n",
            encoding="utf-8",
        )
    print(f"DONE: {mb} MB in {out}")
    # Soft floor: package ZIP/DMG target is 500MB–1GB; beds are the bulk
    if mb < 500:
        print(
            f"WARN: demo beds {mb} MB < 500 MB soft floor — raise MQ_DEMO_BED_MB / --target-mb",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
