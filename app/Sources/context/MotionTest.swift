import AppKit
import SwiftUI

/// `context --motiontest [folder]` draws the panel's changes of state as strips of frames, at fixed times after each
/// change, in a window that is never shown. It is how motion gets looked at without anything reaching the screen.
/// It prints, for each change, how many of the frames in between differ from both ends: 0 means the change was a cut
/// (or that animations did not run unseen), which is worth knowing either way.
enum MotionTest {
    static let times: [Double] = [0, 0.04, 0.09, 0.16, 0.26, 0.45]

    static func run(out: String?) -> Never {
        let tmp = NSTemporaryDirectory() + "context-motiontest-\(ProcessInfo.processInfo.processIdentifier)"
        setenv("CONTEXT_DEBUG", "still,layout", 1)
        setenv("CTX_HOME", tmp, 1)
        setenv("CONTEXT_REPO", "/nonexistent", 1)
        Probe.on = true
        let app = NSApplication.shared
        app.setActivationPolicy(.prohibited)
        DispatchQueue.global().asyncAfter(deadline: .now() + 120) { print("motion: timed out"); exit(3) }
        let m = AppModel.shared
        m.saved.onboarded = true
        let size = CGSize(width: 800, height: 520)
        let window = NSWindow(contentRect: NSRect(origin: .zero, size: size), styleMask: [.borderless], backing: .buffered, defer: true)
        window.isReleasedWhenClosed = false
        window.hasShadow = false
        window.ignoresMouseEvents = true
        let p = PanelModel()
        p.shown = true
        m.panelProof = p
        let host = NSHostingView(rootView: RootView().environment(m))
        window.contentView = host
        host.layoutSubtreeIfNeeded()
        LayoutTest.pump(0.3)
        if let out { try? FileManager.default.createDirectory(atPath: out, withIntermediateDirectories: true) }

        func frame() -> NSBitmapImageRep? {
            host.layoutSubtreeIfNeeded()
            guard let rep = host.bitmapImageRepForCachingDisplay(in: host.bounds) else { return nil }
            host.cacheDisplay(in: host.bounds, to: rep)
            return rep
        }
        func same(_ a: NSBitmapImageRep, _ b: NSBitmapImageRep) -> Bool { a.tiffRepresentation == b.tiffRepresentation }

        var live = Live(phase: "read", rows: 250, sources: ["whatsapp", "email"], threads: ["Sam (landlord)"])
        let steps: [(String, () -> Void)] = [
            ("typing", { p.text = "did i ever tell sam whether we are renewing the lease?" }),
            ("asked", { var t = Turn(id: 0, q: p.text); t.live = live; m.ask.turns = [t]; m.ask.asking = true; p.turnID = 0 }),
            ("writing", { live.text = "Not yet. Sam asked about the renewal twice and you have not written back."; m.ask.turns[0].live = live }),
            ("answered", { m.ask.turns = LayoutTest.turns(1); m.ask.asking = false }),
            ("peek", { m.ask.thread = LayoutTest.threadProof(m.ask.turns[0]) }),
            ("back", { m.ask.thread = nil }),
        ]
        var failed = 0
        for (name, change) in steps {
            let start = Date()
            change()
            var frames: [NSBitmapImageRep] = []
            for t in times {
                let wait = t - Date().timeIntervalSince(start)
                if wait > 0 { LayoutTest.pump(wait) }
                if let f = frame() { frames.append(f) }
            }
            LayoutTest.pump(0.8)
            guard let end = frame(), let first = frames.first else { failed += 1; continue }
            let between = frames.dropFirst().filter { !same($0, first) && !same($0, end) }.count
            print("motion: \(name): \(between) of \(frames.count - 1) frames are in between")
            if Screen.ours() > 0 { print("motion: a window is on screen"); failed += 1 }
            if let out {
                let all = frames + [end]
                let strip = NSImage(size: NSSize(width: size.width * CGFloat(all.count) / 2, height: size.height / 2))
                strip.lockFocus()
                for (i, f) in all.enumerated() { f.draw(in: NSRect(x: CGFloat(i) * size.width / 2, y: 0, width: size.width / 2, height: size.height / 2)) }
                strip.unlockFocus()
                if let tiff = strip.tiffRepresentation, let rep = NSBitmapImageRep(data: tiff) {
                    try? rep.representation(using: .png, properties: [:])?.write(to: URL(fileURLWithPath: "\(out)/motion-\(name).png"))
                }
            }
        }
        try? FileManager.default.removeItem(atPath: tmp)
        exit(failed == 0 ? 0 : 1)
    }
}
