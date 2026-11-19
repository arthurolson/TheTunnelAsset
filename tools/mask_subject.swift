// For a turntable capture (the subject turns, the camera and background stay still): keeps only the subject in each
// frame, on a plain grey background, so photogrammetry follows the subject's turning instead of the unmoving room.
// Uses Apple Vision's subject lifting (VNGenerateForegroundInstanceMaskRequest, macOS 14+): every foreground instance
// (a person and the chair they sit on, say) is kept.
// Usage: swift tools/mask_subject.swift <frames_dir> <out_dir> [grey 0-1, default 0.5]
import AppKit
import CoreImage
import Foundation
import Vision

let args = CommandLine.arguments
guard args.count >= 3 else {
    print("usage: mask_subject <frames_dir> <out_dir> [grey]")
    exit(1)
}
let input = URL(fileURLWithPath: args[1], isDirectory: true)
let output = URL(fileURLWithPath: args[2], isDirectory: true)
let grey = args.count > 3 ? Double(args[3]) ?? 0.5 : 0.5
try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)

let files = try FileManager.default.contentsOfDirectory(at: input, includingPropertiesForKeys: nil)
    .filter { ["jpg", "jpeg", "png", "heic"].contains($0.pathExtension.lowercased()) }
    .sorted { $0.lastPathComponent < $1.lastPathComponent }
let context = CIContext()
var kept = 0, skipped = 0
for file in files {
    let handler = VNImageRequestHandler(url: file)
    let request = VNGenerateForegroundInstanceMaskRequest()
    do {
        try handler.perform([request])
        guard let result = request.results?.first, !result.allInstances.isEmpty,
              let image = CIImage(contentsOf: file) else {
            skipped += 1
            print("no subject found in \(file.lastPathComponent): left out")
            continue
        }
        let mask = CIImage(cvPixelBuffer: try result.generateScaledMaskForImage(forInstances: result.allInstances, from: handler))
        let background = CIImage(color: CIColor(red: grey, green: grey, blue: grey)).cropped(to: image.extent)
        let cut = image.applyingFilter("CIBlendWithMask", parameters: [
            kCIInputBackgroundImageKey: background,
            kCIInputMaskImageKey: mask,
        ])
        let out = output.appendingPathComponent(file.deletingPathExtension().lastPathComponent + ".jpg")
        try context.writeJPEGRepresentation(of: cut, to: out, colorSpace: CGColorSpace(name: CGColorSpace.sRGB)!,
                                            options: [kCGImageDestinationLossyCompressionQuality as CIImageRepresentationOption: 0.92])
        kept += 1
    } catch {
        skipped += 1
        print("\(file.lastPathComponent): \(error)")
    }
}
print("masked \(kept) frames, left out \(skipped), in \(output.path)")
