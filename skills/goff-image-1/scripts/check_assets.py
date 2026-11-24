"""Validate full-canvas PNG layers and optionally pack them. Requires Pillow."""

import argparse
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unicodedata
import zipfile

try:
    from PIL import Image
except ImportError:
    sys.exit("This script requires Python with Pillow. Select an interpreter with PIL installed.")


def ordered_leaves(layers, prefix=""):
    """Keep the manifest's bottom-to-top order, including nested groups."""
    if not isinstance(layers, list) or not layers:
        raise ValueError(f"{prefix or 'manifest'} must have a nonempty layers array")
    names = set()
    for index, layer in enumerate(layers, 1):
        if not isinstance(layer, dict):
            raise ValueError(f"Invalid layer at {prefix}{index}")
        name = layer.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Missing layer name at {prefix}{index}")
        normalized = unicodedata.normalize("NFC", name.strip()).casefold()
        if normalized in names:
            raise ValueError(f"Duplicate sibling name at {prefix}{name}")
        names.add(normalized)
        safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name.strip()).rstrip(". ")
        entry = f"{prefix}{index:02d} {safe_name or 'layer'}"
        kind = layer.get("type")
        if "mask" in layer and kind != "raster":
            raise ValueError(f"{entry}: mask is supported only on a raster layer")
        if kind == "group":
            yield from ordered_leaves(layer.get("layers"), entry + "/")
        elif kind in ("raster", "text"):
            yield layer, entry + ".png"
        else:
            raise ValueError(f"{entry} has an unknown layer type: {kind!r}")


def alpha_extrema(image):
    if "A" in image.getbands():
        return image.getchannel("A").getextrema()
    if "transparency" in image.info:
        return image.convert("RGBA").getchannel("A").getextrema()
    return 255, 255


def image_alpha(path, canvas):
    # verify() checks the PNG chunks. Reopen to decode pixels and measure alpha.
    with Image.open(path) as image:
        if image.format != "PNG" or getattr(image, "n_frames", 1) != 1:
            raise ValueError(f"{path}: expected a single-frame PNG")
        if image.size != canvas:
            raise ValueError(f"{path}: {image.size} differs from the canvas {canvas}")
        image.verify()
    with Image.open(path) as image:
        image.load()
        return alpha_extrema(image)


def input_path(directory, value, label):
    if (not isinstance(value, str) or re.search(r"^/|[\\:]|(?:^|/)\.\.(?:/|$)|%[0-9a-fA-F]{2}", value)
            or Path(value).suffix.lower() != ".png"):
        raise ValueError(f"{label}: use a relative .png path under the manifest directory with / separators")
    return (directory / value).resolve()


def masked_image(path, mask_path, canvas):
    # PNG IHDR encodes bit depth and color type at bytes 24 and 25.
    with mask_path.open("rb") as data:
        header = data.read(26)
    with Image.open(mask_path) as mask:
        if (mask.format != "PNG" or mask.mode != "L" or header[24:26] != bytes((8, 0))
                or "transparency" in mask.info or getattr(mask, "n_frames", 1) != 1 or mask.size != canvas):
            raise ValueError(f"{mask_path}: mask must be a full-canvas, opaque, 8-bit grayscale PNG")
        mask.verify()
    with Image.open(mask_path) as mask, Image.open(path) as raw:
        image = raw.convert("RGBA")
        effective = Image.composite(image.getchannel("A"), Image.new("L", canvas, 0), mask)
        image.putalpha(effective)
        return image


def check_source(path, canvas):
    with Image.open(path) as source:
        size = source.size
        if source.getexif().get(274, 1) in (5, 6, 7, 8):
            size = size[::-1]
        if source.format not in ("JPEG", "PNG") or size != canvas:
            raise ValueError(f"Source {source.format} {size} must be a JPG/PNG matching {canvas}")
        return source.format == "PNG" and alpha_extrema(source)[0] < 255


def check_layers(manifest, source, require_text):
    doc = json.loads(manifest.read_text(encoding="utf-8-sig"))
    if not isinstance(doc, dict):
        raise ValueError("Expected a JSON object")
    canvas = doc.get("width"), doc.get("height")
    if any(type(side) is not int or side < 1 for side in canvas):
        raise ValueError("width and height must be positive integers")
    source_transparent = check_source(source, canvas) if source else False
    transparent = doc.get("transparentBackground", source_transparent)
    if type(transparent) is not bool:
        raise ValueError("transparentBackground must be true or false")
    entries = []
    used_files = set()
    leaves = list(ordered_leaves(doc.get("layers")))
    if not transparent and leaves[0][0].get("role") != "background":
        raise ValueError("The bottom raster of an opaque scene must have role 'background'")
    for index, (layer, archive_path) in enumerate(leaves):
        background = layer.get("role") == "background"
        if background and (index != 0 or layer["type"] != "raster"):
            raise ValueError(f"{archive_path}: the background must be the first raster at the bottom")
        file = layer.get("file")
        if file is None and layer["type"] == "text" and not require_text:
            print(f"{archive_path}: editable text; render PNG needed for --zip")
            continue
        if not isinstance(file, str) or not file.strip():
            raise ValueError(f"{archive_path}: missing PNG file (render text before packing)")
        path = input_path(manifest.parent, file, archive_path)
        if path in used_files:
            raise ValueError(f"{archive_path}: PNG already used by another layer: {path}")
        used_files.add(path)
        if layer["type"] == "text" and not path.exists() and not require_text:
            print(f"{archive_path}: 待 PSD 导出文字 PNG ({file})")
            continue
        low, high = image_alpha(path, canvas)
        if high == 0:
            raise ValueError(f"{archive_path}: empty layer, all alpha values are zero")
        mask_path = None
        if "mask" in layer:
            mask_path = input_path(manifest.parent, layer["mask"], archive_path + " mask")
            if mask_path == path:
                raise ValueError(f"{archive_path}: use separate artwork and mask files")
            rendered = masked_image(path, mask_path, canvas)
            low, high = alpha_extrema(rendered)
            rendered.close()
            if high == 0:
                print(f"{archive_path}: native mask fully hides the recoverable source")
        if background and not transparent and low != 255:
            raise ValueError(f"{archive_path}: incomplete background, minimum alpha is {low}")
        # A tightly cropped, originally translucent subject can cover every pixel.
        single_raster = transparent and len(leaves) == 1 and layer["type"] == "raster"
        overlay = layer.get("role") == "overlay" and layer["type"] == "raster"
        full_canvas_alpha = low < 255 and (single_raster or overlay)
        if not background and low != 0 and not full_canvas_alpha:
            raise ValueError(f"{archive_path}: no fully transparent exterior (minimum alpha {low})")
        print(f"{archive_path}: {canvas[0]}x{canvas[1]}, alpha {low}..{high}")
        entries.append((path, archive_path, mask_path))
    return entries


def pack(entries, destination):
    if destination.suffix.lower() != ".zip":
        raise ValueError("The --zip destination must end in .zip")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as temp:
        temporary = Path(temp.name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as archive:
            expected = []
            for path, name, mask_path in entries:
                expected.append(name)
                if mask_path is None:
                    archive.write(path, name)
                    continue
                with Image.open(path) as source:
                    canvas = source.size
                with masked_image(path, mask_path, canvas) as rendered, archive.open(name, "w", force_zip64=True) as out:
                    rendered.save(out, "PNG")
                folder = "蒙版源件/" + name[:-4] + "/"
                for item, filename in ((path, "完整原件.png"), (mask_path, "显示蒙版.png")):
                    archive.write(item, folder + filename)
                    expected.append(folder + filename)
        with zipfile.ZipFile(temporary) as archive:
            if archive.namelist() != expected or archive.testzip() is not None:
                raise ValueError("ZIP order or integrity check failed")
        # Reserve the name exclusively; another run may have finished this ZIP.
        with destination.open("xb"):
            pass
        try:
            os.replace(temporary, destination)
        except OSError:
            destination.unlink()
            raise
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--source", type=Path, help="Also check the original JPG/PNG display dimensions")
    parser.add_argument("--zip", type=Path, help="Write a verified PNG bundle, requiring renders for text layers")
    args = parser.parse_args()
    try:
        entries = check_layers(args.manifest, args.source, bool(args.zip))
        if args.zip:
            pack(entries, args.zip)
        print(f"OK: {len(entries)} PNGs checked" + (f", packed in {args.zip}" if args.zip else ""))
    except (ValueError, OSError, SyntaxError, zipfile.BadZipFile) as error:
        parser.exit(1, f"Asset check failed: {error}\n")


if __name__ == "__main__":
    main()
