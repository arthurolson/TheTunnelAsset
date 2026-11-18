"""Draw a thumbnail of a glb: its triangles seen from the front (+Z, toward the viewer), in their vertex colours or
material colours, with simple shading, on a dark background. For assets that have no picture of their own.

    python3 tools/glb_thumbnail.py mesh/foo.glb thumbs/foo.jpg [--max-triangles 300000] [--views 4]

--views 4 draws it from the front, right, back and left side by side (960 x 360), for full 3D models.

Handles node transforms (so instanced capsids come out whole), indexed or not, uint8/uint16/float colours.
Very large meshes are drawn from a sample of their triangles. Needs numpy and Pillow.
"""

from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

SIZE = (480, 360)
COMPONENTS = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def read_glb(path: Path) -> tuple[dict, bytes]:
    data = path.read_bytes()
    n = struct.unpack("<I", data[12:16])[0]
    gltf = json.loads(data[20:20 + n])
    binary = data[20 + n + 8:] if len(data) > 20 + n else b""
    return gltf, binary


def accessor(gltf: dict, binary: bytes, index: int) -> np.ndarray:
    a = gltf["accessors"][index]
    view = gltf["bufferViews"][a["bufferView"]]
    dtype = np.dtype(COMPONENTS[a["componentType"]])
    width = WIDTH[a["type"]]
    stride = view.get("byteStride", 0) or dtype.itemsize * width
    start = view.get("byteOffset", 0) + a.get("byteOffset", 0)
    rows = np.ndarray((a["count"], width), dtype, binary, start, (stride, dtype.itemsize))
    out = rows.astype(np.float32)
    if a.get("normalized") and dtype.kind in "ui":
        out /= np.iinfo(dtype).max
    return out


def texture_image(gltf: dict, binary: bytes, texture: int) -> np.ndarray:
    """A glb's embedded texture as RGB floats 0-1."""
    import io

    image = gltf["images"][gltf["textures"][texture]["source"]]
    view = gltf["bufferViews"][image["bufferView"]]
    start = view.get("byteOffset", 0)
    with Image.open(io.BytesIO(binary[start:start + view["byteLength"]])) as im:
        im = im.convert("RGB")
        im.thumbnail((1024, 1024))
        return np.asarray(im, np.float32) / 255.0


def node_matrix(node: dict) -> np.ndarray:
    if "matrix" in node:
        return np.array(node["matrix"], np.float64).reshape(4, 4).T
    t = np.array(node.get("translation", [0, 0, 0]))
    x, y, z, w = node.get("rotation", [0, 0, 0, 1])
    s = np.array(node.get("scale", [1, 1, 1]))
    r = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                  [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                  [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    m = np.eye(4)
    m[:3, :3] = r * s
    m[:3, 3] = t
    return m


def triangles(gltf: dict, binary: bytes) -> tuple[np.ndarray, np.ndarray]:
    """All triangles in the scene (world positions, n x 3 x 3) and their colours (n x 3)."""
    meshes: dict[int, list[tuple[np.ndarray, np.ndarray]]] = {}
    for mi, mesh in enumerate(gltf.get("meshes", [])):
        prims = []
        for p in mesh["primitives"]:
            if p.get("mode", 4) != 4:
                continue
            pos = accessor(gltf, binary, p["attributes"]["POSITION"])
            idx = accessor(gltf, binary, p["indices"]).astype(np.int64).reshape(-1) if "indices" in p else np.arange(len(pos))
            tris = idx[: len(idx) // 3 * 3].reshape(-1, 3)
            mat = gltf.get("materials", [{}])[p["material"]] if "material" in p else {}
            texture = mat.get("pbrMetallicRoughness", {}).get("baseColorTexture")
            if "COLOR_0" in p["attributes"]:
                col = accessor(gltf, binary, p["attributes"]["COLOR_0"])[:, :3]
                colour = col[tris].mean(1)
            elif texture is not None and "TEXCOORD_0" in p["attributes"]:
                # The texture at each triangle's middle (sRGB, made linear like vertex colours).
                image = texture_image(gltf, binary, texture["index"])
                uv = accessor(gltf, binary, p["attributes"]["TEXCOORD_0"])[tris].mean(1) % 1.0
                h, w = image.shape[:2]
                colour = image[(uv[:, 1] * (h - 1)).astype(int), (uv[:, 0] * (w - 1)).astype(int)] ** 2.2
            else:
                mat = gltf.get("materials", [{}])[p["material"]] if "material" in p else {}
                base = mat.get("pbrMetallicRoughness", {}).get("baseColorFactor", [0.8, 0.8, 0.8, 1])
                colour = np.tile(np.array(base[:3], np.float32), (len(tris), 1))
            prims.append((pos[tris], colour))
        meshes[mi] = prims

    out_t, out_c = [], []

    def walk(ni: int, parent: np.ndarray) -> None:
        node = gltf["nodes"][ni]
        m = parent @ node_matrix(node)
        for tri, col in meshes.get(node.get("mesh", -1), []):
            flat = tri.reshape(-1, 3) @ m[:3, :3].T + m[:3, 3]
            out_t.append(flat.reshape(-1, 3, 3).astype(np.float32))
            out_c.append(col)
        for child in node.get("children", []):
            walk(child, m)

    scene = gltf.get("scenes", [{"nodes": list(range(len(gltf.get("nodes", []))))}])[gltf.get("scene", 0)]
    for root in scene["nodes"]:
        walk(root, np.eye(4))
    return np.concatenate(out_t), np.concatenate(out_c)


def render(tris: np.ndarray, colours: np.ndarray, out: Path | None, max_triangles: int, size=SIZE) -> Image.Image:
    global SIZE
    SIZE = size
    if len(tris) > max_triangles:
        keep = np.random.default_rng(0).choice(len(tris), max_triangles, replace=False)
        tris, colours = tris[keep], colours[keep]
    normals = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    normals /= np.linalg.norm(normals, axis=1, keepdims=True).clip(1e-12)
    light = np.array([0.35, 0.6, 0.72])
    light /= np.linalg.norm(light)
    shade = 0.35 + 0.65 * np.abs(normals @ light)  # both sides lit: windings vary between exporters
    lo, hi = tris.reshape(-1, 3).min(0), tris.reshape(-1, 3).max(0)
    scale = min(SIZE[0] / max(hi[0] - lo[0], 1e-9), SIZE[1] / max(hi[1] - lo[1], 1e-9)) * 0.9
    cx, cy = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2
    xy = np.empty(tris.shape[:2] + (2,))
    xy[..., 0] = SIZE[0] / 2 + (tris[..., 0] - cx) * scale
    xy[..., 1] = SIZE[1] / 2 - (tris[..., 1] - cy) * scale
    order = np.argsort(tris[..., 2].mean(1))  # far (low z) first; +Z faces the viewer
    rgb = np.clip(colours * shade[:, None], 0, 1)
    # Linear vertex colours (glTF) to sRGB for the picture.
    rgb = np.where(rgb <= 0.0031308, rgb * 12.92, 1.055 * np.power(rgb, 1 / 2.4) - 0.055)
    im = Image.new("RGB", SIZE, (16, 16, 18))
    d = ImageDraw.Draw(im)
    for i in order:
        c = tuple(int(v * 255) for v in rgb[i])
        d.polygon([tuple(p) for p in xy[i]], fill=c)
    if out is not None:
        im.save(out, quality=88)
    return im


def turned(tris: np.ndarray, degrees: float) -> np.ndarray:
    """The triangles turned about the vertical (y) axis, as if walking round the model."""
    a = np.radians(degrees)
    r = np.array([[np.cos(a), 0, np.sin(a)], [0, 1, 0], [-np.sin(a), 0, np.cos(a)]], np.float32)
    return tris @ r.T


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("glb", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--max-triangles", type=int, default=300_000)
    parser.add_argument("--views", type=int, choices=[1, 4], default=1)
    args = parser.parse_args()
    gltf, binary = read_glb(args.glb)
    tris, colours = triangles(gltf, binary)
    if args.views == 1:
        render(tris, colours, args.out, args.max_triangles)
    else:
        sheet = Image.new("RGB", (960, 360), (16, 16, 18))
        for k, degrees in enumerate((0, 90, 180, 270)):
            sheet.paste(render(turned(tris, degrees), colours, None, args.max_triangles, (240, 360)), (240 * k, 0))
        sheet.save(args.out, quality=88)
    print(f"{args.out}: {len(tris)} triangles drawn{' (sampled)' if len(tris) > args.max_triangles else ''}")


if __name__ == "__main__":
    main()
