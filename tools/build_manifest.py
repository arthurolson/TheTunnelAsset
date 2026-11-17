"""Regenerate assets.json from the files in splat/ and mesh/.

Edit ASSETS below when you add a file, then run:  python tools/build_manifest.py
Requires: numpy, plyfile, trimesh (only for counting vertices/faces).
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = "autinlab/TheTunnelAsset"
BRANCH = "main"
RAW = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/"
CDN = f"https://cdn.jsdelivr.net/gh/{REPO}@{BRANCH}/"  # jsDelivr: only files < 20 MB

SHARP = {
    "name": "SHARP (Apple ml-sharp)",
    "url": "https://github.com/apple/ml-sharp",
    "notes": "Single-image feedforward 3D Gaussian Splatting; reconstructs only what the camera saw.",
}
OPENCV = {"convention": "opencv", "x": "right", "y": "down", "z": "forward", "units": "meters (approx.)",
          "to_y_up": "rotate 180 deg about X"}
Y_UP = {"convention": "gltf", "x": "right", "y": "up", "z": "toward viewer", "units": "meters (approx.)"}

# id -> metadata. `file` is relative to the repo root.
ASSETS: list[dict] = [
    # ---------------- splats ----------------
    dict(id="goodsell_portrait_splat", file="splat/goodsell_portrait.ply", kind="splat",
         subject="david-goodsell", title="David Goodsell painting at his desk",
         tags=["portrait", "artist", "studio", "watercolor"], source="photo",
         method=SHARP, coords=OPENCV, thumbnail="thumbs/goodsell_portrait.jpg"),
    dict(id="scripps_virus_panel_splat", file="splat/scripps_virus_panel_IMG_7748.ply", kind="splat",
         subject="scripps", title="Scripps lab: framed virus capsid artwork",
         tags=["scripps", "virus", "artwork", "lab"], source="photo (IMG_7748)",
         method=SHARP, coords=OPENCV, thumbnail="thumbs/scripps_virus_panel_IMG_7748.jpg"),
    dict(id="scripps_virus_models_7756_splat", file="splat/scripps_virus_models_IMG_7756.ply",
         kind="splat", subject="scripps", title="Scripps lab: 3D-printed virus capsid models (1)",
         tags=["scripps", "virus", "3d-print", "models"], source="photo (IMG_7756)",
         method=SHARP, coords=OPENCV, thumbnail="thumbs/scripps_virus_models_IMG_7756.jpg"),
    dict(id="scripps_virus_models_7757_splat", file="splat/scripps_virus_models_IMG_7757.ply",
         kind="splat", subject="scripps", title="Scripps lab: 3D-printed virus and capsid models (2)",
         tags=["scripps", "virus", "3d-print", "models"], source="photo (IMG_7757)",
         method=SHARP, coords=OPENCV, thumbnail="thumbs/scripps_virus_models_IMG_7757.jpg"),
    dict(id="art_photo_splat", file="splat/art_photo_IMG_9389.ply", kind="splat",
         subject="art", title="Art standing in the lab (photo)",
         tags=["person", "full-body", "lab"], source="photo (IMG_9389)",
         method=SHARP, coords=OPENCV, thumbnail="thumbs/art_photo_IMG_9389.jpg"),
    # ---------------- meshes ----------------
    dict(id="goodsell_portrait_mesh", file="mesh/goodsell_portrait_mesh.glb", kind="mesh",
         subject="david-goodsell", title="David Goodsell portrait, textured 2.5D mesh",
         tags=["portrait", "relief"], source="derived from goodsell_portrait_splat",
         method={"name": "SHARP splat -> mesh"}, coords=Y_UP, thumbnail="thumbs/goodsell_portrait.jpg"),
    dict(id="goodsell_portrait_mesh_bright", file="mesh/goodsell_portrait_mesh_bright.glb",
         kind="mesh", subject="david-goodsell",
         title="David Goodsell portrait, textured 2.5D mesh (brightened)",
         tags=["portrait", "relief"], source="derived from goodsell_portrait_splat",
         method={"name": "SHARP splat -> mesh"}, coords=Y_UP, thumbnail="thumbs/goodsell_portrait.jpg"),
    dict(id="goodsell_portrait_splatlook", file="mesh/goodsell_portrait_splatlook.glb",
         kind="mesh", subject="david-goodsell",
         title="David Goodsell portrait, splat-look mesh (one quad per Gaussian)",
         tags=["portrait", "splat-look"], source="derived from goodsell_portrait_splat",
         method={"name": "SHARP splat -> billboard mesh"}, coords=Y_UP,
         thumbnail="thumbs/goodsell_portrait.jpg"),
    dict(id="art_photo_mesh", file="mesh/art_photo_IMG_9389_mesh.glb", kind="mesh",
         subject="art", title="Art standing in the lab, vertex-colored 2.5D mesh",
         tags=["person", "relief", "lab"], source="derived from art_photo_splat",
         method={"name": "SHARP splat -> grid mesh (front layer)",
                 "script": "ml-sharp tools/splat_to_mesh.py"},
         coords=Y_UP, thumbnail="thumbs/art_photo_IMG_9389_mesh.jpg"),
    dict(id="art_video_fullbody_glb", file="mesh/art_video_IMG_9390_fullbody.glb", kind="mesh",
         subject="art", title="Art full-body 360 deg textured mesh (from orbit video)",
         tags=["person", "full-body", "360", "riggable-candidate"], source="video (IMG_9390, 17 s orbit)",
         method={"name": "Apple Object Capture (RealityKit PhotogrammetrySession)", "detail": "medium",
                 "frames": 134,
                 "notes": "Ghost second head and an extra sheet on one side (subject moved); "
                          "arbitrary scale (~1.35 m tall), rescale to real height."},
         coords=Y_UP, thumbnail="thumbs/art_video_IMG_9390_fullbody.jpg"),
    dict(id="art_video_fullbody_usdz", file="mesh/art_video_IMG_9390_fullbody.usdz", kind="mesh",
         subject="art", title="Art full-body 360 deg textured mesh (USDZ for iOS / visionOS AR)",
         tags=["person", "full-body", "360", "ar"], source="video (IMG_9390, 17 s orbit)",
         method={"name": "Apple Object Capture (RealityKit PhotogrammetrySession)", "detail": "medium"},
         coords=Y_UP, thumbnail="thumbs/art_video_IMG_9390_fullbody.jpg"),
]

FORMATS = {
    ".ply": ("gaussian-splat-ply", "application/octet-stream"),
    ".glb": ("gltf-binary", "model/gltf-binary"),
    ".usdz": ("usdz", "model/vnd.usdz+zip"),
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def geometry_stats(path: Path) -> dict:
    try:
        if path.suffix == ".ply":
            from plyfile import PlyData

            ply = PlyData.read(str(path))
            out = {"gaussians": len(ply["vertex"])}
            if "image_size" in ply:
                w, h = (int(x[0]) for x in ply["image_size"].data)
                out["source_image_size"] = [w, h]
            return out
        if path.suffix == ".glb":
            import trimesh

            scene = trimesh.load(str(path))
            geoms = list(scene.geometry.values()) if hasattr(scene, "geometry") else [scene]
            return {
                "vertices": int(sum(len(g.vertices) for g in geoms)),
                "faces": int(sum(len(g.faces) for g in geoms)),
                "color": geoms[0].visual.kind if geoms else None,
            }
    except Exception as e:  # stats are best-effort
        return {"stats_error": str(e)}
    return {}


def main() -> None:
    items = []
    for a in ASSETS:
        p = ROOT / a["file"]
        fmt, mime = FORMATS[p.suffix]
        size = p.stat().st_size
        item = {
            "id": a["id"],
            "kind": a["kind"],
            "subject": a["subject"],
            "title": a["title"],
            "tags": a["tags"],
            "format": fmt,
            "mime": mime,
            "path": a["file"],
            "url": RAW + a["file"],
            "cdn_url": CDN + a["file"] if size < 20_000_000 else None,
            "bytes": size,
            "sha256": sha256(p),
            "thumbnail": RAW + a["thumbnail"],
            "source": a["source"],
            "method": a["method"],
            "coordinates": a["coords"],
            **geometry_stats(p),
        }
        items.append(item)
        print(f"{a['id']:34s} {size / 1e6:7.1f} MB")

    manifest = {
        "schema": "thetunnel-assets/1",
        "repo": f"https://github.com/{REPO}",
        "base_url": RAW,
        "updated": date.today().isoformat(),
        "count": len(items),
        "subjects": sorted({i["subject"] for i in items}),
        "assets": items,
    }
    (ROOT / "assets.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote assets.json ({len(items)} assets)")


if __name__ == "__main__":
    main()
