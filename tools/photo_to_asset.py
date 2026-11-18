"""Pipeline A: one photo -> Gaussian splat (Apple SHARP) -> 2.5D mesh, in one command.

    ~/miniforge3/envs/sharp/bin/python tools/photo_to_asset.py photos/lab.jpg --id art_lab \
        --subject art --title "Art in the lab" --tags person,lab [--splatlook] [--background 92]

Writes, with a thumbnail and a sidecar for each, then regenerates assets.json:
    splat/<id>.ply                  the SHARP splat (OpenCV coordinates: x right, y down, z forward)
    mesh/<id>_mesh.glb              its front layer as a vertex-coloured relief mesh (glTF y-up, about 1M triangles)
    mesh/<id>_mesh_quest.glb        the same merged on a grid to about --quest-triangles, which headsets load instead
    mesh/<id>_splatlook.glb         with --splatlook: one small quad per Gaussian (left out if over 95 MB)
    mesh/<id>_splatlook_quest.glb   with --splatlook: the same, voxel-decimated to about --quest-triangles
Run it with the Python of the "sharp" conda environment (see the README): it needs SHARP, numpy, plyfile, trimesh
and Pillow. SHARP runs on --device mps (Apple silicon), cuda or cpu; its checkpoint downloads on the first run.

SHARP reconstructs only what the camera saw: the back of everything is empty, and the mesh is a relief, not a closed
object. --background P drops what lies further away than the P-th percentile of depth (a sky or a far wall).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

sys.path.insert(0, str(Path(__file__).parent))
from asset_meta import ROOT, run_manifest, write_sidecar  # noqa: E402

MAX_BYTES = 95_000_000
SH_C0 = 0.28209479177387814
SHARP = {"name": "SHARP (Apple ml-sharp)", "url": "https://github.com/apple/ml-sharp",
         "notes": "Single-image feedforward 3D Gaussian Splatting; reconstructs only what the camera saw."}


def run(cmd: list[str]) -> None:
    print("  $ " + " ".join(str(c) for c in cmd))
    subprocess.run([str(c) for c in cmd], check=True)


def predict_splat(photo: Path, work: Path, device: str) -> Path:
    """SHARP on the one photo: its .ply (1,179,648 Gaussians: 2 layers of 768 x 768, OpenCV coordinates)."""
    inputs, outputs = work / "input", work / "gaussians"
    shutil.rmtree(inputs, ignore_errors=True)
    inputs.mkdir(parents=True)
    outputs.mkdir(parents=True, exist_ok=True)
    shutil.copy2(photo, inputs / photo.name)
    sharp = Path(sys.executable).parent / "sharp"
    run([sharp if sharp.exists() else "sharp", "predict", "-i", inputs, "-o", outputs, "--device", device])
    plys = sorted(outputs.glob("*.ply"), key=lambda p: p.stat().st_mtime)
    if not plys:
        raise SystemExit("SHARP wrote no .ply")
    return plys[-1]


def read_splat(ply: Path):
    from plyfile import PlyData

    data = PlyData.read(str(ply))
    return data, data["vertex"].data


def relief_mesh(vertices, out: Path, background: float | None, layers: int = 2) -> dict:
    """The front layer of SHARP's grid, triangulated: 2 triangles per cell, none across a depth jump (max z / min z
    >= 1.04) or on near-transparent points (opacity <= 0.1), nor beyond the background cut; y-up, vertex colours."""
    import trimesh

    n = len(vertices)
    side = int(round((n / layers) ** 0.5))
    if side * side * layers != n:
        raise SystemExit(f"{n} Gaussians aren't {layers} layers of a square grid: not a SHARP splat?")
    xyz = np.stack([vertices["x"], vertices["y"], vertices["z"]], -1).reshape(layers, side, side, 3)[0]
    dc = np.stack([vertices["f_dc_0"], vertices["f_dc_1"], vertices["f_dc_2"]], -1).reshape(layers, side, side, 3)[0]
    opacity = (1 / (1 + np.exp(-np.asarray(vertices["opacity"], np.float64)))).reshape(layers, side, side)[0].reshape(-1)
    rgb = np.clip(0.5 + SH_C0 * dc, 0, 1).reshape(-1, 3)

    idx = np.arange(side * side).reshape(side, side)
    a, b = idx[:-1, :-1].ravel(), idx[:-1, 1:].ravel()
    c, d = idx[1:, :-1].ravel(), idx[1:, 1:].ravel()
    faces = np.concatenate([np.stack([a, c, b], 1), np.stack([b, c, d], 1)])
    points = xyz.reshape(-1, 3)
    z = points[faces][:, :, 2]
    keep = (z.max(1) / np.maximum(z.min(1), 1e-6) < 1.04) & (opacity[faces].min(1) > 0.1)
    cut = None
    if background is not None:
        cut = float(np.percentile(points[opacity > 0.1, 2], background))
        keep &= z.max(1) <= cut
    faces = faces[keep]

    points = points * np.array([1, -1, -1])  # OpenCV (x right, y down, z forward) -> glTF y-up, toward the viewer
    colours = (np.concatenate([rgb, np.ones((len(points), 1))], 1) * 255).astype(np.uint8)
    mesh = trimesh.Trimesh(points, faces, vertex_colors=colours, process=False)
    mesh.remove_unreferenced_vertices()
    mesh.export(out)
    print(f"  {out.relative_to(ROOT)}: grid {side} x {side}, {len(faces):,} of {len(keep):,} triangles kept, {len(mesh.vertices):,} vertices")
    return {"grid": side, "depth_ratio_max": 1.04, "min_opacity": 0.1, "background_percentile": background,
            "background_depth_m": round(cut, 3) if cut is not None else None}


def cut_background(ply: Path, data, vertices, background: float, out: Path) -> Path:
    """The splat without the Gaussians further than the background cut (for the splat-look meshes)."""
    from plyfile import PlyData, PlyElement

    opacity = 1 / (1 + np.exp(-np.asarray(vertices["opacity"], np.float64)))
    cut = np.percentile(vertices["z"][opacity > 0.1], background)
    kept = vertices[vertices["z"] <= cut]
    PlyData([PlyElement.describe(kept, "vertex")] + [e for e in data.elements if e.name != "vertex"], text=False).write(str(out))
    return out


def thumbnail_from_photo(photo: Path, out: Path) -> None:
    with Image.open(photo) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((480, 360))
        canvas = Image.new("RGB", (480, 360), (16, 16, 18))
        canvas.paste(im, ((480 - im.width) // 2, (360 - im.height) // 2))
        canvas.save(out, quality=88)
    print(f"  {out.relative_to(ROOT)}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("photo", type=Path)
    p.add_argument("--id", required=True, help="the asset id stem: lower-case letters, digits and _")
    p.add_argument("--subject", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--tags", default="")
    p.add_argument("--device", default="mps", choices=["mps", "cuda", "cpu"])
    p.add_argument("--background", type=float, help="drop what is beyond this depth percentile (e.g. 92)")
    p.add_argument("--splatlook", action="store_true", help="also the splat-look mesh and its Quest version")
    p.add_argument("--sigma", type=float, default=1.6, help="splat-look quad half-size, in standard deviations")
    p.add_argument("--soft", action="store_true", help="splat-look quads fade out (alpha-blended)")
    p.add_argument("--quest-triangles", type=int, default=300_000)
    p.add_argument("--splat", type=Path, help="use this SHARP .ply instead of running SHARP")
    p.add_argument("--no-manifest", action="store_true")
    a = p.parse_args()

    tags = [t for t in a.tags.split(",") if t]
    photo = a.photo.resolve()
    work = ROOT / ".work" / a.id
    work.mkdir(parents=True, exist_ok=True)
    with Image.open(photo) as im:
        size = list(ImageOps.exif_transpose(im).size)

    print("1. splat")
    source_ply = a.splat.resolve() if a.splat else predict_splat(photo, work, a.device)
    splat = ROOT / "splat" / f"{a.id}.ply"
    shutil.copy2(source_ply, splat)
    if splat.stat().st_size > MAX_BYTES:
        raise SystemExit(f"{splat.name} is {splat.stat().st_size / 1e6:.0f} MB, over GitHub's limit: crop it with "
                         "--background, or compress it (.spz / .sog) and host it elsewhere (see the README)")
    data, vertices = read_splat(splat)
    print(f"  {splat.relative_to(ROOT)}: {len(vertices):,} Gaussians, {splat.stat().st_size / 1e6:.1f} MB")

    print("2. relief mesh")
    mesh = ROOT / "mesh" / f"{a.id}_mesh.glb"
    relief = relief_mesh(vertices, mesh, a.background)

    mesh_quest = ROOT / "mesh" / f"{a.id}_mesh_quest.glb"
    run([sys.executable, ROOT / "tools/glb_grid_simplify.py", mesh, mesh_quest, "--target", a.quest_triangles // 2, "--cell", 0.002])

    print("3. thumbnails")
    thumbs = ROOT / "thumbs"
    thumbnail_from_photo(photo, thumbs / f"{a.id}.jpg")
    run([sys.executable, ROOT / "tools/glb_thumbnail.py", mesh, thumbs / f"{a.id}_mesh.jpg"])

    print("4. sidecars")
    write_sidecar(splat, id=f"{a.id}_splat", subject=a.subject, title=f"{a.title} (splat)", tags=tags,
                  thumbnail=f"thumbs/{a.id}.jpg", coordinates="opencv", source=f"photo ({photo.name})",
                  method={**SHARP, "device": a.device, "script": "tools/photo_to_asset.py"}, source_image_size=size)
    write_sidecar(mesh, id=f"{a.id}_mesh", subject=a.subject, title=f"{a.title}, 2.5D relief mesh", tags=tags + ["relief"],
                  thumbnail=f"thumbs/{a.id}_mesh.jpg", coordinates="gltf", source=f"derived from {a.id}_splat",
                  method={"name": "SHARP splat -> grid mesh (front layer)", "script": "tools/photo_to_asset.py",
                          **{k: v for k, v in relief.items() if v is not None}})
    write_sidecar(mesh_quest, id=f"{a.id}_mesh_quest", subject=a.subject, title=f"{a.title}, 2.5D relief mesh for Quest",
                  tags=tags + ["relief", "quest", "mobile"], thumbnail=f"thumbs/{a.id}_mesh.jpg", coordinates="gltf",
                  source=f"derived from {a.id}_mesh",
                  method={"name": "tools/glb_grid_simplify.py (vertices merged on a grid)", "target_triangles": a.quest_triangles})

    if a.splatlook:
        print("5. splat-look meshes")
        quads_from = cut_background(splat, data, vertices, a.background, work / "cut.ply") if a.background is not None else splat
        soft = ["--soft"] if a.soft else []
        look = ROOT / "mesh" / f"{a.id}_splatlook.glb"
        run([sys.executable, ROOT / "tools/splat2glb.py", quads_from, look, a.sigma, 0, "", *soft])
        settings = {"sigma": a.sigma, "soft": a.soft, "background_percentile": a.background, "min_opacity": 0.2}
        if look.stat().st_size > MAX_BYTES:
            print(f"  {look.name} is {look.stat().st_size / 1e6:.0f} MB, over GitHub's limit: left out (the Quest version stays)")
            look.unlink()
        else:
            write_sidecar(look, id=f"{a.id}_splatlook", subject=a.subject, title=f"{a.title}, splat-look mesh",
                          tags=tags + ["splat-look"], thumbnail=f"thumbs/{a.id}.jpg", coordinates="gltf",
                          source=f"derived from {a.id}_splat",
                          method={"name": "splat -> billboard mesh (tools/splat2glb.py)", **{k: v for k, v in settings.items() if v is not None}})
        quest = ROOT / "mesh" / f"{a.id}_splatlook_quest.glb"
        run([sys.executable, ROOT / "tools/splat2glb.py", quads_from, quest, a.sigma, a.quest_triangles // 2, "", *soft])
        write_sidecar(quest, id=f"{a.id}_splatlook_quest", subject=a.subject,
                      title=f"{a.title}, splat-look mesh for Quest", tags=tags + ["splat-look", "quest", "mobile"],
                      thumbnail=f"thumbs/{a.id}.jpg", coordinates="gltf", source=f"derived from {a.id}_splat",
                      method={"name": "splat -> billboard mesh (tools/splat2glb.py), voxel-decimated",
                              "target_triangles": a.quest_triangles, **{k: v for k, v in settings.items() if v is not None}})

    if not a.no_manifest:
        print("6. assets.json")
        run_manifest()
    print("done: check the thumbnails, then git add, commit and push")


if __name__ == "__main__":
    main()
