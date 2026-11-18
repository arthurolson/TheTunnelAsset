"""Make a lighter copy of a molecular glb for headsets: every placed mesh in the model's frame, each mesh's vertices
merged on a grid (the average position and normal of the vertices in a cell, the first one's colour), triangles that
collapse dropped. The grid starts at --cell Angstroms and grows until the model is under --target vertices. This is the
same grid merge The Tunnel does when it makes a molecule's toy, done ahead of time so a headset doesn't have to.

    python3 tools/glb_grid_simplify.py molecule/assemblies/big.glb molecule/assemblies/big_quest.glb [--target 180000]

Needs numpy.
"""

from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

import numpy as np

COMPONENTS = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


def read(path: Path):
    data = path.read_bytes()
    n = struct.unpack("<I", data[12:16])[0]
    gltf = json.loads(data[20:20 + n])
    return gltf, data[20 + n + 8:]


def accessor(gltf, binary, index, as_float=True):
    a = gltf["accessors"][index]
    view = gltf["bufferViews"][a["bufferView"]]
    dtype = np.dtype(COMPONENTS[a["componentType"]])
    width = WIDTH[a["type"]]
    stride = view.get("byteStride", 0) or dtype.itemsize * width
    rows = np.ndarray((a["count"], width), dtype, binary, view.get("byteOffset", 0) + a.get("byteOffset", 0), (stride, dtype.itemsize))
    if not as_float:
        return rows.copy()
    out = rows.astype(np.float32)
    if a.get("normalized") and dtype.kind in "ui":
        out /= np.iinfo(dtype).max
    return out


def placements(gltf):
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from build_manifest import node_matrices
    return node_matrices(gltf)


def gather(gltf, binary):
    """Per mesh: positions, normals, colours (0-255 RGBA) and triangles, all its placements together."""
    parts = {}
    for mesh_index, m in placements(gltf):
        m = np.array(m, np.float64)
        for p in gltf["meshes"][mesh_index]["primitives"]:
            if p.get("mode", 4) != 4:
                continue
            pos = accessor(gltf, binary, p["attributes"]["POSITION"])
            nrm = accessor(gltf, binary, p["attributes"]["NORMAL"]) if "NORMAL" in p["attributes"] else np.zeros_like(pos)
            if "COLOR_0" in p["attributes"]:
                col = accessor(gltf, binary, p["attributes"]["COLOR_0"])
                col = np.hstack([col[:, :3], np.ones((len(col), 1), np.float32)]) if col.shape[1] == 3 else col
            else:
                mat = gltf.get("materials", [{}])[p["material"]] if "material" in p else {}
                col = np.tile(np.array(mat.get("pbrMetallicRoughness", {}).get("baseColorFactor", [1, 1, 1, 1]), np.float32), (len(pos), 1))
            idx = accessor(gltf, binary, p["indices"], as_float=False).reshape(-1).astype(np.int64) if "indices" in p else np.arange(len(pos))
            world = pos @ m[:3, :3].T.astype(np.float32) + m[:3, 3].astype(np.float32)
            normals = nrm @ m[:3, :3].T.astype(np.float32)
            entry = parts.setdefault(mesh_index, {"p": [], "n": [], "c": [], "t": [], "count": 0})
            entry["t"].append(idx[: len(idx) // 3 * 3].reshape(-1, 3) + entry["count"])
            entry["p"].append(world)
            entry["n"].append(normals)
            entry["c"].append(np.round(col * 255).astype(np.uint8))
            entry["count"] += len(pos)
    return [{k: np.concatenate(v) for k, v in e.items() if k != "count"} for e in parts.values()]


def merge(part, cell):
    keys = np.floor(part["p"] / cell).astype(np.int64)
    _, first, inverse = np.unique(keys, axis=0, return_index=True, return_inverse=True)
    inverse = inverse.reshape(-1)
    count = np.bincount(inverse).astype(np.float32)[:, None]
    positions = np.zeros((len(first), 3), np.float32)
    normals = np.zeros((len(first), 3), np.float32)
    np.add.at(positions, inverse, part["p"])
    np.add.at(normals, inverse, part["n"])
    positions /= count
    normals /= np.linalg.norm(normals, axis=1, keepdims=True).clip(1e-12)
    colours = part["c"][first]
    t = inverse[part["t"]]
    t = t[(t[:, 0] != t[:, 1]) & (t[:, 1] != t[:, 2]) & (t[:, 0] != t[:, 2])]
    # The same triangle once, whichever corner it starts at (orientation kept).
    roll = np.argmin(t, axis=1)
    canon = np.take_along_axis(t, (roll[:, None] + np.arange(3)) % 3, axis=1)
    _, keep = np.unique(canon, axis=0, return_index=True)
    return positions, normals, colours, t[np.sort(keep)]


def write(path, parts, generator):
    binary, views, accessors, primitives = b"", [], [], []

    def add(arr, kind, component, target, minmax=False, normalized=False):
        nonlocal binary
        raw = arr.tobytes()
        views.append({"buffer": 0, "byteOffset": len(binary), "byteLength": len(raw), "target": target})
        binary += raw + b"\0" * (-len(raw) % 4)
        acc = {"bufferView": len(views) - 1, "componentType": component, "count": len(arr), "type": kind}
        if minmax:
            acc.update(min=arr.min(0).tolist(), max=arr.max(0).tolist())
        if normalized:
            acc["normalized"] = True
        accessors.append(acc)
        return len(accessors) - 1

    for positions, normals, colours, tris in parts:
        primitives.append({"attributes": {
            "POSITION": add(positions.astype("<f4"), "VEC3", 5126, 34962, True),
            "NORMAL": add(normals.astype("<f4"), "VEC3", 5126, 34962),
            "COLOR_0": add(colours.astype(np.uint8), "VEC4", 5121, 34962, normalized=True)},
            "indices": add(tris.reshape(-1).astype("<u4"), "SCALAR", 5125, 34963), "material": 0})
    gltf = {"asset": {"version": "2.0", "generator": generator}, "scene": 0, "scenes": [{"nodes": list(range(len(primitives)))}],
            "nodes": [{"mesh": i} for i in range(len(primitives))],
            "meshes": [{"primitives": [p]} for p in primitives],
            "materials": [{"pbrMetallicRoughness": {"baseColorFactor": [1, 1, 1, 1], "metallicFactor": 0, "roughnessFactor": 0.7}}],
            "buffers": [{"byteLength": len(binary)}], "bufferViews": views, "accessors": accessors}
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    body = struct.pack("<I4s", len(js), b"JSON") + js + struct.pack("<I4s", len(binary), b"BIN\0") + binary
    path.write_bytes(struct.pack("<4sII", b"glTF", 2, 12 + len(body)) + body)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("src", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--target", type=int, default=180_000, help="most vertices in the copy")
    parser.add_argument("--cell", type=float, default=2.0, help="the finest grid tried (model units, Angstroms)")
    args = parser.parse_args()
    gltf, binary = read(args.src)
    parts = gather(gltf, binary)
    total = sum(len(p["p"]) for p in parts)
    cell = max(args.cell, 0.7 * (total / args.target) ** 0.5 * args.cell / 2.0)
    while True:
        merged = [merge(p, cell) for p in parts]
        vertices = sum(len(m[0]) for m in merged)
        if vertices <= args.target:
            break
        cell *= 1.2
    write(args.out, merged, f"TheTunnelAsset tools/glb_grid_simplify.py (from {args.src.name}, {cell:.1f} unit grid)")
    print(f"{args.out}: {total:,} vertices -> {vertices:,}, {sum(len(m[3]) for m in merged):,} triangles, {cell:.1f} unit grid")


if __name__ == "__main__":
    main()
