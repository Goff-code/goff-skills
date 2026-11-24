"""Check whether a previously occluded area actually gains visible content.

Compare two PNG proofs exported from the same reopened PSD. Both hide the
occluder. The first keeps the expected rear object visible; the second also
hides that object. Every specified ROI must independently meet the threshold.
"""

import argparse
import json
import math
from pathlib import Path
import sys

from PIL import Image, ImageChops, ImageCms

from check_fidelity import ensure_same_encoding, load_rgba, roi_box


def measure(exposed, without_object, box, delta, min_percent):
    left, top, right, bottom = box
    total = (right - left) * (bottom - top)
    qualifying = alpha_loss = 0
    largest = 0
    significant = [255 if v >= delta else 0 for v in range(256)]
    nonzero = [0] + [255] * 255
    for y in range(top, bottom, 192):
        band = left, y, right, min(bottom, y + 192)
        on = exposed.crop(band)
        off = without_object.crop(band)
        alpha_on, alpha_off = on.getchannel("A"), off.getchannel("A")
        lost = ImageChops.subtract(alpha_off, alpha_on).point(significant)
        alpha_loss += lost.histogram()[255]
        # Rendering on both extremes measures visible RGB contribution, including
        # black or white translucent paint. Hidden RGB bytes never produce evidence.
        peak = Image.new("L", on.size)
        for shade in ("black", "white"):
            card = Image.new("RGBA", on.size, shade)
            rgb_on = Image.alpha_composite(card, on).convert("RGB")
            rgb_off = Image.alpha_composite(card, off).convert("RGB")
            for channel in ImageChops.difference(rgb_on, rgb_off).split():
                peak = ImageChops.lighter(peak, channel)
        largest = max(largest, peak.getextrema()[1])
        eligible = ImageChops.subtract(alpha_on.point(nonzero), lost)
        qualifying += ImageChops.darker(peak.point(significant), eligible).histogram()[255]
    return {"box_xywh": [left, top, right - left, bottom - top], "pixels": total,
            "significant_revealed_pixels": qualifying, "significant_revealed_pct": 100 * qualifying / total,
            "unexpected_alpha_loss_pixels": alpha_loss, "peak_display_rgb_difference": largest,
            "passed": 100 * qualifying >= min_percent * total and alpha_loss == 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("exposed", type=Path, help="PNG with the occluder hidden; the rear object is enabled")
    parser.add_argument("without_object", type=Path, help="PNG with both the occluder and that rear object hidden")
    parser.add_argument("--roi", required=True, action="append", metavar="NAME:X,Y,W,H",
                        help="repeatable rectangle inside the originally occluded area; displayed pixel coordinates")
    parser.add_argument("--min-percent", required=True, type=float, help="minimum visibly changed percentage of each ROI (0 < value <= 100)")
    parser.add_argument("--min-delta", type=int, default=8, help="minimum RGB display difference (1..255, default 8)")
    parser.add_argument("--json", type=Path, help="also save the JSON printed to stdout")
    args = parser.parse_args()
    try:
        if not math.isfinite(args.min_percent) or not 0 < args.min_percent <= 100 or not 1 <= args.min_delta <= 255:
            raise ValueError("Require 0 < --min-percent <= 100 and 1 <= --min-delta <= 255")
        if args.exposed.samefile(args.without_object):
            raise ValueError("Use independently exported proof files for both states")
        if args.json and (args.json.suffix.lower() != ".json" or args.json.resolve() in
                          {args.exposed.resolve(), args.without_object.resolve()}):
            raise ValueError("Choose a separate .json output file")
        shown, shown_meta = load_rgba(args.exposed, require_png=True)
        hidden, hidden_meta = load_rgba(args.without_object, require_png=True)
        ensure_same_encoding(shown_meta, hidden_meta)
        if shown.size != hidden.size:
            raise ValueError(f"Proof sizes differ after EXIF orientation: {shown.size} / {hidden.size}")
        regions = []
        for spec in args.roi:
            name, rect = roi_box(spec, shown.size)
            regions.append(dict(name=name, **measure(shown, hidden, rect, args.min_delta, args.min_percent)))
        passed = all(region["passed"] for region in regions)
        report = {"exposed": shown_meta, "without_object": hidden_meta,
                  "min_percent": args.min_percent, "min_delta": args.min_delta, "regions": regions, "passed": passed}
        document = json.dumps(report, ensure_ascii=False, indent=2)
        if args.json:
            args.json.parent.mkdir(parents=True, exist_ok=True)
            args.json.write_text(document + "\n", encoding="utf-8")
        print(document)
        return 0 if passed else 1
    except (ValueError, OSError, SyntaxError, Image.DecompressionBombError, ImageCms.PyCMSError) as error:
        parser.exit(2, f"Reveal check could not run: {error}\n")


if __name__ == "__main__":
    sys.exit(main())
