"""Verify full-resolution reconstruction and object-toggle evidence for goff-image-99."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

from PIL import Image, ImageCms
from check_assets import masked_image, ordered_leaves
from check_fidelity import ensure_same_encoding, load_rgba, region_stats, roi_box
from check_reveal import measure


def digest(path):
    with path.open("rb") as f:
        h = hashlib.sha256()
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def layer_path(value):
    if not isinstance(value, list) or not value or not all(isinstance(s, str) and s for s in value):
        raise ValueError(f"Expected a nonempty layer-name path: {value!r}")
    return tuple(value)


def layer_map(layers, parent=()):
    for item in layers:
        path = parent + (item["name"],)
        if item["type"] == "group":
            yield from layer_map(item["layers"], path)
        else:
            yield path, item


def state(only=(), hide=(), unmask=()):
    return tuple(frozenset(paths) for paths in (only, hide, unmask))


def changes(a, b):
    stats = region_stats(a, b, (0, 0, *a.size), 100)
    return stats["canvas"]["pixels"] - stats["canvas"]["exact_pixels"]


def audit(original, manifest, proof, plan):
    doc, spec, rubric = (read_json(p) for p in (manifest, proof, plan))
    original_image, meta = load_rgba(original)
    canvas = original_image.size
    if tuple(doc[k] for k in ("width", "height")) != canvas:
        raise ValueError("Manifest and oriented source dimensions differ")
    psd = (manifest.parent / doc["output"]).resolve()
    if not psd.samefile(proof.parent / spec["psd"]):
        raise ValueError("Manifest and native proof reference different PSDs")
    with Image.open(psd) as im:
        if im.format != "PSD" or im.size != canvas:
            raise ValueError("Expected a PSD of the same dimensions")
        recorded_layers = im.n_frames
    list(ordered_leaves(doc["layers"]))
    leaves = dict(layer_map(doc["layers"]))
    objects = [layer_path(p) for p in rubric["objects"]]
    support = {layer_path(p) for p in rubric.get("support", [])}
    bg = {p for p, layer in leaves.items() if layer.get("role") == "background"}
    if not objects or len(set(objects)) != len(objects) or support.intersection(objects):
        raise ValueError("Declare each editable object once, separate from support layers")
    if set(objects) | support | bg != set(leaves):
        raise ValueError("Declare every leaf as an editable object, a background or a support layer")

    def load(path):
        image, info = load_rgba(path, require_png=True)
        ensure_same_encoding(meta, info)
        if image.size != canvas:
            raise ValueError(f"Wrong canvas: {path}")
        return image

    index = {}
    files = set()
    moved = None
    for shot in spec["shots"]:
        path = (proof.parent / shot["file"]).resolve()
        if path.suffix.lower() != ".png":
            continue
        if path in files:
            raise ValueError(f"Proof file reused across states: {path}")
        files.add(path)
        if "move" in shot:
            if shot["move"] == rubric.get("move") and not any(k in shot for k in ("only", "hide", "unmask", "text")):
                moved = path
            continue
        sel = shot.get("only", [])
        if "text" in shot:
            sel = [shot["text"]]
        key = state(*[[layer_path(p) for p in a] for a in (sel, shot.get("hide", []), shot.get("unmask", []))])
        index.setdefault(key, path)

    def shot(key):
        if key not in index:
            raise ValueError(f"Missing native PNG proof for state {key}")
        return load(index[key])

    if original.samefile(index[state()]):
        raise ValueError("Full PSD proof and original must be distinct files")
    full = shot(state())
    fidelity = region_stats(original_image, full, (0, 0, *canvas), 99)
    visible = fidelity["visible_union"]
    total = visible["pixels"]
    if not total:
        raise ValueError("No visible source or output pixels to measure")
    exact = visible["exact_pixels"]
    delta = total - exact
    grade = "二代" if 100 * exact >= 99 * total else "一代级" if 100 * exact >= 95 * total else "待修"
    failures = []
    report = {"source_sha256": digest(original), "psd_sha256": digest(psd), "full_png_sha256": digest(index[state()]),
              "size": canvas, "encoding": meta["encoding"], "pixels": canvas[0] * canvas[1],
              "visible_pixels": total, "excluded_transparent_pixels": canvas[0] * canvas[1] - total,
              "exact_pixels": exact, "different_pixels": delta, "exact_percent": 100 * exact / total,
              "pixel_grade": grade, "required_percent": 99, "objects": [], "reveal": [], "failures": failures}
    if len(leaves) > 1 and recorded_layers < 2:
        failures.append("PSD contains no editable layer stack for the declared multi-layer manifest")
    if full.getchannel("A").getextrema() == (255, 255):
        with Image.open(psd) as im:
            if changes(im.convert("RGBA"), full):
                failures.append("PSD merged pixels differ from the declared native full export")
    if "move" in rubric:
        if moved is None or not changes(full, load(moved)):
            failures.append("Expected a visibly changed native move proof")
    if grade != "二代":
        failures.append(f"Below 99 percent: {exact} of {total} visible pixels match exactly")

    for p, layer in leaves.items():
        art = load(manifest.parent / layer["file"])
        if changes(original_image, art) == 0 and (len(leaves) != 1 or art.getchannel("A").getextrema()[0] != 0):
            failures.append(f"Complete source used as layer: {p}")
        if p in bg and len(leaves) > 1:
            if changes(shot(state(only=[p])), full) == 0:
                failures.append(f"Solo background contains full scene: {p}")
        if p not in objects:
            continue
        mask = layer.get("mask")
        if mask:
            raw = shot(state(only=[p], unmask=[p]))
            if changes(raw, art):
                failures.append(f"Unmasked native export differs from the recoverable source: {p}")
            art = masked_image(manifest.parent / layer["file"], manifest.parent / mask, canvas)
        solo = shot(state(only=[p]))
        if changes(solo, art) or not solo.getchannel("A").getbbox():
            failures.append(f"Solo export differs from the independent asset or is empty: {p}")
        # Prefer hiding the physical item. Its group may own a corresponding shadow.
        hide_at = next((p[:n] for n in range(len(p), 0, -1) if state(hide=[p[:n]]) in index), None)
        if hide_at is None:
            raise ValueError(f"Missing hide proof: {p}")
        # A broad parent that also removes a different editable object cannot establish independence.
        if any(q != p and q[:len(hide_at)] == hide_at for q in objects):
            raise ValueError(f"Hide proof for {p} removes another declared object")
        modified = changes(full, shot(state(hide=[hide_at])))
        report["objects"].append({"layer": p, "hide": hide_at, "changed_pixels": modified})
    # A fully occluded object's contribution may only appear after the foreground is removed.
    revealed = set()
    for test in rubric["reveal"]:
        front = {layer_path(p) for p in test["hide"]}
        rear = layer_path(test["rear"])
        if not front or not any(p[:len(rear)] == rear for p in objects) or any(
                rear[:len(p)] == p or p[:len(rear)] == rear for p in front):
            raise ValueError("Reveal needs disjoint, separately controllable foreground and rear objects")
        area, bounds = roi_box(test["roi"], canvas)
        minimum = float(test["min_percent"])
        threshold = test.get("min_delta", 8)
        if not math.isfinite(minimum) or not 0 < minimum <= 100 or type(threshold) != int or not 1 <= threshold <= 255:
            raise ValueError("Invalid reveal thresholds")
        on = shot(state(hide=front))
        off = shot(state(hide=front | {rear}))
        metrics = measure(on, off, bounds, threshold, minimum)
        # Both directions matter: the ROI must have been visibly covered in the full image.
        occlusion = measure(full, on, bounds, threshold, minimum)
        report["reveal"].append({"roi": area, "revealed": metrics, "original_occlusion": occlusion})
        if not metrics["passed"] or not occlusion["passed"]:
            failures.append(f"Missing visible overlap or missing rear object: {area}")
        else:
            revealed.add(rear)
    for obj in report["objects"]:
        if not obj["changed_pixels"] and obj["hide"] not in revealed and obj["layer"] not in revealed:
            failures.append(f"Object has no visible contribution in tested states: {obj['layer']}")
    if not rubric["reveal"] and not str(rubric.get("no_overlap_reason", "")).strip():
        raise ValueError("Provide overlap evidence or describe why this design has no overlapping objects")
    report["automated_pass"] = not failures
    report["manual_review"] = "Inspect each solo, exposed material and moved object on neutral light/dark grounds"
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("original", "manifest", "proof", "audit"):
        parser.add_argument(name, type=Path)
    parser.add_argument("--json", type=Path, help="Save the report to a new JSON file")
    args = parser.parse_args()
    try:
        result = audit(args.original, args.manifest, args.proof, args.audit)
        output = json.dumps(result, ensure_ascii=False, indent=2)
        if args.json:
            if args.json.suffix.lower() != ".json":
                raise ValueError("Output report must use a new .json path")
            with args.json.open("x", encoding="utf-8") as stream:
                stream.write(output + "\n")
        print(output)
        return 0 if result["automated_pass"] else 1
    except (OSError, ValueError, TypeError, KeyError, ImageCms.PyCMSError) as exc:
        parser.exit(2, f"Release audit could not run: {exc}\n")


if __name__ == "__main__":
    sys.exit(main())
