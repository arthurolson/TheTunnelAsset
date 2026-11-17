"""Convert the OBJ from usdz_to_obj.swift to GLB, optionally rescaled to a real height.

Object Capture output has arbitrary scale. With height_m, the mesh is scaled so its bounding
box is that tall, centered on x/z, with its lowest point at y = 0 (feet on the floor).
Usage: python tools/obj_to_glb.py in.obj out.glb [height_m]
"""

import sys

import trimesh

src, dst = sys.argv[1], sys.argv[2]
height = float(sys.argv[3]) if len(sys.argv) > 3 else None
scene = trimesh.load(src, force="scene")
if height:
    lo, hi = scene.bounds
    s = height / (hi[1] - lo[1])
    c = (lo + hi) / 2
    scene.apply_translation([-c[0], -lo[1], -c[2]])
    scene.apply_scale(s)
scene.export(dst)
print(f"wrote {dst}, bounds {scene.bounds.round(3).tolist()}")
