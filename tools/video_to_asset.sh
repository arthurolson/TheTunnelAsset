#!/bin/zsh
# Pipeline B: an orbit video -> a full 3D model, in one command (a Mac with Apple silicon: Apple Object Capture).
#
#   tools/video_to_asset.sh orbit.mov --id art_standing --subject art --title "Art, standing" --height 1.80
#       [--tags person,full-body] [--detail medium|full|reduced] [--fps 10] [--drop 0.2]
#
# Writes mesh/<id>_fullbody.glb (real size, feet at y = 0) and mesh/<id>_fullbody.usdz (for iOS / visionOS Quick
# Look), a four-view thumbnail and a sidecar for each, then regenerates assets.json. Steps:
#   1. frames at --fps (ffmpeg), the blurriest --drop fraction left out   tools/select_frames.py
#   2. photogrammetry: sequential samples, high feature sensitivity, object masking   tools/object_capture.swift
#   3. USDZ -> OBJ with its textures (ModelIO)                              tools/usdz_to_obj.swift
#   4. OBJ -> GLB, scaled so it is --height meters tall, feet at y = 0     tools/obj_to_glb.py
# On Windows or Linux, run the same frames through RealityScan, Meshroom or COLMAP + OpenMVS, then steps 4 on.
# Python: the "sharp" conda environment's (PY=... to use another with numpy, scipy, Pillow, trimesh).
set -euo pipefail

ROOT=${0:A:h:h}
PY=${PY:-$HOME/miniforge3/envs/sharp/bin/python}
video="" id="" subject="" title="" height="" tags="" detail=medium fps=10 drop=0.2
while (( $# )); do
  case $1 in
    --id) id=$2; shift 2;;
    --subject) subject=$2; shift 2;;
    --title) title=$2; shift 2;;
    --height) height=$2; shift 2;;
    --tags) tags=$2; shift 2;;
    --detail) detail=$2; shift 2;;
    --fps) fps=$2; shift 2;;
    --drop) drop=$2; shift 2;;
    -*) print -u2 "unknown option $1"; exit 2;;
    *) video=${1:A}; shift;;
  esac
done
if [[ -z $video || -z $id || -z $subject || -z $title ]]; then
  print -u2 "usage: tools/video_to_asset.sh video.mov --id ID --subject S --title T [--height 1.80] [--tags a,b] [--detail medium]"
  exit 2
fi

work=$ROOT/.work/$id
mkdir -p $work
glb=$ROOT/mesh/${id}_fullbody.glb
usdz=$ROOT/mesh/${id}_fullbody.usdz
thumb=$ROOT/thumbs/${id}_fullbody.jpg
start=$SECONDS

print "1. frames"
rm -rf $work/frames $work/frames_all
$PY $ROOT/tools/select_frames.py $video $work/frames $fps $drop
frames=$(ls $work/frames | wc -l | tr -d ' ')

print "2. photogrammetry ($frames frames, detail $detail; a few minutes)"
rm -f $work/model.usdz
swift $ROOT/tools/object_capture.swift $work/frames $work/model.usdz $detail | grep -E "progress (25|50|75|100)%|saved|error|invalid|done" || true
[[ -f $work/model.usdz ]] || { print -u2 "Object Capture made no model"; exit 1; }

print "3. USDZ -> OBJ"
rm -rf $work/obj && mkdir -p $work/obj
swift $ROOT/tools/usdz_to_obj.swift $work/model.usdz $work/obj/model.obj

print "4. OBJ -> GLB${height:+, $height m tall}"
$PY $ROOT/tools/obj_to_glb.py $work/obj/model.obj $glb ${height:-}
cp $work/model.usdz $usdz
for f in $glb $usdz; do
  bytes=$(stat -f %z $f)
  if (( bytes > 95000000 )); then
    print -u2 "${f:t} is $((bytes / 1000000)) MB, over GitHub's limit: try --detail reduced, or host it elsewhere (see the README)"
    exit 1
  fi
done

print "5. thumbnail"
$PY $ROOT/tools/glb_thumbnail.py $glb $thumb --views 4

print "6. sidecars"
method=$(printf '{"name": "Apple Object Capture (RealityKit PhotogrammetrySession)", "detail": "%s", "frames": %s, "frames_per_second": %s, "blurriest_dropped": %s, "sample_ordering": "sequential", "feature_sensitivity": "high", "object_masking": true, "script": "tools/video_to_asset.sh"%s}' \
  $detail $frames $fps $drop "${height:+, \"height_m\": $height}")
coordinates=${height:+gltf-meters}
coordinates=${coordinates:-gltf}
$PY $ROOT/tools/asset_meta.py $glb --id ${id}_fullbody --subject $subject --title "$title, full 3D model" \
  --tags "${tags:+$tags,}full-body,360" --source "video (${video:t})" --method $method --coordinates $coordinates \
  --thumbnail thumbs/${id}_fullbody.jpg
$PY $ROOT/tools/asset_meta.py $usdz --id ${id}_fullbody_usdz --subject $subject --title "$title, full 3D model (USDZ for iOS / visionOS)" \
  --tags "${tags:+$tags,}full-body,360,ar" --source "video (${video:t})" --method $method --coordinates $coordinates \
  --thumbnail thumbs/${id}_fullbody.jpg

print "7. assets.json"
$PY $ROOT/tools/build_manifest.py
print "done in $(( (SECONDS - start) / 60 )) min: check the thumbnail, then git add, commit and push"
