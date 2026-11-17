// Apple Object Capture (RealityKit PhotogrammetrySession) from a folder of images.
// Usage: swift tools/object_capture.swift <images_dir> <out.usdz> [preview|reduced|medium|full|raw]
import Foundation
import RealityKit

let args = CommandLine.arguments
guard args.count >= 3 else {
    print("usage: object_capture <images_dir> <out.usdz> [detail]")
    exit(1)
}
let input = URL(fileURLWithPath: args[1], isDirectory: true)
let output = URL(fileURLWithPath: args[2])
let detailName = args.count > 3 ? args[3] : "medium"
let detail: PhotogrammetrySession.Request.Detail = {
    switch detailName {
    case "preview": return .preview
    case "reduced": return .reduced
    case "full": return .full
    case "raw": return .raw
    default: return .medium
    }
}()

guard PhotogrammetrySession.isSupported else {
    print("PhotogrammetrySession not supported on this Mac")
    exit(1)
}

var config = PhotogrammetrySession.Configuration()
config.sampleOrdering = .sequential  // frames come from a continuous video
config.featureSensitivity = .high    // dark clothing, low texture
config.isObjectMaskingEnabled = true // keep the subject, drop the room

let session = try PhotogrammetrySession(input: input, configuration: config)

Task {
    do {
        for try await out in session.outputs {
            switch out {
            case .requestProgress(_, let f):
                print(String(format: "progress %.0f%%", f * 100))
            case .requestComplete(_, let r):
                if case .modelFile(let url) = r { print("saved \(url.path)") }
            case .requestError(_, let e):
                print("request error: \(e)")
            case .processingComplete:
                print("done")
                exit(0)
            case .invalidSample(let id, let reason):
                print("invalid sample \(id): \(reason)")
            case .skippedSample(let id):
                print("skipped sample \(id)")
            case .processingCancelled:
                print("cancelled")
                exit(1)
            default:
                break
            }
        }
    } catch {
        print("output error: \(error)")
        exit(1)
    }
}

try session.process(requests: [.modelFile(url: output, detail: detail)])
RunLoop.main.run()
