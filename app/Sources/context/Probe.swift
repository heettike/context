import SwiftUI

/// Layout checks. A view marked with `.probe` reports where it ended up and how big it wanted to be, but only
/// while `--layouttest` is running. The test then asserts on the numbers, so a clipped heading is found by the
/// build, not by the person using the app.
enum ProbeKind: String {
    case text      // may wrap; must not be cut off vertically
    case line      // one line; must not be truncated
    case button    // must keep its own size
    case block     // only has to stay inside the window and off its siblings
    case edge      // shares one left edge with the others in its group
}

struct ProbeInfo: Equatable {
    var name: String
    var kind: ProbeKind
    var group: String
    var scrolls: Bool
    var frame: CGRect
    var ideal: CGSize
}

struct ProbeKey: PreferenceKey {
    static var defaultValue: [ProbeInfo] = []
    static func reduce(value: inout [ProbeInfo], nextValue: () -> [ProbeInfo]) { value.append(contentsOf: nextValue()) }
}

enum Probe {
    static var on = false
    /// a motion check is running: pages and lines arrive as they do in the app, so their frames can be drawn and measured
    static var moving = false
    /// things are drawn at rest, with no arrival: a layout check that is not looking at motion
    static var still: Bool { on && !moving }
    static var found: [ProbeInfo] = []
    static let space = "window"
}

extension View {
    /// `group`: probes in one group must not overlap (or, for `.edge`, must share a left edge).
    /// `scrolls`: the view lives in a scroll view, so being below the fold is fine.
    @ViewBuilder func probe(_ name: String, _ kind: ProbeKind = .block, group: String = "", scrolls: Bool = false) -> some View {
        if Probe.on {
            background(GeometryReader { outer in
                // a hidden copy laid out with no limit in the direction that matters gives the size it wants
                Group {
                    switch kind {
                    case .text: self.frame(width: outer.size.width).fixedSize(horizontal: false, vertical: true)
                    case .line, .button: self.fixedSize()
                    case .block, .edge: Color.clear.frame(width: outer.size.width, height: outer.size.height)
                    }
                }
                .hidden()
                .background(GeometryReader { inner in
                    Color.clear.preference(key: ProbeKey.self, value: [ProbeInfo(
                        name: name, kind: kind, group: group, scrolls: scrolls,
                        frame: outer.frame(in: .named(Probe.space)), ideal: inner.size)])
                })
            })
        } else {
            self
        }
    }
}
