import AppKit
import SwiftUI

/// The wall of first run, checked: what a tile may say, that nothing in it is cut or lies outside it, that a value
/// which changes is never drawn twice, and that the words a stranger must never read are nowhere in the app.
extension LayoutTest {
    /// Every word of a tile lies inside its tile, and no two words of one kind lie on each other.
    static func wallCheck(_ screen: String, _ at: String, _ found: [ProbeInfo]) -> [String] {
        guard screen.hasPrefix("reading"), AppModel.shared.detail == nil else { return [] }
        var more: [String] = []
        let tiles = found.filter { $0.name == "read.row" }.map(\.frame)
        for p in found where ["read.name", "read.sub", "read.wait", "read.count", "read.act"].contains(p.name) {
            guard let tile = tiles.first(where: { $0.insetBy(dx: -1, dy: -1).contains(CGPoint(x: p.frame.midX, y: p.frame.minY + 1)) }) else { continue }
            if p.frame.maxY > tile.maxY - 4 || p.frame.maxX > tile.maxX - 4 {
                more.append("\(at): \(p.name) runs out of its tile (\(Int(p.frame.minX)),\(Int(p.frame.minY)) \(Int(p.frame.width))x\(Int(p.frame.height)) in a tile ending at \(Int(tile.maxX)),\(Int(tile.maxY)))")
            }
        }
        more += wallWords(at)
        if found.filter({ $0.name == "read.exports.choose" }).count > 1 { more.append("\(at): the exports are asked about more than once") }
        return more
    }

    /// What the wall says, read from the rows themselves: never a thread's or a person's name, never a tile for a
    /// source that only has nothing in it yet, and none of the words that sent a stranger looking for an agent.
    static func wallWords(_ at: String) -> [String] {
        let m = AppModel.shared
        var more: [String] = []
        let rows = m.readGroups.flatMap(\.rows)
        let labels = Set(m.engine.log.values.flatMap { $0.map { $0.label.lowercased() } }.filter { $0.count > 2 })
        for r in rows {
            let said = [r.text, r.wait, r.button].joined(separator: " | ").lowercased()
            for l in labels where said.contains(l) { more.append("\(at): the \(r.name) tile shows a thread's name on the wall") }
            for w in banned where said.contains(w) { more.append("\(at): the \(r.name) tile says \u{201C}\(w)\u{201D}") }
            if said.contains("could not read") { more.append("\(at): the \(r.name) tile says it could not read, with no reason") }
            if r.kind == .reading, r.count == 0, r.since == nil, r.text != "starting" { more.append("\(at): the \(r.name) tile stands at 0 with nothing moving") }
        }
        if rows.contains(where: { $0.id == "journal" }), case .skipped = m.engine.state("journal") { more.append("\(at): a source with nothing in it yet has a tile") }
        if rows.filter({ $0.button == "yes" || $0.button == "no" }).count > 0 { more.append("\(at): an export tile asks its own yes or no") }
        return more
    }

    /// Words that must not be anywhere in the app. Spelled backwards here, so this list is not itself a find.
    static let banned: [String] = ["boj s'tnega ruoy", "taht ypoc"].map { String($0.reversed()) }

    /// The app's own binary, searched for them.
    static func bannedWords() -> [String] {
        guard let path = Bundle.main.executablePath ?? CommandLine.arguments.first, let data = FileManager.default.contents(atPath: path) else { return ["banned words: the app's own file could not be read"] }
        return banned.filter { data.range(of: Data($0.utf8)) != nil }.map { "the app still says \u{201C}\($0)\u{201D} somewhere" }
    }

    /// How many points of two renders differ by more than a tone: a third of the way from black to white.
    static func differing(_ a: NSBitmapImageRep, _ b: NSBitmapImageRep) -> (count: Int, at: String) {
        guard let pa = a.bitmapData, let pb = b.bitmapData, a.pixelsWide == b.pixelsWide, a.pixelsHigh == b.pixelsHigh, a.bytesPerRow == b.bytesPerRow else { return (-1, "") }
        let spp = a.samplesPerPixel, row = a.bytesPerRow, scale = max(1, a.pixelsWide / max(1, Int(a.size.width)))
        var n = 0, x0 = Int.max, y0 = Int.max, x1 = 0, y1 = 0
        for y in 0..<a.pixelsHigh {
            let o = y * row
            for x in 0..<a.pixelsWide {
                let i = o + x * spp
                if abs(Int(pa[i]) - Int(pb[i])) > 80 || abs(Int(pa[i + 1]) - Int(pb[i + 1])) > 80 || abs(Int(pa[i + 2]) - Int(pb[i + 2])) > 80 {
                    n += 1
                    x0 = min(x0, x); y0 = min(y0, y); x1 = max(x1, x); y1 = max(y1, y)
                }
            }
        }
        return (n, n == 0 ? "" : "from \(x0 / scale),\(y0 / scale) to \(x1 / scale),\(y1 / scale)")
    }

    /// The wall while its values change, with animation left on: frames in between are laid out and looked at. A
    /// line or a tile's word that is drawn twice at once, the old value and the new, shows up as two of one probe.
    static func wallMotion(_ window: NSWindow, _ m: AppModel, out: String?) -> [String] {
        var more: [String] = []
        let e = m.engine
        scenarios(m).first { $0.0 == "reading-mixed" }?.1()
        // an export that arrives mid-read gets a new tile, which macos fades in over empty ground. that is not a value
        // changing in place, so here every tile is on the wall from the start
        for id in e.order where Catalog.info(id).via == .archive && (e.states[id] == .reading || e.states[id] == .waiting) { e.states[id] = .done(rows: Invented.sizes[0], secs: 1) }
        (window.contentView as? NSHostingView<AnyView>)?.rootView = AnyView(EmptyView())
        window.contentView = nil
        window.setContentSize(CGSize(width: 920, height: 640))
        NSApplication.shared.appearance = NSAppearance(named: .aqua)
        Probe.found = []
        let host = NSHostingView(rootView: AnyView(RootView().environment(m)))       // animations on: this is the point
        window.contentView = host
        host.layoutSubtreeIfNeeded()
        pump(0.5)
        let reading = e.order.filter { e.states[$0] == .reading }
        let changes: [(String, () -> Void)] = [
            ("lands", {                                  // two sources land at once: the line under the total and two tiles change
                for id in reading.prefix(2) { e.states[id] = .done(rows: Invented.landed, secs: 2); e.live[id] = Invented.landed; e.spans[id] = DateSpan(first: Invented.later, last: "2026-11-01") }
            }),
            ("counts", { for id in e.order where e.states[id] == .reading { e.live[id] = (e.live[id] ?? 0) + Invented.step; e.log[id]?.append(Sample(rows: 1, at: Invented.at, label: "priya raman", phase: "")) } }),
            ("signed-in", {                              // this mac is read; the signed-in sources begin
                for id in e.order where e.states[id] == .reading || e.states[id] == .waiting { e.states[id] = .done(rows: Invented.sizes[1], secs: 1.2) }
                m.readingDone = Date()
                m.bridge = true
                m.signedIn = .reading
            }),
            ("all-read", { e.syncing = false; m.signedIn = .done; e.states["slack"] = .done(rows: Invented.signedIn, secs: 31) }),
        ]
        var frames: [(String, NSBitmapImageRep)] = []
        for (name, change) in changes {
            let start = Date()
            change()
            for (i, t) in [0.03, 0.08, 0.14, 0.22, 0.4].enumerated() {
                let wait = t - Date().timeIntervalSince(start)
                if wait > 0 { pump(wait) }
                host.layoutSubtreeIfNeeded()
                let found = Probe.found
                let at = "the wall, \(name), \(Int(t * 1000)) ms after"
                if found.filter({ $0.name == "read.line" }).count > 1 { more.append("\(at): the line under the total is drawn twice") }
                if found.filter({ $0.name == "read.total" }).count > 1 { more.append("\(at): the total is drawn twice") }
                for group in ["read.names", "read.figures", "read.subs", "read.rows"] {
                    let members = found.filter { $0.group == group }
                    var hit = false
                    for a in members.indices where !hit {
                        for b in members.indices where b > a && !hit {
                            let x = members[a].frame.intersection(members[b].frame)
                            if !x.isNull, x.width > 1, x.height > 1 { more.append("\(at): \(members[a].name) and \(members[b].name) are drawn on each other in \(group)"); hit = true }
                        }
                    }
                }
                more += wallCheck("reading-motion", at, found)
                if let rep = host.bitmapImageRepForCachingDisplay(in: host.bounds) {
                    host.cacheDisplay(in: host.bounds, to: rep)
                    frames.append((at, rep))
                    if let out { try? rep.representation(using: .png, properties: [:])?.write(to: URL(fileURLWithPath: "\(out)/motion-wall-\(name)-\(i).png")) }
                }
            }
            // the same screen once everything has landed. a frame in between that differs from it shows something
            // caught between two states: a line fading while its next value fades in, a tile part way to its place.
            // (the clocks stand still and the figures do not roll under the check, so nothing else can differ;
            // a tile's ground easing from one tone to another is far under the threshold.)
            pump(0.9)
            host.layoutSubtreeIfNeeded()
            if let end = host.bitmapImageRepForCachingDisplay(in: host.bounds) {
                host.cacheDisplay(in: host.bounds, to: end)
                for (at, f) in frames {
                    let d = differing(f, end)
                    if d.count > 40 { more.append("\(at): \(d.count) points of the wall are between two states (\(d.at))") }
                }
            }
            frames = []
        }
        if Screen.ours() > 0 { more.append("the wall in motion: a window of the test is on screen") }
        (window.contentView as? NSHostingView<AnyView>)?.rootView = AnyView(EmptyView())
        window.contentView = nil
        scenarios(m).first { $0.0 == "frame-0" }?.1()
        return Array(Set(more)).sorted()
    }
}
