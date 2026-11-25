import AppKit
import SwiftUI

/// Peek: any cited row opens as the real message in its conversation, in place. Arrows walk the conversation,
/// left and right step to the next citation, return opens it in its own app, esc or space puts it away.

struct ThreadRow: Identifiable, Equatable {
    let id: String
    let who: String        // the name to print: "you", or the sender
    let me: Bool
    let ts: String
    let text: String
    let here: Bool         // the cited message itself
}

struct ThreadPeek: Equatable {
    var hit: Hit
    var turn: Int
    var number: Int
    var title: String
    var src: String
    var rows: [ThreadRow]
    var open = ""
    var total = 0
    var loading = true
    var error = ""
    var cursor = 0          // the row the arrow keys are on

    init(hit: Hit, turn: Int, number: Int) {
        self.hit = hit
        self.turn = turn
        self.number = number
        title = hit.thread.isEmpty ? Catalog.info(hit.src).name : hit.thread.lowercased()
        src = hit.src
        // the cited message is already here: it shows at once, and its conversation fills in around it
        rows = [ThreadRow(id: hit.id, who: hit.who == "me" ? "you" : (hit.sender.isEmpty ? (hit.who.isEmpty ? "them" : hit.who) : hit.sender).lowercased(),
                          me: hit.who == "me", ts: hit.ts, text: hit.text, here: true)]
        open = hit.url
    }

    mutating func take(_ d: [String: Any]?) {
        loading = false
        guard let d else { error = "the conversation could not be read."; return }
        if let e = d["error"] as? String, !e.isEmpty { error = e.lowercased(); return }
        let got = ((d["rows"] as? [[String: Any]]) ?? []).enumerated().map { i, r -> ThreadRow in
            let me = r["me"] as? Bool ?? false
            let sender = (r["sender"] as? String ?? "").lowercased()
            return ThreadRow(id: (r["id"] as? String ?? "") + ":\(i)", who: me ? "you" : (sender.isEmpty ? "them" : sender), me: me,
                             ts: r["ts"] as? String ?? "", text: r["text"] as? String ?? "", here: r["here"] as? Bool ?? false)
        }
        guard !got.isEmpty else { return }
        rows = got
        cursor = got.firstIndex(where: \.here) ?? 0
        if let t = d["title"] as? String, !t.isEmpty { title = t.lowercased() }
        if let s = d["src"] as? String, !s.isEmpty { src = s }
        if let o = d["open"] as? String, !o.isEmpty { open = o }
        total = d["rows_total"] as? Int ?? got.count
    }
}

extension AskModel {
    /// Opens a cited row in its conversation. The message shows at once; the lines around it arrive a moment later.
    func peekThread(_ hit: Hit, turn: Int, _ engine: Engine, margin: Bool = false) {
        let cites = turns.first { $0.id == turn }?.answer?.cites ?? turns.first { $0.id == turn }?.live?.cites ?? []
        let number = (cites.firstIndex { $0.id == hit.id } ?? 0) + 1
        peek = nil
        threadInMargin = margin
        if !margin, turns.contains(where: { $0.id == turn }) { sourcesFor = turn }
        thread = ThreadPeek(hit: hit, turn: turn, number: number)
        threadCall?.cancel()
        guard !Engine.debug else { return }
        let id = hit.id
        threadCall = engine.client.thread(AskModel.rowID(hit), around: 10) { [weak self] d in
            guard let self, self.thread?.hit.id == id else { return }
            self.thread?.take(d)
        }
        NSHapticFeedbackManager.defaultPerformer.perform(.alignment, performanceTime: .default)
    }

    func closeThread() {
        threadCall?.cancel()
        threadCall = nil
        thread = nil
        threadInMargin = false
    }

    /// The next or the one before, among the rows this answer cites.
    func stepCite(_ by: Int, _ engine: Engine) {
        guard let t = thread, let cites = turns.first(where: { $0.id == t.turn })?.answer?.cites, !cites.isEmpty,
              let i = cites.firstIndex(where: { $0.id == t.hit.id }) else { return }
        let next = min(max(i + by, 0), cites.count - 1)
        if next != i { peekThread(cites[next], turn: t.turn, engine) }
    }

    /// The keys while a peek is open. True when the key was ours. With something typed in the input, only esc is:
    /// the conversation beside it must never eat what the owner is writing.
    func threadKey(_ e: NSEvent, _ engine: Engine, modal: Bool = false) -> Bool {
        guard var t = thread else { return false }
        guard e.modifierFlags.intersection([.command, .option, .control]).isEmpty else { return false }
        if !modal, !draft.isEmpty, e.keyCode != 53 { return false }
        switch Int(e.keyCode) {
        case 53, 49: closeThread()                                           // esc, space
        case 125: t.cursor = min(t.cursor + 1, t.rows.count - 1); thread = t  // down
        case 126: t.cursor = max(t.cursor - 1, 0); thread = t                 // up
        case 124: stepCite(1, engine)                                         // right
        case 123: stepCite(-1, engine)                                        // left
        case 36, 76: if let u = Answer.web(t.open), !Probe.on { NSWorkspace.shared.open(u) }
        default: return modal                                                 // in the hotkey panel nothing is typed under a peek
        }
        return true
    }
}

/// The conversation around one message, as a ledger: who, what they said, when. No bubbles.
struct ThreadCard: View {
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduce
    let peek: ThreadPeek
    var maxHeight: CGFloat = 420
    var flat = false            // inside the panel, which is already a floating thing: no second card
    var scrolls = false         // unfolded in the margin of a conversation, which scrolls

    var body: some View {
        let shape = RoundedRectangle(cornerRadius: Radius.card, style: .continuous)
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .center, spacing: 10) {
                SourceIcon(id: peek.src, size: 20)
                Text(peek.title).font(.system(size: 14, weight: .semibold)).foregroundStyle(Ink.ink).lineLimit(1).truncationMode(.middle)
                Text(peek.rows.first.map { Words.day($0.ts) } ?? "").font(.system(size: 12, weight: .medium)).monospacedDigit().foregroundStyle(Ink.faint)
                    .lineLimit(1).fixedSize()
                    .probe("peek.when", .line, scrolls: scrolls)
                Spacer(minLength: 8)
                if peek.loading && !Probe.on {
                    Text("reading").font(.system(size: 12, weight: .medium)).foregroundStyle(Ink.faint).fixedSize()
                } else if peek.total > peek.rows.count {
                    Text("\(peek.rows.count) of \(Words.count(peek.total))").font(.system(size: 12, weight: .medium)).monospacedDigit().foregroundStyle(Ink.faint).fixedSize()
                        .probe("peek.count", .line, scrolls: scrolls)
                }
            }
            .padding(.horizontal, 18).frame(height: 46)
            Rectangle().fill(Ink.line).frame(height: 1)
            ScrollViewReader { proxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: 0) {
                        ForEach(Array(peek.rows.enumerated()), id: \.element.id) { i, row in
                            HStack(alignment: .firstTextBaseline, spacing: 12) {
                                Text(row.who).font(.system(size: 12, weight: .semibold)).foregroundStyle(row.me ? Ink.ink : Ink.soft)
                                    .lineLimit(1).truncationMode(.tail).frame(width: flat ? 64 : 92, alignment: .leading)
                                Text(row.text).font(.system(size: 14)).foregroundStyle(row.here ? Ink.ink : Ink.ink.opacity(0.78)).lineSpacing(3)
                                    .fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                    .probe("peek.text", .text, scrolls: true)
                                Text(ThreadCard.clock(row.ts)).font(.system(size: 11, weight: .medium)).monospacedDigit().foregroundStyle(Ink.faint)
                                    .lineLimit(1).fixedSize()
                            }
                            .padding(.horizontal, 18).padding(.vertical, 8)
                            .background(i == peek.cursor ? Ink.ink.opacity(0.05) : .clear)
                            // the cited message: the one live mark on the card
                            .overlay(alignment: .leading) { if row.here { Rectangle().fill(Ink.ember).frame(width: 2) } }
                            .id(row.id)
                            .probe("peek.row", .block, group: "peek.rows", scrolls: true)
                        }
                    }
                    .padding(.vertical, 6)
                }
                .frame(maxHeight: maxHeight)
                .fixedSize(horizontal: false, vertical: true)
                .onChange(of: peek.rows.count, initial: true) {
                    if let here = peek.rows.first(where: \.here) { proxy.scrollTo(here.id, anchor: .center) }
                }
                .onChange(of: peek.cursor) { _, c in
                    guard peek.rows.indices.contains(c) else { return }
                    withAnimation(reduce ? nil : Motion.snap(false, 0.2)) { proxy.scrollTo(peek.rows[c].id, anchor: .center) }
                }
            }
            if !peek.error.isEmpty {
                Text(peek.error).font(.system(size: 12)).foregroundStyle(Ink.soft).fixedSize(horizontal: false, vertical: true)
                    .padding(.horizontal, 18).padding(.bottom, 10)
                    .probe("peek.error", .text, scrolls: scrolls)
            }
            Rectangle().fill(Ink.line).frame(height: 1)
            HStack(spacing: 14) {
                hint(["↑", "↓"], "walk")
                hint(["←", "→"], "source \(peek.number)")
                if Answer.web(peek.open) != nil { hint(["↵"], "open") }
                Spacer(minLength: 8)
                hint(["esc"], "close")
            }
            .padding(.horizontal, 18).frame(height: 34)
        }
        .background(flat ? Color.clear : Ink.raised)
        .clipShape(flat ? AnyShape(Rectangle()) : AnyShape(shape))
        .overlay { if !flat { shape.strokeBorder(Ink.ink.opacity(0.10), lineWidth: 1) } }
        .shadow(color: .black.opacity(flat || Probe.on ? 0 : 0.18), radius: 24, y: 10)
        .probe("peek.card", .block, scrolls: scrolls)
    }

    private func hint(_ keys: [String], _ word: String) -> some View {
        HStack(spacing: 5) {
            ForEach(keys, id: \.self) { KeyHint(key: $0) }
            Text(word).font(.system(size: 12, weight: .medium)).foregroundStyle(Ink.soft).lineLimit(1).fixedSize()
                .probe("peek.hint", .line, scrolls: scrolls)
        }
    }

    /// "14:32" from an iso time; nothing when the row has only a date.
    static func clock(_ ts: String) -> String {
        guard ts.count >= 16, let t = ts.firstIndex(of: "T") else { return "" }
        return String(ts[ts.index(after: t)...].prefix(5))
    }
}
