"""Run this skill's build or proof step in local Photoshop on macOS."""

import argparse
import json
from pathlib import Path
import subprocess
import sys


APPLE_SCRIPT = """
on run argv
    set jsxSource to item 1 of argv
    tell application id "com.adobe.Photoshop"
        with timeout of 1800 seconds
            return do javascript jsxSource
        end timeout
    end tell
end run
"""

STEPS = {
    "build": ("posterLayerManifest", "build_psd.jsx"),
    "proof": ("posterLayerProof", "proof_psd.jsx"),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", choices=STEPS)
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.exit(1, "Use Photoshop File > Scripts > Browse to run the JSX on this platform.\n")
    if not args.config.is_file():
        parser.error("The JSON configuration file does not exist")
    parameter, filename = STEPS[args.step]
    script = Path(__file__).resolve().with_name(filename)
    if not script.is_file():
        parser.error(f"Missing script: {script}")
    config_literal = json.dumps(str(args.config.resolve()))
    script_literal = json.dumps(str(script))
    jsx = (
        f"$.global.{parameter} = {config_literal}; "
        f"var result = $.evalFile(new File({script_literal})); "
        "if (result instanceof Error) throw result; result;"
    )
    return subprocess.run(["/usr/bin/osascript", "-e", APPLE_SCRIPT, jsx]).returncode


if __name__ == "__main__":
    sys.exit(main())
