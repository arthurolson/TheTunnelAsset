"""EXAMPLE (scene-specific): how the Scripps 1924 splat was cleaned.

Removes sky Gaussians (from a sky mask .npy, bool HxW at the photo resolution), floaters, halo
and stretched edge Gaussians, then writes a no-sky version and one with the sky re-added as a
far inpainted backdrop plane. Thresholds were tuned for that photo; adapt them for others.
Usage: python tools/clean_splat_sky.py in.ply sky_mask.npy photo.jpg out_dir
"""
import sys, numpy as np
from plyfile import PlyData, PlyElement
from scipy import ndimage as ndi
from PIL import Image
src, maskp, photo, outdir = sys.argv[1:5]
sky0 = np.load(maskp); H, W = sky0.shape
# building/ground = non-sky regions connected to the lower part of the image
nonsky = ~sky0; nonsky[:14] = False
lab, n = ndi.label(nonsky)
ground_ids = set(np.unique(lab[int(0.6*H):, :])) - {0}
build = np.isin(lab, list(ground_ids))
skyline = np.argmax(build, axis=0)                      # first building row per column
skyline[~build.any(0)] = H
rows = np.arange(H)[:, None]
sky = rows < skyline[None, :]
sky = ndi.binary_dilation(sky, iterations=3)
Image.fromarray((sky*255).astype(np.uint8)).save(f'{outdir}/sky_mask_final.png')

ply = PlyData.read(src); v = ply['vertex'].data
K = np.array(ply['intrinsic'].data.tolist()).reshape(3, 3); f, cx, cy = K[0,0], K[0,2], K[1,2]
x, y, z = v['x'], v['y'], v['z']
u = np.round(f*x/z + cx).astype(int); w = np.round(f*y/z + cy).astype(int)
inside = (z > 0) & (u >= 0) & (u < W) & (w >= 0) & (w < H)
uc, wc = np.clip(u, 0, W-1), np.clip(w, 0, H-1)
opac = 1/(1+np.exp(-v['opacity']))
is_sky = inside & sky[wc, uc]
bad = (opac < 0.05) | ~inside | (uc < 28) | (uc > W-10) | (wc > H-7)
scene = ~is_sky & ~bad
# halo: Gaussians just under the skyline that are far closer than the wall below them
sl = skyline[uc]
band = scene & (wc < sl + 25)
ref = scene & (wc >= sl + 25) & (wc < sl + 90)
colmed = np.full(W, np.nan)
for c in range(W):
    zz = z[ref & (uc == c)]
    if len(zz): colmed[c] = np.median(zz)
colmed = ndi.generic_filter(np.nan_to_num(colmed, nan=np.nanmedian(colmed)), np.median, size=9)
halo = band & ((z < 0.7*colmed[uc]) | (z > 1.25*colmed[uc]))
# stretched edge Gaussians (rubber-sheet streaks between depth layers)
smax = np.exp(np.maximum(np.maximum(v['scale_0'], v['scale_1']), v['scale_2']))
smin = np.exp(np.minimum(np.minimum(v['scale_0'], v['scale_1']), v['scale_2']))
stretched = scene & (smax > 0.012*z) & (smax/smin > 8)
print('stretched', stretched.sum())
halo |= stretched
scene &= ~halo
print(f'total {len(v)}  sky {is_sky.sum()}  floaters/edge {(bad & ~is_sky).sum()}  halo {halo.sum()}  kept {scene.sum()}')

others = [e for e in ply.elements if e.name != 'vertex']
def save(arr, name):
    PlyData([PlyElement.describe(arr, 'vertex')] + others, text=False).write(f'{outdir}/{name}'); print('wrote', name, len(arr))
save(v[scene], 'scripps_clean_no_sky.ply')

# ---- far sky backdrop, inpainted behind the buildings
img = np.asarray(Image.open(photo).convert('RGB')).astype(float)/255
skyfill = sky.copy(); skyfill[int(0.62*H):] = False
skycore = ndi.binary_erosion(sky, iterations=6)
# calibrate photo colour -> f_dc using existing sky Gaussians
selc = is_sky & ~bad & (opac > 0.5)
pc = img[wc[selc], uc[selc]]
fdc = np.stack([v['f_dc_0'], v['f_dc_1'], v['f_dc_2']], 1)[selc]
A = np.c_[pc.mean(1), np.ones(selc.sum())]
coef = [np.linalg.lstsq(np.c_[pc[:, i], np.ones(len(pc))], fdc[:, i], rcond=None)[0] for i in range(3)]
# inpaint: nearest sky-core colour, then smooth the filled part
idx = ndi.distance_transform_edt(~skycore, return_indices=True)[1]
filled = img[idx[0], idx[1]]
soft = np.stack([ndi.gaussian_filter(filled[..., i], 12) for i in range(3)], -1)
backimg = np.where(skycore[..., None], img, soft)
step, pad = 2, 0.3
us = np.arange(-pad*W, (1+pad)*W, step); ws = np.arange(-0.15*H, 0.62*H, step)
UU, WW = np.meshgrid(us, ws)
col = backimg[np.clip(WW.astype(int), 0, H-1), np.clip(UU.astype(int), 0, W-1)]
build_z = z[scene & (wc < sl + 120)]
Z = np.percentile(build_z, 95) * 1.6
bk = np.zeros(UU.size, dtype=v.dtype)
bk['x'] = ((UU - cx) * Z / f).ravel(); bk['y'] = ((WW - cy) * Z / f).ravel(); bk['z'] = Z
for i in range(3): bk[f'f_dc_{i}'] = ((col[..., i] - 0.5) / 0.28209479).ravel()
bk['opacity'] = 6.0
s = np.log(step * Z / f * 0.75)
bk['scale_0'] = s; bk['scale_1'] = s; bk['scale_2'] = np.log(0.05 * step * Z / f)
bk['rot_0'] = 1.0
print(f'backdrop plane at z={Z:.1f} m, {len(bk)} Gaussians, colour fit slopes {[round(c[0],2) for c in coef]}')
save(np.concatenate([v[scene], bk]), 'scripps_clean_sky_backdrop.ply')
