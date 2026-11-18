"""Drop repeated placements from a glb: nodes that place the same mesh with the same transform as another node.
Some exports (Mol* with an assembly whose operators are all the identity) place one mesh many times in exactly the
same spot, which multiplies what a viewer draws for nothing. Only the glTF's JSON changes; the geometry is untouched.

    python3 tools/glb_dedupe_nodes.py in.glb out.glb
"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path


def main() -> None:
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    data = src.read_bytes()
    n = struct.unpack("<I", data[12:16])[0]
    gltf = json.loads(data[20:20 + n])
    rest = data[20 + n:]  # the BIN chunk, as it is

    nodes = gltf.get("nodes", [])
    seen, keep = set(), []
    for i, node in enumerate(nodes):
        if node.get("children"):
            keep.append(i)  # a node with children is kept: only leaf placements are compared
            continue
        key = (node.get("mesh"), json.dumps({k: node[k] for k in ("matrix", "translation", "rotation", "scale") if k in node}, sort_keys=True))
        if node.get("mesh") is not None and key in seen:
            continue
        seen.add(key)
        keep.append(i)
    remap = {old: new for new, old in enumerate(keep)}
    gltf["nodes"] = [nodes[i] for i in keep]
    for node in gltf["nodes"]:
        if "children" in node:
            node["children"] = [remap[c] for c in node["children"] if c in remap]
    for scene in gltf.get("scenes", []):
        scene["nodes"] = [remap[c] for c in scene.get("nodes", []) if c in remap]
    if "scenes" in gltf and "scene" not in gltf:
        gltf["scene"] = 0  # name the default, so every viewer shows it

    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    body = struct.pack("<I4s", len(js), b"JSON") + js + rest
    dst.write_bytes(struct.pack("<4sII", b"glTF", 2, 12 + len(body)) + body)
    print(f"{dst}: {len(nodes)} nodes -> {len(keep)} ({len(nodes) - len(keep)} repeated placements dropped)")


if __name__ == "__main__":
    main()
