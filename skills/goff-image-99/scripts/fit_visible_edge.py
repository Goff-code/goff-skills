"""Fit a complete object's visible colors against its measured backing in Normal mode.

Requires Pillow and NumPy. The supplied binary mask identifies visible samples owned
by this object with no higher layer contributing. Intrinsic coverage and all hidden
pixels are preserved. Output is a new candidate, never the whole-scene proof.
"""
import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from check_fidelity import ensure_same_encoding, load_rgba


def render(back, rgb, alpha):
    pixels = np.column_stack((rgb, alpha)).astype(np.uint8, copy=False)
    foreground = Image.fromarray(pixels[None, :, :])
    return np.asarray(Image.alpha_composite(back, foreground))[0]


def solve(backing, current, target):
    back = Image.fromarray(backing[None, :, :])
    existing = current[:, :3]
    alpha = current[:, 3]
    projected = render(back, existing, alpha)
    upward = projected[:, :3] < target[:, :3]
    # For each channel, find the closest color on the target quantization plateau.
    # Searching from above uses the last value at or below target.
    low = np.zeros(existing.shape, dtype=np.int16)
    high = np.full(existing.shape, 255, dtype=np.int16)
    for _ in range(8):
        mid = (low + high + (~upward)) // 2
        value = render(back, mid, alpha)[:, :3]
        take_upper = np.where(upward, value < target[:, :3], value <= target[:, :3])
        low = np.where(take_upper, np.minimum(high, mid + upward), low)
        high = np.where(take_upper, high, np.maximum(low, mid - (~upward)))
    proposed = np.where(projected[:, :3] == target[:, :3], existing, low).astype(np.uint8)
    actual = render(back, proposed, alpha)
    matches = (actual == target).all(axis=1)
    return proposed, matches


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('original', 'object', 'backing', 'visible_mask', 'output'):
        p.add_argument(name, type=Path)
    p.add_argument("--max-change", type=int, default=48, help="maximum per-channel shift from existing pigment (0..255)")
    args = p.parse_args()
    if not 0 <= args.max_change <= 255:
        p.error("--max-change must be between 0 and 255")
    if args.output.suffix.lower() != '.png' or args.output.exists():
        p.error('Use a new PNG output path')
    source, metadata = load_rgba(args.original)
    obj, obj_meta = load_rgba(args.object, require_png=True)
    backing, back_meta = load_rgba(args.backing, require_png=True)
    for m in (obj_meta, back_meta):
        ensure_same_encoding(metadata, m)
    with Image.open(args.visible_mask) as mask:
        if (mask.format != 'PNG' or mask.mode not in ('1', 'L') or mask.getexif().get(274, 1) != 1
                or getattr(mask, 'n_frames', 1) != 1 or 'transparency' in mask.info):
            p.error('Use an oriented, opaque, single grayscale PNG ownership mask')
        if len({im.size for im in (mask, obj, backing, source)}) != 1:
            p.error('All four inputs must have identical display dimensions')
        m = np.asarray(mask.convert('L'))
    if not np.isin(m, (0, 255)).all() or not m.any():
        p.error('Ownership must be binary with a nonempty white visible region')
    result = np.array(obj)
    original = np.asarray(source)
    under = np.asarray(backing)
    failed = solved = 0
    for y in range(0, result.shape[0], 32):
        region = slice(y, y + 32)
        band = result[region]
        selected = (m[region] == 255)
        failed += np.count_nonzero(selected & (band[:, :, 3] == 0))
        selected &= band[:, :, 3] > 0
        if not selected.any():
            continue
        target = original[region][selected]
        old = band[selected]
        colors, ok = solve(under[region][selected], old, target)
        ok &= np.abs(colors.astype(np.int16) - old[:, :3]).max(axis=1) <= args.max_change
        failed += np.count_nonzero(~ok)
        solved += np.count_nonzero(ok)
        old[ok, :3] = colors[ok]
        band[selected] = old
    opts = {}
    chunks = PngInfo()
    with Image.open(args.object) as im:
        for k in ('icc_profile', 'dpi'):
            if k in im.info:
                opts[k] = im.info[k]
        if 'srgb' in im.info and 'icc_profile' not in opts:
            chunks.add(b'sRGB', bytes([im.info['srgb']]))
        if 'gamma' in im.info:
            chunks.add(b'gAMA', round(im.info['gamma'] * 100000).to_bytes(4, 'big'))
        if 'chromaticity' in im.info:
            chunks.add(b'cHRM', b''.join(round(v * 100000).to_bytes(4, 'big') for v in im.info['chromaticity']))
    with args.output.open('xb') as f:
        Image.fromarray(result).save(f, 'PNG', pnginfo=chunks, **opts)
    print(f'Owned pixels exactly reproducible: {solved}; unresolved within coverage and color limits: {failed}')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
