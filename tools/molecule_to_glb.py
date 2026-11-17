"""Make a ready-to-show glb from a PDB or mmCIF atomic model: one sphere per atom (spacefill), coloured by element,
with soft shading baked into the vertex colours so it reads well in viewers that draw it unlit (as The Tunnel does).

    python3 tools/molecule_to_glb.py molecule/1crn.cif molecule/1crn_spacefill.glb [--color chain] [--detail 1]

Coordinates stay in Angstroms (glTF y-up, the model's own frame), centred on the origin; the sidecar's
"coordinates": "angstrom" tells the app the scale (1 unit = 1e-10 m). Only the first model is used; waters are skipped.
Needs numpy.
"""

from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

import numpy as np

# Van der Waals radii (Angstroms) and CPK-like colours.
RADII = {"H": 1.10, "C": 1.70, "N": 1.55, "O": 1.52, "S": 1.80, "P": 1.80, "SE": 1.90, "FE": 1.40, "ZN": 1.39,
         "MG": 1.73, "CA": 1.97, "CL": 1.75, "NA": 2.27, "K": 2.75}
COLORS = {"H": (0.95, 0.95, 0.95), "C": (0.55, 0.55, 0.55), "N": (0.19, 0.31, 0.97), "O": (0.94, 0.16, 0.12),
          "S": (1.0, 0.78, 0.2), "P": (1.0, 0.5, 0.0), "SE": (1.0, 0.63, 0.0), "FE": (0.88, 0.4, 0.2)}
CHAIN_COLORS = [(0.40, 0.65, 0.95), (0.95, 0.55, 0.35), (0.55, 0.85, 0.45), (0.85, 0.45, 0.85), (0.95, 0.85, 0.35),
                (0.35, 0.85, 0.85), (0.95, 0.45, 0.55), (0.65, 0.55, 0.95)]


def read_atoms(path: Path) -> list[tuple[float, float, float, str, str]]:
    atoms = []
    if path.suffix.lower() == ".pdb":
        for line in path.read_text(errors="replace").splitlines():
            if line.startswith("ENDMDL"):
                break
            if line.startswith(("ATOM  ", "HETATM")) and line[17:20].strip() != "HOH":
                element = (line[76:78].strip() or line[12:14].strip()).upper()
                atoms.append((float(line[30:38]), float(line[38:46]), float(line[46:54]), element, line[21]))
        return atoms
    columns: list[str] = []
    reading = False
    for line in path.read_text(errors="replace").splitlines():
        s = line.strip()
        if s.startswith("_atom_site."):
            columns.append(s.split()[0][len("_atom_site."):])
            continue
        if columns and not reading and not s.startswith("_"):
            reading = True
        if reading:
            if not s or s.startswith(("#", "loop_", "_")):
                break
            v = s.split()
            col = {name: v[i] for i, name in enumerate(columns) if i < len(v)}
            if col.get("pdbx_PDB_model_num", "1") != "1" or col.get("label_comp_id") == "HOH":
                continue
            atoms.append((float(col["Cartn_x"]), float(col["Cartn_y"]), float(col["Cartn_z"]),
                          col.get("type_symbol", "C").upper(), col.get("auth_asym_id", col.get("label_asym_id", "A"))))
    return atoms


def icosphere(detail: int) -> tuple[np.ndarray, np.ndarray]:
    t = (1 + 5 ** 0.5) / 2
    v = [(-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0), (0, -1, t), (0, 1, t), (0, -1, -t), (0, 1, -t),
         (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1)]
    f = [(0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11), (1, 5, 9), (5, 11, 4), (11, 10, 2), (10, 7, 6),
         (7, 1, 8), (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9), (4, 9, 5), (2, 4, 11), (6, 2, 10),
         (8, 6, 7), (9, 8, 1)]
    verts = [np.array(p, float) / np.linalg.norm(p) for p in v]
    for _ in range(detail):
        cache: dict[tuple[int, int], int] = {}

        def mid(a: int, b: int) -> int:
            key = (min(a, b), max(a, b))
            if key not in cache:
                m = verts[a] + verts[b]
                verts.append(m / np.linalg.norm(m))
                cache[key] = len(verts) - 1
            return cache[key]

        nf = []
        for a, b, c in f:
            ab, bc, ca = mid(a, b), mid(b, c), mid(c, a)
            nf += [(a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)]
        f = nf
    return np.array(verts, np.float32), np.array(f, np.uint32)


def write_glb(path: Path, positions: np.ndarray, colors: np.ndarray, indices: np.ndarray, name: str) -> None:
    pos = positions.astype("<f4").tobytes()
    col = colors.astype("<u1").tobytes()
    idx = indices.astype("<u4").tobytes()

    def pad(b: bytes) -> bytes:
        return b + b"\0" * (-len(b) % 4)

    binary = pad(pos) + pad(col) + pad(idx)
    o_col, o_idx = len(pad(pos)), len(pad(pos)) + len(pad(col))
    gltf = {
        "asset": {"version": "2.0", "generator": "TheTunnelAsset tools/molecule_to_glb.py"},
        "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0, "name": name}],
        "meshes": [{"name": name, "primitives": [{"attributes": {"POSITION": 0, "COLOR_0": 1}, "indices": 2, "material": 0}]}],
        "materials": [{"name": "baked", "pbrMetallicRoughness": {"metallicFactor": 0, "roughnessFactor": 1},
                       "extensions": {"KHR_materials_unlit": {}}}],
        "extensionsUsed": ["KHR_materials_unlit"],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(pos), "target": 34962},
                        {"buffer": 0, "byteOffset": o_col, "byteLength": len(col), "target": 34962},
                        {"buffer": 0, "byteOffset": o_idx, "byteLength": len(idx), "target": 34963}],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": len(positions), "type": "VEC3",
             "min": positions.min(0).tolist(), "max": positions.max(0).tolist()},
            {"bufferView": 1, "componentType": 5121, "normalized": True, "count": len(colors), "type": "VEC4"},
            {"bufferView": 2, "componentType": 5125, "count": indices.size, "type": "SCALAR"}],
    }
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    body = struct.pack("<I4s", len(js), b"JSON") + js + struct.pack("<I4s", len(binary), b"BIN\0") + binary
    path.write_bytes(struct.pack("<4sII", b"glTF", 2, 12 + len(body)) + body)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("model", type=Path, help=".pdb or .cif")
    parser.add_argument("out", type=Path, help=".glb to write")
    parser.add_argument("--color", choices=["element", "chain"], default="element")
    parser.add_argument("--detail", type=int, default=1, help="sphere subdivisions (1: 80 triangles per atom)")
    args = parser.parse_args()

    atoms = read_atoms(args.model)
    if not atoms:
        raise SystemExit(f"no atoms in {args.model}")
    centres = np.array([a[:3] for a in atoms], np.float32)
    centres -= centres.mean(0)
    unit, faces = icosphere(args.detail)
    light = np.array([0.4, 0.8, 0.45]) / np.linalg.norm([0.4, 0.8, 0.45])
    shade = 0.45 + 0.55 * np.clip(unit @ light, 0, 1)  # baked: ambient plus one soft light from above front
    chains = sorted({a[4] for a in atoms})
    positions, colors, indices = [], [], []
    for i, (x, y, z, element, chain) in enumerate(atoms):
        radius = RADII.get(element, 1.7)
        base = np.array(CHAIN_COLORS[chains.index(chain) % len(CHAIN_COLORS)] if args.color == "chain"
                        else COLORS.get(element, (0.8, 0.5, 0.8)))
        positions.append(unit * radius + centres[i])
        rgb = np.clip(base[None, :] * shade[:, None], 0, 1)
        colors.append(np.hstack([rgb * 255, np.full((len(unit), 1), 255)]).round())
        indices.append(faces + i * len(unit))
    positions_a = np.vstack(positions)
    write_glb(args.out, positions_a, np.vstack(colors), np.vstack(indices), args.model.stem)
    size = positions_a.max(0) - positions_a.min(0)
    print(f"{args.out}: {len(atoms)} atoms, {len(positions_a)} vertices, {sum(len(f) for f in indices)} triangles, "
          f"{size[0]:.0f} x {size[1]:.0f} x {size[2]:.0f} A")


if __name__ == "__main__":
    main()
