// Convert a USDZ (e.g. from Object Capture) to OBJ + MTL + textures with ModelIO.
// Usage: swift tools/usdz_to_obj.swift in.usdz out.obj
import Foundation
import ModelIO

let args = CommandLine.arguments
let asset = MDLAsset(url: URL(fileURLWithPath: args[1]))
asset.loadTextures()
try asset.export(to: URL(fileURLWithPath: args[2]))
print("exported \(args[2])")
