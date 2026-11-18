"""Writes an asset's metadata sidecar (<file>.meta.json) and, on request, regenerates assets.json. Used by the
pipelines (photo_to_asset.py, video_to_asset.sh) so a new asset is in the manifest, and in the headset after a push.

    python3 tools/asset_meta.py mesh/foo.glb --id foo --subject art --title "..." --tags a,b \
        --source "..." --method '{"name": "..."}' --coordinates gltf --thumbnail thumbs/foo.jpg [--manifest]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write_sidecar(asset: Path, **fields) -> Path:
    """The sidecar next to an asset file, with these fields (None values left out); returns its path."""
    meta = {k: v for k, v in fields.items() if v is not None and v != ""}
    if "id" not in meta:
        raise SystemExit("an asset needs an id")
    sidecar = asset.with_name(asset.name + ".meta.json")
    sidecar.write_text(json.dumps(meta, indent=2) + "\n")
    print(f"  {sidecar.relative_to(ROOT)}")
    return sidecar


def run_manifest() -> None:
    """Regenerates assets.json (stops on any problem the manifest script finds)."""
    result = subprocess.run([sys.executable, str(ROOT / "tools/build_manifest.py")], cwd=ROOT)
    if result.returncode != 0:
        raise SystemExit("build_manifest.py found a problem (see above)")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("asset", type=Path)
    p.add_argument("--id", required=True)
    p.add_argument("--subject")
    p.add_argument("--title")
    p.add_argument("--name")
    p.add_argument("--tags", default="")
    p.add_argument("--source")
    p.add_argument("--method", help="JSON object: the method and the settings used")
    p.add_argument("--coordinates")
    p.add_argument("--thumbnail")
    p.add_argument("--extra", help="JSON object of any other fields")
    p.add_argument("--manifest", action="store_true", help="then regenerate assets.json")
    a = p.parse_args()
    extra = json.loads(a.extra) if a.extra else {}
    write_sidecar(a.asset.resolve(), id=a.id, name=a.name, subject=a.subject, title=a.title,
                  tags=[t for t in a.tags.split(",") if t], thumbnail=a.thumbnail, coordinates=a.coordinates,
                  source=a.source, method=json.loads(a.method) if a.method else None, **extra)
    if a.manifest:
        run_manifest()


if __name__ == "__main__":
    main()
