#!/bin/zsh
# Pipeline B: an orbit video -> a full 3D model and splat, in one command (a Mac with Apple silicon: Apple Object
# Capture).
#
#   tools/video_to_asset.sh orbit.mov [more.mov ...] --id art_standing --subject art --title "Art, standing"
#       --height 1.80 [--tags person,full-body] [--detail medium|full|reduced] [--fps 10] [--drop 0.2]
#       [--turntable [--grey-below 0.5]] [--splat-count 600000]
#
# Writes mesh/<id>_fullbody.glb (real size, feet at y = 0), mesh/<id>_fullbody.usdz (for iOS / visionOS Quick Look),
# splat/<id>_fullbody.ply (a full 3D splat sampled over the mesh), a four-view thumbnail and a sidecar for each, then
# regenerates assets.json. Several videos of the same subject (from different heights, say) are used together.
#
# --turntable: the subject turns in front of a still camera and room (a person on a swivel chair). Each frame is cut
# out onto grey first, so photogrammetry follows the subject, not the room. Object Capture can still wall in gaps
# (under a chair seat) with that grey: --grey-below H removes grey triangles lower than H meters. No USDZ is written
# then, since that cleanup is done on the GLB.
#
# Steps:
#   1. frames at --fps (ffmpeg), the blurriest --drop fraction left out   tools/select_frames.py
#      (--turntable) the subject cut out onto grey                          tools/mask_subject.swift
#   2. photogrammetry: sequential samples, high feature sensitivity, object masking   tools/object_capture.swift
#   3. USDZ -> OBJ with its textures (ModelIO)                              tools/usdz_to_obj.swift
#   4. OBJ -> GLB, scaled so it is --height meters tall, feet at y = 0     tools/obj_to_glb.py
#      (--grey-below) background grey removed                              tools/glb_drop_colour.py
#   5. a splat sampled over the mesh                                       tools/mesh_to_splat.py
# On Windows or Linux, run the same frames through RealityScan, Meshroom or COLMAP + OpenMVS, then steps 4 on.
# Python: the "sharp" conda environment's (PY=... to use another with numpy, scipy, Pillow, trimesh).
set -euo pipefail

ROOT=${0:A:h:h}
PY=${PY:-$HOME/miniforge3/envs/sharp/bin/python}
videos=() id="" subject="" title="" height="" tags="" detail=medium fps=10 drop=0.2 turntable=0 grey_below="" splat_count=600000
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
    --turntable) turntable=1; shift;;
    --grey-below) grey_below=$2; shift 2;;
    --splat-count) splat_count=$2; shift 2;;
    -*) print -u2 "unknown option $1"; exit 2;;
    *) videos+=(${1:A}); shift;;
  esac
done
if (( ${#videos} == 0 )) ||  [[ -z $id || -z $subject || -z $title ]]; then
  print -u2 "usage: tools/video_to_asset.sh video.mov [more.mov] --id ID --subject S --title T [--height 1.80] [--tags a,b] [--detail medium] [--turntable [--grey-below 0.5]]"
  exit 2
fi

work=$ROOT/.work/$id
mkdir -p $work
glb=$ROOT/mesh/${id}_fullbody.glb
usdz=$ROOT/mesh/${id}_fullbody.usdz
splat=$ROOT/splat/${id}_fullbody.ply
thumb=$ROOT/thumbs/${id}_fullbody.jpg
start=$SECONDS

print "1. frames"
rm -rf $work/frames $work/frames_all $work/video_* $work/masked
mkdir -p $work/frames
i=0
for video in $videos; do
  i=$((i + 1))
  $PY $ROOT/tools/select_frames.py $video $work/video_$i $fps $drop
  for f in $work/video_$i/*.jpg; do cp $f $work/frames/v${i}_${f:t}; done
done
frames=$(ls $work/frames | wc -l | tr -d ' ')
capture=$work/frames
if (( turntable )); then
  print "   cutting the subject out of each frame (turntable)"
  swift $ROOT/tools/mask_subject.swift $work/frames $work/masked
  capture=$work/masked
fi

print "2. photogrammetry ($frames frames, detail $detail; a few minutes)"
rm -f $work/model.usdz
swift $ROOT/tools/object_capture.swift $capture $work/model.usdz $detail | grep -E "progress (25|50|75|100)%|saved|error|invalid|done" || true
[[ -f $work/model.usdz ]] || { print -u2 "Object Capture made no model"; exit 1; }

print "3. USDZ -> OBJ"
rm -rf $work/obj && mkdir -p $work/obj
swift $ROOT/tools/usdz_to_obj.swift $work/model.usdz $work/obj/model.obj

print "4. OBJ -> GLB${height:+, $height m tall}"
$PY $ROOT/tools/obj_to_glb.py $work/obj/model.obj $glb ${height:-}
if [[ -n $grey_below ]]; then
  cp $glb $work/raw.glb
  $PY $ROOT/tools/glb_drop_colour.py $work/raw.glb $glb --below $grey_below
  rm -f $usdz $usdz.meta.json
else
  cp $work/model.usdz $usdz
fi
for f in $glb $splat ${usdz:+$usdz}; do
  [[ -f $f ]] || continue
  bytes=$(stat -f %z $f)
  if (( bytes > 95000000 )); then
    print -u2 "${f:t} is $((bytes / 1000000)) MB, over GitHub's limit: try --detail reduced, or host it elsewhere (see the README)"
    exit 1
  fi
done

print "5. thumbnail and splat"
$PY $ROOT/tools/glb_thumbnail.py $glb $thumb --views 4
$PY $ROOT/tools/mesh_to_splat.py $glb $splat --count $splat_count

print "6. sidecars"
# The method's settings as JSON, made with Python so optional fields stay valid JSON.
method=$(DETAIL=$detail FRAMES=$frames FPS=$fps DROP=$drop VIDEOS=${#videos} HEIGHT=$height TURNTABLE=$turntable \
  GREY_BELOW=$grey_below $PY -c '
import json, os
e = os.environ
m = {"name": "Apple Object Capture (RealityKit PhotogrammetrySession)", "detail": e["DETAIL"],
     "frames": int(e["FRAMES"]), "videos": int(e["VIDEOS"]), "frames_per_second": float(e["FPS"]),
     "blurriest_dropped": float(e["DROP"]), "sample_ordering": "sequential", "feature_sensitivity": "high",
     "object_masking": True, "script": "tools/video_to_asset.sh"}
if e["HEIGHT"]: m["height_m"] = float(e["HEIGHT"])
if e["TURNTABLE"] == "1": m["turntable"] = "subject cut out onto grey (tools/mask_subject.swift)"
if e["GREY_BELOW"]: m["grey_removed_below_m"] = float(e["GREY_BELOW"])
print(json.dumps(m))')
source="video (${(j:, :)${videos:t}})"
coordinates=${height:+gltf-meters}
coordinates=${coordinates:-gltf}
$PY $ROOT/tools/asset_meta.py $glb --id ${id}_fullbody --subject $subject --title "$title, full 3D model" \
  --tags "${tags:+$tags,}full-body,360" --source $source --method $method --coordinates $coordinates \
  --thumbnail thumbs/${id}_fullbody.jpg
if [[ -f $usdz ]]; then
  $PY $ROOT/tools/asset_meta.py $usdz --id ${id}_fullbody_usdz --subject $subject --title "$title, full 3D model (USDZ for iOS / visionOS)" \
    --tags "${tags:+$tags,}full-body,360,ar" --source $source --method $method --coordinates $coordinates \
    --thumbnail thumbs/${id}_fullbody.jpg
fi
$PY $ROOT/tools/asset_meta.py $splat --id ${id}_fullbody_splat --subject $subject --title "$title, full 3D splat" \
  --tags "${tags:+$tags,}full-body,360" --source "derived from ${id}_fullbody" \
  --method "{\"name\": \"Gaussians sampled over the textured mesh surface\", \"count\": $splat_count, \"script\": \"tools/mesh_to_splat.py\"}" \
  --coordinates opencv --thumbnail thumbs/${id}_fullbody.jpg

print "7. assets.json"
$PY $ROOT/tools/build_manifest.py
print "done in $(( (SECONDS - start) / 60 )) min: check the thumbnail, then git add, commit and push"
