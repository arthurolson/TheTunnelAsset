"""Turn a SHARP .ply (grid-ordered Gaussians) into a vertex-colored 2.5D mesh.

SHARP stores Gaussians as (layers, H, W) flattened. Layer 0 is the front surface, so we
triangulate that grid and drop triangles that straddle depth discontinuities.

Usage: python tools/splat_to_mesh.py in.ply out_basename [layers=2]
Writes out_basename.ply (vertex colors) and out_basename.glb, converted to y-up.
"""

import sys

import numpy as np
import trimesh
from plyfile import PlyData

src, out = sys.argv[1], sys.argv[2]
layers = int(sys.argv[3]) if len(sys.argv) > 3 else 2
v = PlyData.read(src)["vertex"]
n = len(v)
side = int(round((n / layers) ** 0.5))
assert side * side * layers == n, (n, side)

xyz = np.stack([v["x"], v["y"], v["z"]], -1).reshape(layers, side, side, 3)[0]
sh = np.stack([v["f_dc_0"], v["f_dc_1"], v["f_dc_2"]], -1).reshape(layers, side, side, 3)[0]
op = (1 / (1 + np.exp(-np.asarray(v["opacity"])))).reshape(layers, side, side)[0]
rgb = np.clip(0.5 + 0.28209479177387814 * sh, 0, 1)

idx = np.arange(side * side).reshape(side, side)
a, b = idx[:-1, :-1].ravel(), idx[:-1, 1:].ravel()
c, d = idx[1:, :-1].ravel(), idx[1:, 1:].ravel()
faces = np.concatenate([np.stack([a, c, b], 1), np.stack([b, c, d], 1)])

P = xyz.reshape(-1, 3)
z = P[:, 2]
# Drop faces across depth jumps (relative depth ratio) or on near-transparent points.
fz = z[faces]
ratio = fz.max(1) / np.maximum(fz.min(1), 1e-6)
keep = (ratio < 1.04) & (op.reshape(-1)[faces].min(1) > 0.1)
faces = faces[keep]

# OpenCV (x right, y down, z forward) -> y-up, camera looking down -z.
P = P * np.array([1, -1, -1])
colors = (np.concatenate([rgb.reshape(-1, 3), np.ones((len(P), 1))], 1) * 255).astype(np.uint8)
mesh = trimesh.Trimesh(P, faces, vertex_colors=colors, process=False)
mesh.remove_unreferenced_vertices()
mesh.export(out + ".ply")
mesh.export(out + ".glb")
print(f"grid {side}x{side}, faces kept {keep.sum()}/{len(keep)}, verts {len(mesh.vertices)}")
