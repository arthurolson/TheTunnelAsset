"""Removes the parts of a textured model coloured like a plain background: for a turntable capture whose frames were
cut out onto grey (tools/mask_subject.swift), photogrammetry can wall in the gaps under a chair or between legs with
that grey. Each triangle's colour is sampled from the texture at a few points; triangles that are almost all
background grey go, and so do small loose pieces left over.

    python3 tools/glb_drop_colour.py in.glb out.glb [--below 0.5] [--grey 0.5] [--tolerance 0.07] [--min-piece 0.002]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import trimesh


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("glb", type=Path)
    p.add_argument("out", type=Path)
    p.add_argument("--grey", type=float, default=0.5, help="the background grey, 0-1")
    p.add_argument("--tolerance", type=float, default=0.07, help="how far from that grey still counts as background")
    p.add_argument("--min-piece", type=float, default=0.002, help="loose pieces smaller than this fraction of the faces go")
    p.add_argument("--below", type=float, default=None,
                   help="only triangles lower than this height (model units, y up) can go: under a chair's seat, say")
    a = p.parse_args()

    mesh = trimesh.load(a.glb, force="mesh")
    material = mesh.visual.material
    image = getattr(material, "baseColorTexture", None) or getattr(material, "image", None)
    texture = np.asarray(image.convert("RGB"), np.float32) / 255.0
    h, w = texture.shape[:2]
    uv = mesh.visual.uv[mesh.faces]  # (faces, 3, 2)

    # Sample each triangle at its corners pulled a little inward and its centre.
    weights = np.array([[0.7, 0.15, 0.15], [0.15, 0.7, 0.15], [0.15, 0.15, 0.7], [1 / 3, 1 / 3, 1 / 3]])
    samples = np.einsum("sk,fkd->fsd", weights, uv) % 1.0
    colours = texture[((1 - samples[..., 1]) * (h - 1)).astype(int), (samples[..., 0] * (w - 1)).astype(int)]
    background = (np.abs(colours - a.grey).max(-1) < a.tolerance).mean(-1) >= 0.75
    if a.below is not None:
        background &= mesh.triangles_center[:, 1] < a.below
    print(f"{background.sum():,} of {len(mesh.faces):,} triangles are background grey")

    mesh.update_faces(~background)
    mesh.remove_unreferenced_vertices()
    pieces = mesh.split(only_watertight=False)
    keep = [piece for piece in pieces if len(piece.faces) >= a.min_piece * len(mesh.faces)]
    print(f"{len(pieces)} pieces, kept {len(keep)}")
    out = trimesh.util.concatenate(keep) if len(keep) > 1 else keep[0]
    out.export(a.out)
    print(f"wrote {a.out}: {len(out.faces):,} triangles, bounds {np.round(out.bounds, 3).tolist()}")


if __name__ == "__main__":
    main()
