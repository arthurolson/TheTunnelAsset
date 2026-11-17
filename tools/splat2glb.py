"""Splat-look mesh: one flat quad per Gaussian (2 largest axes, +-SIGMA std), unlit vertex colors.

Usage: python tools/splat2glb.py in.ply out.glb [sigma=1.6] [target_splats=0] [copyright]
target_splats > 0 voxel-decimates (keeps the most visible splat per cell, enlarges it) -
e.g. 100000 gave the 290k-tri Quest version of Scripps 1924.
Input is an OpenCV-convention 3DGS .ply (SHARP); output is glTF y-up.
"""
import sys, json, struct, numpy as np
from plyfile import PlyData
src, dst = sys.argv[1], sys.argv[2]
COPYRIGHT = sys.argv[5] if len(sys.argv) > 5 else ""
SIGMA = float(sys.argv[3]) if len(sys.argv) > 3 else 1.6
v = PlyData.read(src)['vertex'].data
op = 1/(1+np.exp(-v['opacity']))
v = v[op > 0.2]; op = op[op > 0.2]
TARGET = int(sys.argv[4]) if len(sys.argv) > 4 else 0
if TARGET and len(v) > TARGET:
    sc = np.exp(np.stack([v['scale_0'], v['scale_1'], v['scale_2']], 1)); sc.sort(1)
    imp = op * sc[:, 2] * sc[:, 1]                       # visible area
    pos = np.stack([v['x'], v['y'], v['z']], 1)
    lo, hi = 0.0, 2.0
    for _ in range(25):                                  # voxel size giving ~TARGET occupied cells
        vox = (lo + hi) / 2
        key = np.unique(np.floor(pos / vox).astype(np.int64), axis=0, return_inverse=True)[1].ravel()
        m = key.max() + 1
        if abs(m - TARGET) < 0.03 * TARGET: break
        lo, hi = (vox, hi) if m > TARGET else (lo, vox)
    ordr = np.lexsort((-imp, key)); first = np.r_[True, key[ordr][1:] != key[ordr][:-1]]
    keep = ordr[first]
    counts = np.bincount(key, minlength=m)[key[keep]]
    v = v[keep]
    grow = np.clip(np.sqrt(counts), 1, 2.5)              # enlarge kept splats for the ones they replace
    for c_ in ('scale_0', 'scale_1', 'scale_2'): v[c_] = v[c_] + np.log(grow).astype(np.float32)
    print(f'decimated to {len(v)} splats with voxel {vox:.3f} m')
n = len(v)
c = np.stack([v['x'], v['y'], v['z']], 1).astype(np.float64)
s = np.exp(np.stack([v['scale_0'], v['scale_1'], v['scale_2']], 1))
q = np.stack([v['rot_0'], v['rot_1'], v['rot_2'], v['rot_3']], 1); q /= np.linalg.norm(q, axis=1, keepdims=True)
w, x, y, z = q.T
R = np.stack([
    np.stack([1-2*(y*y+z*z), 2*(x*y-w*z), 2*(x*z+w*y)], -1),
    np.stack([2*(x*y+w*z), 1-2*(x*x+z*z), 2*(y*z-w*x)], -1),
    np.stack([2*(x*z-w*y), 2*(y*z+w*x), 1-2*(x*x+y*y)], -1)], 1)   # (n,3,3), columns = local axes
order = np.argsort(-s, axis=1)                    # two largest axes span the flat splat
ia, ib = order[:, 0], order[:, 1]
ar = np.arange(n)
A = R[ar, :, ia] * (SIGMA * s[ar, ia])[:, None]
B = R[ar, :, ib] * (SIGMA * s[ar, ib])[:, None]
corners = np.stack([c - A - B, c + A - B, c + A + B, c - A + B], 1)   # (n,4,3)
P = corners.reshape(-1, 3)
P[:, 1] *= -1; P[:, 2] *= -1                      # OpenCV (y down, z fwd) -> glTF (y up)
P = P.astype(np.float32)
# colour: SH DC -> sRGB -> linear (glTF vertex colours are linear)
srgb = np.clip(0.5 + 0.28209479*np.stack([v['f_dc_0'], v['f_dc_1'], v['f_dc_2']], 1), 0, 1)
lin = np.where(srgb <= 0.04045, srgb/12.92, ((srgb+0.055)/1.055)**2.4)
col = np.repeat((lin*255+0.5).astype(np.uint8), 4, axis=0)
col = np.c_[col, np.full(len(col), 255, np.uint8)]
base = (np.arange(n, dtype=np.uint32)*4)[:, None]
idx = (base + np.array([0, 1, 2, 0, 2, 3], np.uint32)).ravel()

def pad4(b, fill=b'\x00'): return b + fill*((4 - len(b) % 4) % 4)
bp, bc, bi = P.tobytes(), col.tobytes(), idx.tobytes()
bin_ = pad4(bp) ; oc = len(bin_); bin_ += pad4(bc); oi = len(bin_); bin_ += pad4(bi)
gltf = {
  "asset": {"version": "2.0", "generator": "splat2glb (quads from Gaussian splats)",
            "copyright": COPYRIGHT},
  "extensionsUsed": ["KHR_materials_unlit"],
  "scene": 0, "scenes": [{"nodes": [0]}],
  "nodes": [{"mesh": 0, "name": "splat_quads"}],
  "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "COLOR_0": 1}, "indices": 2, "material": 0, "mode": 4}]}],
  "materials": [{"name": "splat_vertex_color", "doubleSided": True,
                 "pbrMetallicRoughness": {"baseColorFactor": [1, 1, 1, 1], "metallicFactor": 0, "roughnessFactor": 1},
                 "extensions": {"KHR_materials_unlit": {}}}],
  "buffers": [{"byteLength": len(bin_)}],
  "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(bp), "target": 34962},
                  {"buffer": 0, "byteOffset": oc, "byteLength": len(bc), "target": 34962},
                  {"buffer": 0, "byteOffset": oi, "byteLength": len(bi), "target": 34963}],
  "accessors": [{"bufferView": 0, "componentType": 5126, "count": len(P), "type": "VEC3",
                 "min": P.min(0).tolist(), "max": P.max(0).tolist()},
                {"bufferView": 1, "componentType": 5121, "normalized": True, "count": len(col), "type": "VEC4"},
                {"bufferView": 2, "componentType": 5125, "count": len(idx), "type": "SCALAR"}]}
js = pad4(json.dumps(gltf, separators=(',', ':')).encode(), b' ')
total = 12 + 8 + len(js) + 8 + len(bin_)
with open(dst, 'wb') as fh:
    fh.write(struct.pack('<III', 0x46546C67, 2, total))
    fh.write(struct.pack('<II', len(js), 0x4E4F534A)); fh.write(js)
    fh.write(struct.pack('<II', len(bin_), 0x004E4942)); fh.write(bin_)
print(f'{n} splats -> {len(P)} verts, {len(idx)//3} tris, {total/1e6:.1f} MB; bounds {P.min(0).round(1)} .. {P.max(0).round(1)}')
