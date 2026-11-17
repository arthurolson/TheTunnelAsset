"""Pick sharp frames from a video for photogrammetry.

Extracts frames with ffmpeg at FPS, scores each by variance of the Laplacian (sharpness) and
copies all but the blurriest DROP fraction to out_dir.
Usage: python tools/select_frames.py in.mov out_dir [fps=10] [drop=0.2]
Requires ffmpeg on PATH, numpy, pillow, scipy.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

src, out = sys.argv[1], Path(sys.argv[2])
fps = float(sys.argv[3]) if len(sys.argv) > 3 else 10
drop = float(sys.argv[4]) if len(sys.argv) > 4 else 0.2
allf = out.parent / (out.name + "_all")
allf.mkdir(parents=True, exist_ok=True)
out.mkdir(parents=True, exist_ok=True)
subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", src, "-vf", f"fps={fps}",
                "-q:v", "2", str(allf / "%04d.jpg")], check=True)
frames = sorted(allf.glob("*.jpg"))
score = []
for f in frames:
    g = np.asarray(Image.open(f).convert("L").reduce(2), dtype=np.float32)
    score.append(ndi.laplace(g).var())
cut = np.quantile(score, drop)
kept = [f for f, s in zip(frames, score) if s >= cut]
for f in kept:
    shutil.copy2(f, out / f.name)
print(f"{len(frames)} frames, kept {len(kept)} (sharpness >= {cut:.1f}) in {out}")
