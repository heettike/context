// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "context",
    platforms: [.macOS(.v14)],
    targets: [.executableTarget(name: "context", path: "Sources/context")]
)
