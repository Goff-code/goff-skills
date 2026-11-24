"""Measure native-size pixel fidelity against a lossless, all-visible PSD export.

Requires Pillow with LittleCMS. Compares 8-bit straight RGB/alpha in the same
encoding. RGB is comparable where both pixels are visible; alpha is compared
everywhere. Untagged SDR is assumed sRGB. No gamut conversion or resizing.
"""

import argparse
import hashlib
import io
import json
import math
from pathlib import Path
import struct
import sys

try:
    from PIL import Image, ImageChops, ImageCms, ImageOps
except ImportError:
    sys.exit("Select a Python interpreter with Pillow and LittleCMS (PIL.ImageCms).")


def png_precision(path):
    """Pillow may expose 16-bit RGB PNG as RGB; inspect IHDR before decoding."""
    with path.open("rb") as stream:
        stream.seek(8)
        bits = None
        while True:
            header = stream.read(8)
            if len(header) != 8:
                raise ValueError(f"{path}: incomplete PNG header")
            length, kind = struct.unpack(">I4s", header)
            if kind == b"IDAT":
                break
            if kind == b"IHDR" and length == 13:
                bits = stream.read(13)[8]
            elif kind == b"cICP" and length == 4:
                cicp = tuple(stream.read(4))
                if cicp != (1, 13, 0, 1):
                    raise ValueError(f"{path}: unsupported cICP {cicp}; export matching 8-bit RGB SDR copies")
            else:
                stream.seek(length, 1)
            stream.seek(4, 1)
        return bits


def encoding(image):
    info = image.info
    if "icc_profile" in info:
        data = info["icc_profile"]
        if not data:
            raise ValueError("Unreadable embedded ICC profile")
        profile = ImageCms.ImageCmsProfile(io.BytesIO(data))
        if profile.profile.xcolor_space.strip() != "RGB":
            raise ValueError("Non-RGB ICC profile; convert to 8-bit RGB with a known profile first")
        desc = ImageCms.getProfileDescription(profile).strip()
        # Different sRGB profile files may carry different copyright/metadata.
        # Check a representative RGB cube as well as the profile's declared name.
        if "srgb" in desc.lower():
            values = [0, 2, 8, 16, 31, 64, 96, 128, 160, 192, 224, 252, 255]
            swatch = Image.new("RGB", (len(values) ** 3, 1))
            swatch.putdata([(r, g, b) for r in values for g in values for b in values])
            standard = ImageCms.createProfile("sRGB")
            converted = ImageCms.profileToProfile(swatch, profile, standard, renderingIntent=1)
            if max(hi for _, hi in ImageChops.difference(swatch, converted).getextrema()) <= 1:
                return "srgb", desc
        return "icc:" + hashlib.sha256(data).hexdigest(), desc
    if "srgb" in info:
        return "srgb", "PNG sRGB"
    gamma = info.get("gamma")
    chroma = info.get("chromaticity")
    srgb_chroma = (.3127, .3290, .6400, .3300, .3000, .6000, .1500, .0600)
    if (gamma is not None and abs(gamma - .45455) > .0001) or (
        chroma is not None and (len(chroma) != 8 or any(abs(v - s) > .0001 for v, s in zip(chroma, srgb_chroma)))
    ):
        key = f"PNG gamma={gamma}, chromaticity={chroma}"
        return key, key
    exif = image.getexif()
    if 34665 in exif:
        space = exif.get_ifd(34665).get(40961)
        if space not in (1, None):
            raise ValueError(f"EXIF ColorSpace={space} without a matching ICC; assign the verified source profile first")
    return "srgb", "sRGB (standard PNG hints or untagged SDR assumption)"


def load_rgba(path, *, require_png=False):
    """Return an EXIF-oriented straight RGBA image and JSON-serializable metadata."""
    path = Path(path)
    with Image.open(path) as raw:
        if raw.format not in (("PNG",) if require_png else ("JPEG", "PNG")):
            raise ValueError(f"{path}: expected {'a lossless PNG proof' if require_png else 'a JPG or PNG original'}")
        if getattr(raw, "n_frames", 1) != 1:
            raise ValueError(f"{path}: animated/multiframe images require a specific frame")
        bits = png_precision(path) if raw.format == "PNG" else getattr(raw, "bits", 8)
        if bits is None or bits > 8 or raw.mode not in ("1", "L", "LA", "P", "RGB", "RGBA"):
            raise ValueError(f"{path}: unsupported {raw.mode}, {bits}-bit samples; use matching 8-bit RGB copies")
        space, label = encoding(raw)
        orientation = int(raw.getexif().get(274, 1))
        if orientation not in range(1, 9):
            raise ValueError(f"{path}: invalid EXIF orientation {orientation}")
        image = ImageOps.exif_transpose(raw).convert("RGBA")
        return image, {"path": str(path), "format": raw.format, "mode": raw.mode, "bits": bits,
                       "orientation": orientation, "encoding": space, "profile": label, "size": list(image.size)}


def ensure_same_encoding(ref_meta, actual_meta):
    if ref_meta["encoding"] != actual_meta["encoding"]:
        raise ValueError(
            f"Different color encodings: {ref_meta['profile']} / {actual_meta['profile']}. "
            "Keep the source profile in Photoshop or color-manage both files into the same documented 8-bit RGB profile before measuring."
        )


VISIBLE = [0] + [255] * 255


def region_stats(original, actual, box, threshold, diff_image=None):
    x, y, right, bottom = box
    n = (right - x) * (bottom - y)
    union = shared = added = lost = exact = near = rgb_error = alpha_error = maximum = 0
    for top in range(y, bottom, 192):
        band = x, top, right, min(top + 192, bottom)
        ref = original.crop(band)
        result = actual.crop(band)
        ra, aa = ref.getchannel("A"), result.getchannel("A")
        rm, am = ra.point(VISIBLE), aa.point(VISIBLE)
        both = ImageChops.darker(rm, am)
        overlap = both.histogram()[255]
        original_count, actual_count = rm.histogram()[255], am.histogram()[255]
        shared += overlap
        union += original_count + actual_count - overlap
        added += actual_count - overlap
        lost += original_count - overlap
        ach = ImageChops.difference(ra, aa)
        peak = ach
        alpha_error += sum(value * count for value, count in enumerate(ach.histogram()))
        for channel in "RGB":
            delta = ImageChops.difference(ref.getchannel(channel), result.getchannel(channel))
            delta = ImageChops.multiply(delta, both)
            rgb_error += sum(value * count for value, count in enumerate(delta.histogram()))
            peak = ImageChops.lighter(peak, delta)
        hist = peak.histogram()
        exact += hist[0]
        near += sum(hist[:5])
        maximum = max(maximum, peak.getextrema()[1])
        if diff_image is not None:
            # Black = equal, amber = RGB 1..4, red = RGB >4, cyan = any alpha change.
            preview = Image.merge("RGB", (peak.point([0] + [245] * 255),
                                          peak.point([0] + [180] * 4 + [55] * 251),
                                          peak.point([0] + [44] * 255)))
            preview.paste((40, 205, 232), mask=ach.point(VISIBLE))
            diff_image.paste(preview, (x, top))
    invisible = n - union
    vx, vn = exact - invisible, near - invisible

    def ratios(num, within_four, total):
        return {"pixels": total, "exact_pixels": num, "within4_pixels": within_four,
                "exact_pct": 100 * num / total if total else None,
                "within4_pct": 100 * within_four / total if total else None}

    return {"box_xywh": [x, y, right - x, bottom - y], "canvas": ratios(exact, near, n),
            "visible_union": ratios(vx, vn, union), "both_visible": shared, "added_visible": added,
            "lost_visible": lost, "max_channel_diff": maximum, "mae_rgb_on_shared": rgb_error / (3 * shared) if shared else None,
            "mae_alpha_canvas": alpha_error / n, "mae_alpha_visible_union": alpha_error / union if union else None,
            "meets_threshold": union > 0 and 100 * exact >= threshold * n and 100 * vx >= threshold * union}


def roi_box(text, size):
    name, separator, coords = text.rpartition(":")
    if not separator:
        name, coords = text, text
    try:
        x, y, width, height = (int(s) for s in coords.split(","))
    except ValueError:
        raise ValueError(f"Invalid ROI {text!r}; use NAME:X,Y,W,H") from None
    if not name or x < 0 or y < 0 or width < 1 or height < 1 or x + width > size[0] or y + height > size[1]:
        raise ValueError(f"ROI {text!r} lies outside {size} or is empty")
    return name, (x, y, x + width, y + height)


def metric(value):
    return "n/a" if value is None else f"{value:.4f}"


def print_stats(label, stats):
    all_pixels, visible = stats["canvas"], stats["visible_union"]
    print(f"{label}: exact canvas {metric(all_pixels['exact_pct'])}% / visible union {metric(visible['exact_pct'])}%; "
          f"within 4 canvas {metric(all_pixels['within4_pct'])}% / visible {metric(visible['within4_pct'])}%; "
          f"MAE RGB {metric(stats['mae_rgb_on_shared'])}, alpha {metric(stats['mae_alpha_canvas'])}; "
          f"added/lost visible {stats['added_visible']}/{stats['lost_visible']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original", type=Path)
    parser.add_argument("proof", type=Path, help="lossless PNG rendered from the reopened PSD, all intended layers visible")
    parser.add_argument("--min-exact", type=float, default=95, help="minimum exact pixel percentage, 0 to 100 (default 95)")
    parser.add_argument("--roi", action="append", default=[], metavar="NAME:X,Y,W,H", help="repeatable region in displayed source coordinates")
    parser.add_argument("--enforce-roi", action="store_true", help="require each selected ROI to meet the same threshold")
    parser.add_argument("--diff", type=Path, help="PNG map: black equal, amber small RGB change, red larger, cyan alpha change")
    parser.add_argument("--json", type=Path, help="write a machine-readable JSON report")
    args = parser.parse_args()
    try:
        if not math.isfinite(args.min_exact) or not 0 <= args.min_exact <= 100:
            raise ValueError("--min-exact must be between 0 and 100")
        if args.original.samefile(args.proof):
            raise ValueError("Select the original and a separate PNG exported from the reopened PSD")
        targets = {args.original.resolve(), args.proof.resolve()}
        for out, ext in ((args.diff, ".png"), (args.json, ".json")):
            if out:
                if out.resolve() in targets or out.suffix.lower() != ext:
                    raise ValueError(f"Choose a separate {ext} output file: {out}")
                targets.add(out.resolve())
        original, orig_meta = load_rgba(args.original)
        actual, proof_meta = load_rgba(args.proof, require_png=True)
        ensure_same_encoding(orig_meta, proof_meta)
        if original.size != actual.size:
            raise ValueError(f"After orienting: original {original.size}, proof {actual.size}; dimensions must match")
        boxes = [roi_box(r, original.size) for r in args.roi]
        diff = Image.new("RGB", original.size) if args.diff else None
        full = region_stats(original, actual, (0, 0, *original.size), args.min_exact, diff)
        regions = [dict(name=name, **region_stats(original, actual, box, args.min_exact)) for name, box in boxes]
        passed = full["meets_threshold"] and (not args.enforce_roi or all(r["meets_threshold"] for r in regions))
        report = {"original": orig_meta, "proof": proof_meta, "min_exact_pct": args.min_exact,
                  "enforce_roi": args.enforce_roi, "full": full, "regions": regions, "passed": passed}
        print(f"Color: {orig_meta['profile']} / {proof_meta['profile']}")
        print_stats("Full", full)
        for r in regions:
            print_stats(r["name"], r)
        for out in (args.diff, args.json):
            if out:
                out.parent.mkdir(parents=True, exist_ok=True)
        if args.diff:
            diff.save(args.diff, "PNG")
        if args.json:
            args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if passed:
            print("PASS")
        else:
            print("FAIL: empty visible union" if not full["visible_union"]["pixels"] else "FAIL: exact match below threshold in a required region")
        return 0 if passed else 1
    except (ValueError, OSError, SyntaxError, Image.DecompressionBombError, ImageCms.PyCMSError) as error:
        parser.exit(2, f"Fidelity check could not run: {error}\n")


if __name__ == "__main__":
    sys.exit(main())
