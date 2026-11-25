import AppKit
import SwiftUI

/// The lines every page in the main area hangs on, and the frame's own measures.
enum Grid {
    static let edge: CGFloat = 40      // where a page's text starts, from the left of the main area
    static let trailing: CGFloat = 40
    static let setup: CGFloat = 92     // first run has no sidebar: its text starts after the traffic lights
    static let sidebar: CGFloat = 252
    static let column: CGFloat = 740   // the conversation, and the input under it
    static let narrow: CGFloat = 860   // a window narrower than this folds the sidebar by itself
    static let spine: CGFloat = 40     // the years down the left edge of the main column, on home and in a conversation
    static let spinePad: CGFloat = 58  // where text starts beside the spine; the input starts 14 pt before it
}

/// The measures of the title-bar row: everything in it sits on the centre line of the traffic lights.
enum TopBar {
    static let tabFont = NSFont.systemFont(ofSize: 13, weight: .medium)
    static let statusFont = NSFont.systemFont(ofSize: 12, weight: .medium)
    /// the mark: the cap height of the bar's text and a little, so it reads as a letter of the same line
    static let mark: CGFloat = (NSFont.systemFont(ofSize: 14, weight: .semibold).capHeight * 1.55).rounded()

    /// How far below the middle of its line box a face's x-height centre sits.
    static func rise(_ font: NSFont) -> CGFloat { (font.ascender + font.descender) / 2 - font.xHeight / 2 }

    /// Where the middle of a label's x-height falls, given the frame its text was laid out in.
    static func xCentre(of frame: CGRect, font: NSFont) -> CGFloat {
        let line = font.ascender - font.descender
        return frame.minY + (frame.height - line) / 2 + font.ascender - font.xHeight / 2
    }
}

/// A small square button of the title-bar row and the sidebar: one symbol, a wash under the pointer.
struct BarButton: View {
    let symbol: String
    var help = ""
    var size: CGFloat = 14
    var label = ""              // what voiceover says, when the help's own words are not the name of the thing
    let action: () -> Void
    @State private var hover = false

    /// What voiceover says: the help's words without the key written after them.
    static func spoken(_ help: String, _ symbol: String) -> String {
        let words = help.components(separatedBy: "  ").first ?? help
        return words.isEmpty ? symbol.replacingOccurrences(of: ".", with: " ") : words
    }

    var body: some View {
        Button(action: action) {
            Image(systemName: symbol).font(.system(size: size, weight: .medium)).foregroundStyle(hover ? Ink.ink : Ink.soft)
                .frame(width: 28, height: 28)
                .background(Ink.ink.opacity(hover ? 0.07 : 0), in: RoundedRectangle(cornerRadius: Radius.row, style: .continuous))
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
        .help(help)
        .accessibilityLabel(label.isEmpty ? BarButton.spoken(help, symbol) : label)
        .ring(Radius.row)
        .animation(Motion.hover, value: hover)
    }
}

/// The top of the main area: one row on the centre line of the traffic lights. With the sidebar folded it holds the
/// way to open it and "new chat" after the lights; in the middle, the name of what is showing; at the right, what
/// is being read and the door to an answer's sources.
struct MainBar: View {
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduce
    let side: Bool          // the sidebar is showing

    var body: some View {
        let title = model.barTitle
        HStack(alignment: .center, spacing: 4) {
            if !side {
                BarButton(symbol: "sidebar.left", help: "show the list of chats  ⇧⌘S", label: "show sidebar") { model.toggleSidebar() }
                    .probe("bar.item", .block)
                BarButton(symbol: "square.and.pencil", help: "new chat  ⌘N") { model.newChat() }
                    .probe("bar.item", .block)
            }
            Spacer(minLength: 12)
            if !side {
                TimelineView(.periodic(from: .now, by: 5)) { t in
                    if let doing = model.engine.doing(at: t.date) {
                        // the sync pill: with the list of chats folded away, what is being read still shows, and opens sources
                        Button { model.go(.sources) } label: {
                            HStack(alignment: .center, spacing: 6) {
                                Spinner(size: 9)
                                Text(doing).font(.system(size: 12, weight: .medium)).monospacedDigit().foregroundStyle(Ink.soft).lineLimit(1).fixedSize()
                                    .probe("bar.doing", .line)
                            }
                            .padding(.horizontal, 10).frame(height: 24)
                            .background(Ink.wash, in: Capsule())
                            .contentShape(Capsule())
                        }
                        .buttonStyle(.plain)
                        .probe("bar.pill", .block)
                        .help(model.engine.doingDetail(at: t.date))
                        .accessibilityLabel(doing).accessibilityHint("opens sources")
                        .transition(.opacity)
                    }
                }
            }
            if model.tab == .home, !model.ask.exact, let t = model.ask.sourcesFor.flatMap({ id in model.ask.turns.first { $0.id == id } }) ?? model.ask.turns.last(where: { !($0.answer?.cites.isEmpty ?? true) }) {
                BarButton(symbol: "sidebar.right", help: "this answer's sources", label: "sources panel") { model.ask.toggleSources(t.id) }
                    .probe("bar.item", .block)
            }
        }
        .padding(.leading, side ? 14 : max(model.lights.x + 10, 14)).padding(.trailing, 12)
        .frame(height: model.lights.y * 2, alignment: .center)
        .overlay(alignment: .center) {
            if !title.isEmpty {
            Text(title).font(.system(size: Face.label, weight: .medium)).foregroundStyle(Ink.soft).lineLimit(1).truncationMode(.tail)
                .probe("bar.title", .block)
                .offset(y: -TopBar.rise(TopBar.tabFont))
                .padding(.horizontal, side ? 60 : 170)
                // the name before it is cut; the new one arrives. two names are never drawn in the same place
                .id(title).transition(.asymmetric(insertion: .opacity, removal: .identity))
            }
        }
        .frame(maxWidth: .infinity)
        // the bar has a ground of its own: whatever scrolls up goes under it, blurred.
        // a render draws plain paper, since blur does not draw in a window nobody sees.
        .background {
            ZStack {
                if !Probe.on { Rectangle().fill(.ultraThinMaterial) }
                Ink.paper.opacity(Probe.on ? 1 : 0.84)
            }
            .probe("bar.ground", .block)
        }
        .overlay(alignment: .bottom) { Rectangle().fill(Ink.line).frame(height: 1).opacity(model.underBar ? 1 : 0) }
        .animation(.easeOut(duration: 0.12), value: model.underBar)
        .animation(Motion.quick(reduce), value: title)
    }
}

/// Goes first inside a scroll view's content. It tells the bar when that content has moved up under it.
struct ScrollTop: View {
    var body: some View {
        Color.clear.frame(height: 0)
            .background(GeometryReader { g in Color.clear.preference(key: ScrollTopKey.self, value: g.frame(in: .named(Probe.space)).minY) })
    }
}

struct ScrollTopKey: PreferenceKey {
    static let defaultValue: CGFloat = .infinity
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) { value = min(value, nextValue()) }
}

/// The one shared element: the input in the middle of home and the input at the foot of a chat are the same thing in two places.
private struct AskSpaceKey: EnvironmentKey { static let defaultValue: Namespace.ID? = nil }
extension EnvironmentValues {
    var askSpace: Namespace.ID? {
        get { self[AskSpaceKey.self] }
        set { self[AskSpaceKey.self] = newValue }
    }
}
extension View {
    @ViewBuilder func travels(_ id: String, in space: Namespace.ID?) -> some View {
        if let space, !Probe.on { matchedGeometryEffect(id: id, in: space, properties: .position, anchor: .top) } else { self }
    }
}
