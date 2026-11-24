"""Restore confirmed, visible source pixels to an aligned 8-bit PNG layer."""

import argparse
from pathlib import Path

from PIL import Image, ImageChops
from PIL.PngImagePlugin import PngInfo

from check_fidelity import ensure_same_encoding, load_rgba


def restore(source, layer, ownership, output):
    if output.suffix.lower() != ".png":
        raise ValueError("Output must be a new PNG")
    if output.exists() or any(output.resolve() == p.resolve() for p in (source, layer, ownership)):
        raise ValueError(f"Choose a new output path: {output}")
    original, ref_meta = load_rgba(source)
    candidate, layer_meta = load_rgba(layer, require_png=True)
    ensure_same_encoding(ref_meta, layer_meta)
    with Image.open(ownership) as mask:
        if mask.format != "PNG" or mask.mode not in ("L", "1") or getattr(mask, "n_frames", 1) != 1:
            raise ValueError("Ownership must be a single grayscale mask PNG; white means visible source")
        if mask.getexif().get(274, 1) != 1:
            raise ValueError("Bake the ownership mask orientation before using it")
        if mask.size != original.size or candidate.size != original.size:
            raise ValueError("Source, candidate and mask must share the same oriented pixel grid")
        # An antialiased source edge already contains its former background. Keep the
        # existing matte and straight-alpha RGB at such pixels.
        full = [0] * 255 + [255]
        opaque = ImageChops.multiply(original.getchannel("A").point(full), candidate.getchannel("A").point(full))
        weight = ImageChops.multiply(mask.convert("L"), opaque)
    merged = Image.composite(original, candidate, weight)
    # PNG geometry already follows display orientation. Preserve color metadata from
    # the candidate; do not transfer the original file's EXIF orientation.
    save_options = {}
    with Image.open(layer) as prior:
        if prior.info.get("icc_profile"):
            save_options["icc_profile"] = prior.info["icc_profile"]
        if prior.info.get("dpi"):
            save_options["dpi"] = prior.info["dpi"]
        if prior.mode == "RGB" and candidate.getchannel("A").getextrema() == (255, 255):
            merged = merged.convert("RGB")
        chunks = PngInfo()
        if "srgb" in prior.info and "icc_profile" not in save_options:
            chunks.add(b"sRGB", bytes([prior.info["srgb"]]))
        if "gamma" in prior.info:
            chunks.add(b"gAMA", round(prior.info["gamma"] * 100000).to_bytes(4, "big"))
        if "chromaticity" in prior.info:
            chunks.add(b"cHRM", b"".join(round(v * 100000).to_bytes(4, "big") for v in prior.info["chromaticity"]))
        save_options["pnginfo"] = chunks
    output.parent.mkdir(parents=True, exist_ok=True)
    stream = output.open("xb")
    try:
        with stream:
            merged.save(stream, format="PNG", **save_options)
    except Exception:
        output.unlink(missing_ok=True)
        raise
    count = weight.histogram()
    print(f"Restored {count[255]} fully weighted pixels; {sum(count[1:255])} seam pixels")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "layer", "ownership", "output"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    try:
        restore(args.source, args.layer, args.ownership, args.output)
    except (ValueError, OSError) as error:
        parser.exit(2, f"Source restoration failed: {error}\n")


if __name__ == "__main__":
    main()
