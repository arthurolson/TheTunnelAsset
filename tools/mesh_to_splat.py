"""A Gaussian splat (.ply, standard 3DGS layout) sampled from a textured or vertex-coloured mesh: Gaussians spread
evenly over its surface by area, coloured from its texture (or vertex colours), each a flat disc lying in the surface.
For a full 3D model (from Object Capture, say) this gives a splat of the whole object, all round, for splat viewers,
where SHARP gives only the front of a single photo.

    python3 tools/mesh_to_splat.py mesh/foo_fullbody.glb splat/foo_fullbody.ply [--count 600000]

The splat is written in OpenCV coordinates (x right, y down, z forward), as the repository's other splats are:
the glTF model's y-up frame turned 180 degrees about x. Needs numpy, trimesh, plyfile and Pillow.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import trimesh
from plyfile import PlyData, PlyElement

SH_C0 = 0.28209479177387814


def surface_colours(mesh: trimesh.Trimesh, faces: np.ndarray, bary: np.ndarray) -> np.ndarray:
    """sRGB colours 0-1 at points on the mesh: from its texture at the points' UVs, else its vertex colours."""
    visual = mesh.visual
    if isinstance(visual, trimesh.visual.TextureVisuals) and visual.uv is not None and visual.material is not None:
        image = getattr(visual.material, "baseColorTexture", None) or getattr(visual.material, "image", None)
        if image is not None:
            texture = np.asarray(image.convert("RGB"), np.float32) / 255.0
            uv = (visual.uv[mesh.faces[faces]] * bary[:, :, None]).sum(1) % 1.0
            h, w = texture.shape[:2]
            return texture[((1 - uv[:, 1]) * (h - 1)).astype(int), (uv[:, 0] * (w - 1)).astype(int)]
    colours = mesh.visual.to_color().vertex_colors[:, :3].astype(np.float32) / 255.0
    return (colours[mesh.faces[faces]] * bary[:, :, None]).sum(1)


def quaternions_from_normals(normals: np.ndarray) -> np.ndarray:
    """(w, x, y, z) rotations taking the Gaussian's local z axis (its thin one) to each normal."""
    z = np.array([0.0, 0.0, 1.0])
    axis = np.cross(np.broadcast_to(z, normals.shape), normals)
    s = np.linalg.norm(axis, axis=1, keepdims=True)
    c = normals @ z
    angle = np.arctan2(s[:, 0], c)
    axis = np.where(s > 1e-8, axis / np.maximum(s, 1e-12), np.array([1.0, 0.0, 0.0]))
    half = angle / 2
    return np.column_stack([np.cos(half), axis * np.sin(half)[:, None]])


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("mesh", type=Path)
    p.add_argument("out", type=Path)
    p.add_argument("--count", type=int, default=600_000, help="how many Gaussians")
    p.add_argument("--thickness", type=float, default=0.15, help="a disc's thickness as a fraction of its width")
    a = p.parse_args()

    mesh = trimesh.load(a.mesh, force="mesh")
    points, faces = trimesh.sample.sample_surface_even(mesh, a.count) if a.count < 50_000 else trimesh.sample.sample_surface(mesh, a.count)
    corners = mesh.triangles[faces]
    bary = trimesh.triangles.points_to_barycentric(corners, points)
    colours = surface_colours(mesh, faces, np.clip(bary, 0, 1))
    normals = mesh.face_normals[faces]

    # Each disc covers about its share of the surface, a little more so they overlap without gaps.
    radius = np.sqrt(mesh.area / len(points) / np.pi) * 1.4
    flip = np.array([1.0, -1.0, -1.0])  # glTF y-up -> OpenCV (x right, y down, z forward)
    points = points * flip
    normals = normals * flip
    rotation = quaternions_from_normals(normals / np.linalg.norm(normals, axis=1, keepdims=True))

    n = len(points)
    fields = [("x", "f4"), ("y", "f4"), ("z", "f4"), ("nx", "f4"), ("ny", "f4"), ("nz", "f4"),
              ("f_dc_0", "f4"), ("f_dc_1", "f4"), ("f_dc_2", "f4"), ("opacity", "f4"),
              ("scale_0", "f4"), ("scale_1", "f4"), ("scale_2", "f4"),
              ("rot_0", "f4"), ("rot_1", "f4"), ("rot_2", "f4"), ("rot_3", "f4")]
    v = np.zeros(n, dtype=fields)
    v["x"], v["y"], v["z"] = points.T
    dc = (colours - 0.5) / SH_C0
    v["f_dc_0"], v["f_dc_1"], v["f_dc_2"] = dc.T
    v["opacity"] = np.log(0.95 / 0.05)  # logit of 0.95
    v["scale_0"] = v["scale_1"] = np.log(radius)
    v["scale_2"] = np.log(radius * a.thickness)
    v["rot_0"], v["rot_1"], v["rot_2"], v["rot_3"] = rotation.T
    PlyData([PlyElement.describe(v, "vertex")], text=False).write(str(a.out))
    size = points.max(0) - points.min(0)
    print(f"{a.out}: {n:,} Gaussians, {a.out.stat().st_size / 1e6:.1f} MB, disc radius {radius * 1000:.1f} mm, "
          f"{size[0]:.2f} x {size[1]:.2f} x {size[2]:.2f} m")


if __name__ == "__main__":
    main()
