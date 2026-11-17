"""Convert an OBJ with its MTL colours (one flat colour per material, as molecular surface exporters write them) to a
glb: one primitive per material, its Kd as the base colour, normals kept, coordinates as they are (glTF y-up).

    python3 tools/obj_mtl_to_glb.py surface.obj out.glb [--scale 1.0]

Needs numpy. (tools/obj_to_glb.py is the textured-photogrammetry converter; this one is for coloured surfaces.)
"""

from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

import numpy as np


def read_mtl(path: Path) -> dict[str, tuple[float, float, float]]:
    colours, name = {}, None
    if not path.exists():
        return colours
    for line in path.read_text().splitlines():
        parts = line.split()
        if parts[:1] == ["newmtl"]:
            name = parts[1]
        elif parts[:1] == ["Kd"] and name:
            colours[name] = tuple(float(x) for x in parts[1:4])
    return colours


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("obj", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--scale", type=float, default=1.0, help="multiply coordinates by this")
    args = parser.parse_args()

    positions, normals, groups, material = [], [], {}, "default"
    mtllib = None
    for line in args.obj.read_text().splitlines():
        if line.startswith("v "):
            positions.append([float(x) for x in line.split()[1:4]])
        elif line.startswith("vn "):
            normals.append([float(x) for x in line.split()[1:4]])
        elif line.startswith("usemtl "):
            material = line.split()[1]
        elif line.startswith("mtllib "):
            mtllib = line.split(maxsplit=1)[1].strip()
        elif line.startswith("f "):
            corners = [c.split("/") for c in line.split()[1:]]
            vi = [int(c[0]) - 1 for c in corners]
            ni = [int(c[2]) - 1 if len(c) > 2 and c[2] else vi[k] for k, c in enumerate(corners)]
            for k in range(1, len(vi) - 1):  # fan-triangulate
                groups.setdefault(material, []).append(((vi[0], ni[0]), (vi[k], ni[k]), (vi[k + 1], ni[k + 1])))
    colours = read_mtl(args.obj.parent / mtllib) if mtllib else {}
    pos = np.array(positions, np.float32) * args.scale
    nrm = np.array(normals, np.float32) if normals else None

    binary = b""
    views, accessors, primitives, materials = [], [], [], []

    def add(data: np.ndarray, kind: str, component: int, target: int, minmax: bool = False) -> int:
        nonlocal binary
        raw = data.tobytes()
        views.append({"buffer": 0, "byteOffset": len(binary), "byteLength": len(raw), "target": target})
        binary += raw + b"\0" * (-len(raw) % 4)
        acc = {"bufferView": len(views) - 1, "componentType": component, "count": len(data), "type": kind}
        if minmax:
            acc.update(min=data.min(0).tolist(), max=data.max(0).tolist())
        accessors.append(acc)
        return len(accessors) - 1

    for name, tris in groups.items():
        corners = np.array([c for t in tris for c in t])  # (n*3, 2): vertex index, normal index
        unique, inverse = np.unique(corners, axis=0, return_inverse=True)
        attributes = {"POSITION": add(pos[unique[:, 0]], "VEC3", 5126, 34962, True)}
        if nrm is not None:
            attributes["NORMAL"] = add(nrm[unique[:, 1]], "VEC3", 5126, 34962)
        indices = add(inverse.reshape(-1).astype(np.uint32), "SCALAR", 5125, 34963)
        r, g, b = colours.get(name, (0.8, 0.8, 0.8))
        materials.append({"name": name, "pbrMetallicRoughness": {"baseColorFactor": [r, g, b, 1], "metallicFactor": 0,
                                                                 "roughnessFactor": 0.7}})
        primitives.append({"attributes": attributes, "indices": indices, "material": len(materials) - 1})

    gltf = {"asset": {"version": "2.0", "generator": "TheTunnelAsset tools/obj_mtl_to_glb.py"},
            "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0, "name": args.obj.stem}],
            "meshes": [{"name": args.obj.stem, "primitives": primitives}], "materials": materials,
            "buffers": [{"byteLength": len(binary)}], "bufferViews": views, "accessors": accessors}
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    body = struct.pack("<I4s", len(js), b"JSON") + js + struct.pack("<I4s", len(binary), b"BIN\0") + binary
    args.out.write_bytes(struct.pack("<4sII", b"glTF", 2, 12 + len(body)) + body)
    print(f"{args.out}: {sum(len(t) for t in groups.values())} triangles, {len(groups)} materials")


if __name__ == "__main__":
    main()
