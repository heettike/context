import AppKit
import SwiftUI

// Time is always on screen (DESIGN.md): a spine of years down the left of the main column, a ribbon of
// dated dots above every answer, and the evidence as notes in the margin beside the sentence it supports.

/// One piece of evidence of one answer: the turn it belongs to and its number there.
struct Pick: Equatable {
    var turn: Int
    var n: Int
}

/// The measures of an answer set as a page with a margin, or nil when the window has no room for one.
struct PageMeasure: Equatable {
    var text: CGFloat
    var notes: CGFloat
    static let gap: CGFloat = 28
    /// under this much main column the notes fall back to numbered chips and the panel
    static let least: CGFloat = 760
    var total: CGFloat { text + PageMeasure.gap + notes }

    /// For a main column this wide: a measure near 62 characters of the serif at 16 pt, and what is left for notes.
    static func fit(_ width: CGFloat) -> PageMeasure? {
        guard width >= least else { return nil }
        let room = width - Grid.spinePad * 2 - gap
        let text = min(480, (room * 0.64).rounded())
        return PageMeasure(text: text, notes: min(300, room - text))
    }
}

private struct PageMeasureKey: EnvironmentKey { static let defaultValue: PageMeasure? = nil }
private struct StreamingKey: EnvironmentKey { static let defaultValue = false }
extension EnvironmentValues {
    /// set by the conversation when it is wide enough for margin notes
    var page: PageMeasure? {
        get { self[PageMeasureKey.self] }
        set { self[PageMeasureKey.self] = newValue }
    }
    /// this text is being written now: its newest words fade in
    var streaming: Bool {
        get { self[StreamingKey.self] }
        set { self[StreamingKey.self] = newValue }
    }
}

// MARK: the spine

/// The years the archive runs over, down the left edge of the main column, with now at the foot under the one dot.
struct Spine: View {
    @Environment(AppModel.self) private var model

    /// At most six marks from the first year in the archive to now, evenly spread.
    static func years(first: Int, now: Int) -> [Int] {
        guard first < now else { return [] }
        let span = now - first, steps = min(5, span)
        return (0..<steps).map { first + Int((Double(span) * Double($0) / Double(steps)).rounded()) }
    }

    var body: some View {
        let now = Calendar.current.component(.year, from: Date())
        let first = model.engine.spans.values.compactMap { Words.parts($0.first)?.y }.min() ?? now
        let years = Spine.years(first: first, now: now)
        VStack(alignment: .trailing, spacing: 0) {
            ForEach(years, id: \.self) { y in
                Text(String(y)).foregroundStyle(Ink.faint).lineLimit(1).fixedSize()
                    .probe("spine.year", .line, group: "spine")
                Spacer(minLength: 4)
            }
            HStack(spacing: 4) {
                Text("now").foregroundStyle(Ink.ink).lineLimit(1).fixedSize()
                Circle().fill(Ink.ember).frame(width: 5, height: 5)
            }
            .probe("spine.now", .line, group: "spine")
        }
        .font(.system(size: 9.5, design: .monospaced))
        .padding(.top, 14).padding(.bottom, 22).padding(.trailing, 5)
        .frame(width: Grid.spine, alignment: .trailing)
        .frame(maxHeight: .infinity)
        .overlay(alignment: .trailing) { Rectangle().fill(Ink.line).frame(width: 1) }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(years.isEmpty ? "now" : "your archive runs from \(first) to now")
        .probe("spine", .block)
    }
}

// MARK: the ribbon

/// Above an answer: one dot for each message it rests on, placed in time, with a date at each end and at the
/// chosen dot. While the answer is being worked on the line draws and each dot lands as its message is found.
struct Ribbon: View {
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduce
    let turn: Int
    let cites: [Hit]
    var live = false
    @State private var drawn = false

    static let height: CGFloat = 34

    /// Days since a fixed day, for placing a date on the line.
    static func day(_ ts: String) -> Double? {
        guard let p = Words.parts(ts) else { return nil }
        return Double(p.y) * 372 + Double(p.m) * 31 + Double(p.d)
    }

    /// Where each dot stands, 0 to 1, in the order the cites are numbered: by its date between the first and the
    /// last; dots that would lie on each other are moved apart by at least `gap` of the width.
    static func places(_ cites: [Hit], gap: Double) -> [Double] {
        let days = cites.map { day($0.ts) }
        let known = days.compactMap { $0 }
        guard let lo = known.min(), let hi = known.max() else { return cites.indices.map { cites.count < 2 ? 0.5 : Double($0) / Double(cites.count - 1) } }
        var at = days.map { d -> Double in hi > lo ? ((d ?? hi) - lo) / (hi - lo) : 0.5 }
        // keep them apart, walking left to right
        let order = at.indices.sorted { at[$0] < at[$1] }
        for k in order.indices.dropFirst() where at[order[k]] - at[order[k - 1]] < gap { at[order[k]] = at[order[k - 1]] + gap }
        if let over = at.max(), over > 1 { at = at.map { $0 / over } }
        return at
    }

    var body: some View {
        let chosen = model.ask.chosen.flatMap { $0.turn == turn ? $0.n : nil }
        let still = Probe.still || reduce
        GeometryReader { geo in
            let w = max(1, geo.size.width - 12)
            let at = Ribbon.places(cites, gap: min(0.2, 10 / w))
            let ends = Ribbon.ends(cites)
            ZStack(alignment: .bottomLeading) {
                Rectangle().fill(Ink.line).frame(height: 1)
                    .scaleEffect(x: drawn || still || !live ? 1 : 0.04, anchor: .leading)
                    .probe("ribbon.line", .block, scrolls: true)
                // a date at each end, and one that rises to the chosen dot when it is not an end
                if let ends, cites.count > 1 {
                    label(ends.first, on: chosen.map { at[$0 - 1] < 0.02 } ?? false).offset(x: 0, y: -11)
                    label(ends.last, on: chosen.map { at[$0 - 1] > 0.98 } ?? false)
                        .frame(maxWidth: .infinity, alignment: .trailing).offset(y: -11)
                } else if let only = cites.first, cites.count == 1 {
                    label(Words.day(only.ts), on: chosen == 1).frame(maxWidth: .infinity, alignment: .center).offset(y: -11)
                }
                if let n = chosen, n >= 1, n <= cites.count, cites.count > 1, at[n - 1] >= 0.02, at[n - 1] <= 0.98 {
                    let x = 6 + at[n - 1] * w
                    label(Words.day(cites[n - 1].ts), on: true)
                        .fixedSize().position(x: min(max(x, 70), geo.size.width - 70), y: geo.size.height - 17)
                        .transition(still ? .identity : .opacity.combined(with: .offset(y: 4)))
                        .id("label\(n)")
                }
                ForEach(Array(cites.enumerated()), id: \.element.id) { i, hit in
                    let on = chosen == i + 1
                    Button {
                        let p = Pick(turn: turn, n: i + 1)
                        model.ask.pinned = model.ask.pinned == p ? nil : p
                    } label: {
                        Circle().fill(on ? Ink.ember : Ink.ink)
                            .frame(width: on ? 9 : 6, height: on ? 9 : 6)
                            .frame(width: 16, height: 16).contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .onHover { inside in
                        if inside { model.ask.hoverPick = Pick(turn: turn, n: i + 1) } else if model.ask.hoverPick == Pick(turn: turn, n: i + 1) { model.ask.hoverPick = nil }
                    }
                    .accessibilityLabel("source \(i + 1), \(Words.day(hit.ts))")
                    .accessibilityAddTraits(on ? [.isSelected] : [])
                    .help(Cite.title(hit) + "  ·  " + Words.day(hit.ts))
                    .probe("ribbon.dot", .block, scrolls: true)
                    .position(x: 6 + at[i] * w, y: geo.size.height - 0.5)
                    .transition(still ? .identity : .scale(scale: 0.2).combined(with: .opacity))
                    .animation(Motion.dot(still), value: on)
                }
            }
            .frame(width: geo.size.width, height: geo.size.height, alignment: .bottomLeading)
            .animation(Motion.dot(still), value: cites.count)
            .animation(Motion.lit(still), value: chosen)
        }
        .frame(height: Ribbon.height)
        .onAppear {
            if still || !live { drawn = true; return }
            withAnimation(Motion.draw(reduce)) { drawn = true }
        }
        .probe("ribbon", .block, scrolls: true)
    }

    static func ends(_ cites: [Hit]) -> (first: String, last: String)? {
        let dated = cites.filter { day($0.ts) != nil }.sorted { day($0.ts)! < day($1.ts)! }
        guard let a = dated.first, let b = dated.last else { return nil }
        return (Words.day(a.ts), Words.day(b.ts))
    }

    private func label(_ s: String, on: Bool) -> some View {
        Text(s).font(.system(size: 9.5, design: .monospaced)).foregroundStyle(on ? Ink.ink : Ink.faint).lineLimit(1).fixedSize()
            .probe("ribbon.label", .line, scrolls: true)
    }
}

// MARK: margin notes

/// Where a citation's number came to rest in the text, so its note can stand level with it.
struct NoteAnchor: Equatable {
    let n: Int
    let anchor: Anchor<CGRect>
}

struct NoteAnchorKey: PreferenceKey {
    static var defaultValue: [NoteAnchor] = []
    static func reduce(value: inout [NoteAnchor], nextValue: () -> [NoteAnchor]) { value.append(contentsOf: nextValue()) }
}

/// The same, worked out to a height from the top of the answer.
struct NoteYKey: PreferenceKey {
    static var defaultValue: [Int: CGFloat] = [:]
    static func reduce(value: inout [Int: CGFloat], nextValue: () -> [Int: CGFloat]) { value.merge(nextValue()) { min($0, $1) } }
}

private struct NoteY: LayoutValueKey { static let defaultValue: CGFloat = .infinity }

/// Notes down a margin: each as near the height it asks for as the one above allows. Never one on another.
struct NoteStack: Layout {
    var spacing: CGFloat = 8

    private func rows(_ width: CGFloat?, _ subviews: Subviews) -> [(y: CGFloat, size: CGSize)] {
        var cursor: CGFloat = 0, out: [(CGFloat, CGSize)] = []
        for v in subviews {
            let size = v.sizeThatFits(ProposedViewSize(width: width, height: nil))
            let want = v[NoteY.self]
            let y = max(want.isFinite ? want : cursor, cursor)
            out.append((y, size))
            cursor = y + size.height + spacing
        }
        return out
    }

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let r = rows(proposal.width, subviews)
        return CGSize(width: proposal.width ?? (r.map(\.size.width).max() ?? 0), height: r.last.map { $0.y + $0.size.height } ?? 0)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        for (v, row) in zip(subviews, rows(bounds.width, subviews)) {
            v.place(at: CGPoint(x: bounds.minX, y: bounds.minY + row.y), anchor: .topLeading, proposal: ProposedViewSize(width: bounds.width, height: nil))
        }
    }
}

/// The evidence of one answer, in the margin: a note for each message, level with the sentence it supports.
struct MarginNotes: View {
    @Environment(AppModel.self) private var model
    let turn: Turn
    let cites: [Hit]
    let ys: [Int: CGFloat]

    var body: some View {
        // in the order they stand in the text; one the text never points at goes after the rest
        // numbers on one line of text are level
        let line: (Int) -> CGFloat = { n in ys[n].map { ($0 / 6).rounded() } ?? .infinity }
        let order = cites.indices.map { $0 + 1 }.sorted { (line($0), $0) < (line($1), $1) }
        NoteStack {
            ForEach(Array(order.enumerated()), id: \.element) { i, n in
                MarginNote(turn: turn.id, n: n, hit: cites[n - 1], index: i)
                    .layoutValue(key: NoteY.self, value: ys[n].map { max(0, $0 - 4) } ?? .infinity)
            }
        }
        .overlay(alignment: .leading) { Rectangle().fill(Ink.line).frame(width: 1) }
        .probe("notes", .block, scrolls: true)
    }
}

/// One note: its number, who, when and where from on a small line, then the line itself. Chosen, it moves two
/// points and takes the accent rule; pressed, the message unfolds under it with the ones before and after.
struct MarginNote: View {
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduce
    let turn: Int
    let n: Int
    let hit: Hit
    let index: Int
    @State private var shown = Probe.still

    static func who(_ h: Hit) -> String {
        if h.who == "me" || h.who == "saved" { return "you" }
        let name = Cite.from(h) ?? Cite.title(h)
        return name.count > 22 ? String(name.prefix(21)).trimmingCharacters(in: .whitespaces) + "…" : name
    }

    var body: some View {
        let ask = model.ask
        let me = Pick(turn: turn, n: n)
        let lit = ask.chosen == me
        let open = ask.threadInMargin && ask.thread?.hit.id == hit.id && ask.thread?.turn == turn
        let still = Probe.still || reduce
        VStack(alignment: .leading, spacing: 0) {
            Button {
                ask.pinned = me
                if open { withAnimation(Motion.unfold(still)) { ask.closeThread() } }
                else { withAnimation(Motion.unfold(still)) { ask.peekThread(hit, turn: turn, model.engine, margin: true) } }
            } label: {
                VStack(alignment: .leading, spacing: 2) {
                    Text(["\(n)", MarginNote.who(hit), Words.day(hit.ts), Catalog.info(hit.src).name].filter { !$0.isEmpty }.joined(separator: " · "))
                        .font(.system(size: 10, design: .monospaced)).foregroundStyle(lit ? Ink.soft : Ink.faint)
                        .lineLimit(1).truncationMode(.middle)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    if !open {
                        Text(hit.snippet.isEmpty ? hit.text : hit.snippet)
                            .font(.system(size: Face.small)).lineSpacing(2).foregroundStyle(lit ? Ink.ink : Ink.soft)
                            .lineLimit(lit ? 5 : 2).multilineTextAlignment(.leading)
                            .fixedSize(horizontal: false, vertical: true)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
                .padding(.leading, 10).padding(.trailing, 6).padding(.vertical, 5)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("source \(n): \(MarginNote.who(hit)), \(Words.day(hit.ts))")
            .accessibilityHint(open ? "closes the message" : "opens the message in its conversation")
            .ring(Radius.chip, inset: 0)
            if lit || open {
                TeachWords { RulesModel.sentence($0, thread: Cite.title(hit)) }.padding(.leading, 10).padding(.bottom, 6)
            }
            if open, let peek = ask.thread {
                ThreadCard(peek: peek, maxHeight: 300, flat: true, scrolls: true)
                    .transition(still ? .identity : .asymmetric(insertion: .scale(scale: 0.96, anchor: .top).combined(with: .opacity), removal: .opacity))
                    .probe("note.thread", .block, scrolls: true)
            }
        }
        .background(lit || open ? Ink.wash : .clear)
        .overlay(alignment: .leading) { Rectangle().fill(Ink.ember).frame(width: 1.5).opacity(lit || open ? 1 : 0) }
        .offset(x: (lit ? -2 : 0) + (shown ? 0 : Motion.noteSlide))
        .opacity(shown ? 1 : 0)
        .onHover { inside in if inside { ask.hoverPick = me } else if ask.hoverPick == me { ask.hoverPick = nil } }
        .animation(Motion.lit(still), value: lit)
        .onAppear {
            if still || shown { shown = true; return }
            withAnimation(Motion.note(reduce, index)) { shown = true }
        }
        .probe("note", .block, group: "notes\(turn)", scrolls: true)
    }
}

/// The evidence of an answer in the hotkey panel, which has no margin: the same notes, one under another, below
/// the answer. The arrows walk them; one pressed opens the message in its conversation in the answer's place.
struct PanelNotes: View {
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduce
    let turn: Turn
    let answer: Answer
    @State private var saved = false
    @State private var copied = false

    var body: some View {
        let ask = model.ask
        VStack(alignment: .leading, spacing: 0) {
            ForEach(Array(answer.cites.enumerated()), id: \.element.id) { i, hit in
                let me = Pick(turn: turn.id, n: i + 1)
                let lit = ask.flash == hit.id || ask.chosen == me
                Button { ask.peekThread(hit, turn: turn.id, model.engine) } label: {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(["\(i + 1)", MarginNote.who(hit), Words.day(hit.ts), Catalog.info(hit.src).name].filter { !$0.isEmpty }.joined(separator: " · "))
                            .font(.system(size: 10, design: .monospaced)).foregroundStyle(lit ? Ink.soft : Ink.faint).lineLimit(1).truncationMode(.middle)
                        Text(hit.snippet.isEmpty ? hit.text : hit.snippet).font(.system(size: Face.small)).lineSpacing(2)
                            .foregroundStyle(lit ? Ink.ink : Ink.soft).lineLimit(2).multilineTextAlignment(.leading)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.leading, 10).padding(.trailing, 6).padding(.vertical, 6)
                    .background(lit ? Ink.wash : .clear)
                    .overlay(alignment: .leading) { Rectangle().fill(lit ? Ink.ember : Ink.line).frame(width: 1.5) }
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .onHover { inside in if inside { ask.hoverPick = me } else if ask.hoverPick == me { ask.hoverPick = nil } }
                .animation(Motion.lit(Probe.still || reduce), value: lit)
                .accessibilityLabel("source \(i + 1): \(MarginNote.who(hit)), \(Words.day(hit.ts))")
                .accessibilityHint("opens the message in its conversation")
                .probe("panel.note", .block, group: "panel.notes", scrolls: true)
            }
            HStack(spacing: Space.l) {
                Button(copied ? "copied" : "copy") { Clip.copy(AskModel.plain(turn)); copied = true }.buttonStyle(QuietButton(size: Face.small))
                Button(saved ? "saved to today's journal" : "save to journal") {
                    if !saved { model.journal.append(AskModel.plain(turn)); saved = true }
                }
                .buttonStyle(QuietButton(size: Face.small))
                Spacer(minLength: 0)
            }
            .padding(.top, answer.cites.isEmpty ? 0 : Space.m)
        }
    }
}
