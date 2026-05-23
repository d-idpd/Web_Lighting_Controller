"""
Split combined kitchen mask images into per-zone mask files.

Your source masks (LeftMask.png / RightMask.png) show all three LED zones
in a single image. This script finds the three brightness bands automatically
and exports:

    static/images/left-mask-top.png
    static/images/left-mask-mid.png
    static/images/left-mask-bot.png
    static/images/right-mask-top.png
    static/images/right-mask-mid.png
    static/images/right-mask-bot.png

It also copies your base photos as:
    static/images/left-base.png
    static/images/right-base.png

Usage:
    python split_masks.py                       (uses default source paths)
    python split_masks.py --left ../LeftMask.png --right ../RightMask.png

Source images are looked for in this order:
  1. Paths passed via --left / --right flags
  2. ../LeftMask.png and ../RightMask.png  (sibling of sp110e-controller/)
  3. ./LeftMask.png and ./RightMask.png    (current directory)

Requires: pip install Pillow
"""

import argparse
import os
import shutil
from pathlib import Path

try:
    from PIL import Image
    import numpy as np
except ImportError:
    print("ERROR: Pillow and numpy are required. Run: pip install Pillow numpy")
    raise SystemExit(1)

OUT_DIR = Path(__file__).parent / "static" / "images"

CANDIDATES = [
    (Path(__file__).parent.parent / "LeftMask.png",
     Path(__file__).parent.parent / "RightMask.png",
     Path(__file__).parent.parent / "LeftBase.png",
     Path(__file__).parent.parent / "RightBase.png"),
    (Path("LeftMask.png"), Path("RightMask.png"),
     Path("LeftBase.png"), Path("RightBase.png")),
]


def find_brightness_bands(gray_array: np.ndarray, n_bands: int = 3,
                           threshold: int = 20) -> list[tuple[int, int]]:
    """
    Find N horizontal bands of brightness in a grayscale image array.
    Returns a list of (row_start, row_end) tuples sorted top-to-bottom.
    """
    row_brightness = gray_array.mean(axis=1)
    lit_rows = np.where(row_brightness > threshold)[0]

    if len(lit_rows) == 0:
        raise ValueError("No bright pixels found — is the mask correct?")

    # Split into contiguous runs of lit rows
    runs: list[list[int]] = []
    current_run: list[int] = [lit_rows[0]]
    for r in lit_rows[1:]:
        if r - current_run[-1] <= 5:  # allow up to 5-row dark gap within a band
            current_run.append(r)
        else:
            runs.append(current_run)
            current_run = [r]
    runs.append(current_run)

    # Keep only the N largest runs
    runs.sort(key=lambda x: len(x), reverse=True)
    top_n = sorted(runs[:n_bands], key=lambda x: x[0])  # sort top-to-bottom

    bands = [(r[0], r[-1]) for r in top_n]
    return bands


def split_mask(src: Path, side: str) -> None:
    print(f"\nProcessing {src.name} → {side} zone masks")
    img = Image.open(src).convert("L")  # grayscale
    arr = np.array(img)

    try:
        bands = find_brightness_bands(arr)
    except ValueError as e:
        print(f"  ERROR: {e}")
        return

    zone_names = ["top", "mid", "bot"]
    for (row_start, row_end), zone in zip(bands, zone_names):
        # Create a black canvas same size as the source
        zone_arr = np.zeros_like(arr)
        # Copy only the rows belonging to this zone
        zone_arr[row_start:row_end + 1, :] = arr[row_start:row_end + 1, :]
        zone_img = Image.fromarray(zone_arr, mode="L")
        out_path = OUT_DIR / f"{side}-mask-{zone}.png"
        zone_img.save(out_path)
        print(f"  Saved {out_path.name}  (rows {row_start}–{row_end})")


def copy_base(src: Path, side: str) -> None:
    if not src.exists():
        print(f"  Base image not found: {src} — skipping")
        return
    dest = OUT_DIR / f"{side}-base.png"
    shutil.copy2(src, dest)
    print(f"  Copied base → {dest.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Split kitchen masks into zone masks")
    parser.add_argument("--left",  help="Path to LeftMask.png")
    parser.add_argument("--right", help="Path to RightMask.png")
    parser.add_argument("--left-base",  help="Path to LeftBase.png")
    parser.add_argument("--right-base", help="Path to RightBase.png")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Resolve mask paths
    if args.left and args.right:
        left_mask = Path(args.left)
        right_mask = Path(args.right)
        left_base = Path(args.left_base) if args.left_base else left_mask.parent / "LeftBase.png"
        right_base = Path(args.right_base) if args.right_base else right_mask.parent / "RightBase.png"
    else:
        left_mask = right_mask = left_base = right_base = None
        for lm, rm, lb, rb in CANDIDATES:
            if lm.exists() and rm.exists():
                left_mask, right_mask, left_base, right_base = lm, rm, lb, rb
                break

    if left_mask is None or not left_mask.exists():
        print("ERROR: Could not find LeftMask.png. Use --left <path>")
        raise SystemExit(1)
    if right_mask is None or not right_mask.exists():
        print("ERROR: Could not find RightMask.png. Use --right <path>")
        raise SystemExit(1)

    print(f"Output directory: {OUT_DIR}")

    split_mask(left_mask, "left")
    copy_base(left_base, "left")

    split_mask(right_mask, "right")
    copy_base(right_base, "right")

    print("\nDone. Zone masks written to static/images/")
    print("Review them and re-run with adjusted --threshold if any zone is missing or merged.")


if __name__ == "__main__":
    main()
