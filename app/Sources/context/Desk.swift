import AppKit
import SwiftUI

// Home is the desk (DESIGN.md): the last thirty days as they stand, from the engine's `now` command.
// {"cmd": "now"} -> {"result": {"at", "waiting": [{who, what, when, days, thread, id, src}],
//                               "promised": [{what, when, days, thread, id, src}], "mind": [{what, detail, thread}],
//                               "strip": [{"ym": "2015-08", "n": 900}]}}
// Any list may be empty. An engine that does not know the command leaves home as the greeting and the input.

struct NowLine: Identifiable, Equatable {
    var id: String
    var title: String
    var detail = ""
    var when = ""
    var days: Int?
    var thread = ""
    var row = ""
    var src = ""
}

struct NowData: Equatable {
    var at = ""
    var waiting: [NowLine] = []
    var promised: [NowLine] = []
    var mind: [NowLine] = []
    var strip: [Month] = []
    struct Month: Equatable { var ym: String; var n: Int }

    init?(_ any: Any?) {
        guard let d = any as? [String: Any] else { return nil }
        // an answer with none of its keys is not this command's answer
        guard d["waiting"] != nil || d["promised"] != nil || d["mind"] != nil || d["strip"] != nil else { return nil }
        at = d["at"] as? String ?? ""
        func rows(_ key: String) -> [[String: Any]] { (d[key] as? [[String: Any]]) ?? [] }
        func s(_ r: [String: Any], _ k: String) -> String { (r[k] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines).lowercased() }
        waiting = rows("waiting").enumerated().compactMap { i, r in
            let who = s(r, "who"), what = s(r, "what")
            guard !who.isEmpty || !what.isEmpty else { return nil }
            return NowLine(id: "w\(i)", title: who.isEmpty ? what : who, detail: who.isEmpty ? "" : what, when: r["when"] as? String ?? "", days: r["days"] as? Int,
                           thread: s(r, "thread"), row: r["id"] as? String ?? "", src: r["src"] as? String ?? "")
        }
        promised = rows("promised").enumerated().compactMap { i, r in
            let what = s(r, "what")
            guard !what.isEmpty else { return nil }
            return NowLine(id: "p\(i)", title: what, when: r["when"] as? String ?? "", days: r["days"] as? Int, thread: s(r, "thread"), row: r["id"] as? String ?? "", src: r["src"] as? String ?? "")
        }
        mind = rows("mind").enumerated().compactMap { i, r in
            let what = s(r, "what")
            guard !what.isEmpty else { return nil }
            return NowLine(id: "m\(i)", title: what, detail: s(r, "detail"), thread: s(r, "thread"))
        }
        strip = rows("strip").compactMap { r in (r["ym"] as? String).map { Month(ym: $0, n: r["n"] as? Int ?? 0) } }
    }

    /// "today", "1 day", "16 days"
    static func waited(_ days: Int?) -> String {
        guard let days else { return "" }
        return days <= 0 ? "today" : (days == 1 ? "1 day" : "\(days) days")
    }

    /// "today", "yesterday", "3 days ago", "last week", "3 weeks ago"
    static func ago(_ days: Int?) -> String {
        guard let days else { return "" }
        switch days {
        case ..<1: return "today"
        case 1: return "yesterday"
        case 2..<7: return "\(days) days ago"
        case 7..<14: return "last week"
        default: return "\(days / 7) weeks ago"
        }
    }
}

@Observable final class NowModel {
    var data: NowData?
    @ObservationIgnored var asked: Date?
    @ObservationIgnored private var asking = false

    /// Asked at launch, after each sync, and when home opens if the last answer is over ten minutes old.
    func load(_ engine: Engine, force: Bool = false) {
        guard !Probe.on, !asking else { return }
        if !force, let asked, Date().timeIntervalSince(asked) < 600 { return }
        asking = true
        engine.client.call(["cmd": "now"], timeout: 30) { [weak self] reply in
            guard let self else { return }
            self.asking = false
            self.asked = Date()
            // an engine that does not know the command, or one that failed: what was there stays; with nothing there, home is the greeting
            if let d = NowData(reply) { self.data = d }
        }
    }
}

/// The desk: a serif head, the whole archive as a strip of months, three short columns, and the input at the foot.
struct DeskView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduce
    let now: NowData

    static let most = 4

    var body: some View {
        VStack(spacing: 0) {
            ScrollView {
                ScrollTop()
                VStack(alignment: .leading, spacing: 0) {
                    HStack(alignment: .firstTextBaseline, spacing: Space.m) {
                        Text("this month").font(Face.said(26)).tracking(-0.4).foregroundStyle(Ink.ink).lineLimit(1).fixedSize()
                            .probe("desk.head", .line, group: "desk.top", scrolls: true)
                            .accessibilityAddTraits(.isHeader)
                        TimelineView(.periodic(from: .now, by: 30)) { _ in
                            Text(DeskView.stamp(now.at, synced: model.engine.lastSync))
                                .font(.system(size: 10.5, design: .monospaced)).foregroundStyle(Ink.faint).lineLimit(1)
                        }
                        Spacer(minLength: 0)
                    }
                    if !now.strip.isEmpty {
                        ArchiveStrip(months: now.strip).padding(.top, Space.l)
                    }
                    HStack(alignment: .top, spacing: Space.xl) {
                        column("waiting on you", now.waiting, empty: "nobody is waiting on you.", kind: .waiting, base: 0)
                        column("you said you would", now.promised, empty: "nothing you promised is still open.", kind: .promised, base: 4)
                        column("on your mind", now.mind, empty: "nothing stands out this month.", kind: .mind, base: 8)
                    }
                    .padding(.top, Space.xl)
                }
                .frame(maxWidth: 760, alignment: .leading)
                .frame(maxWidth: .infinity)
                .padding(.horizontal, Grid.spinePad).padding(.top, Space.l).padding(.bottom, Space.l)
            }
            Composer(home: true, hotkey: true)
                .frame(maxWidth: 760 + 28)
                .padding(.horizontal, Grid.spinePad - 14).padding(.top, 8).padding(.bottom, 16)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .probe("desk", .block)
    }

    /// "21 nov · synced 4 min ago"
    static func stamp(_ at: String, synced: Date?) -> String {
        let p = Words.parts(at)
        let day = p.map { "\($0.d) \(Words.months[$0.m - 1])" } ?? ""
        return [day, synced == nil ? "" : "synced \(Words.since(synced))"].filter { !$0.isEmpty }.joined(separator: " · ")
    }

    enum Kind { case waiting, promised, mind }

    private func column(_ name: String, _ lines: [NowLine], empty: String, kind: Kind, base: Int) -> some View {
        let shown = Array(lines.prefix(DeskView.most))
        let longest = kind == .waiting ? shown.compactMap(\.days).max() : nil
        return VStack(alignment: .leading, spacing: 0) {
            Text(name).font(.system(size: 10.5, weight: .medium, design: .monospaced)).foregroundStyle(Ink.faint).lineLimit(1)
                .accessibilityAddTraits(.isHeader)
                .probe("desk.col.name", .line, scrolls: true)
                .padding(.bottom, Space.s)
            if shown.isEmpty {
                Rectangle().fill(Ink.line).frame(height: 1)
                Text(empty).font(.system(size: Face.small)).foregroundStyle(Ink.soft).fixedSize(horizontal: false, vertical: true)
                    .padding(.top, Space.s)
                    .probe("desk.empty", .text, scrolls: true)
            }
            ForEach(Array(shown.enumerated()), id: \.element.id) { i, line in
                DeskLine(line: line, kind: kind, dot: longest != nil && (longest ?? 0) > 0 && line.days == longest && shown.firstIndex { $0.days == longest } == i, index: base + i)
            }
        }
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .probe("desk.col", .block, group: "desk.cols", scrolls: true)
    }
}

/// One line of the desk: a rule over it, what it is, what about, and how long. It opens the conversation it came from.
struct DeskLine: View {
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduce
    let line: NowLine
    let kind: DeskView.Kind
    let dot: Bool
    let index: Int
    @State private var hover = false
    @State private var shown = Probe.still
    @State private var days = 0

    var body: some View {
        Button { open() } label: {
            VStack(alignment: .leading, spacing: 2) {
                Rectangle().fill(hover ? Ink.soft.opacity(0.6) : Ink.line).frame(height: 1).padding(.bottom, 5)
                HStack(alignment: .firstTextBaseline, spacing: 5) {
                    if dot { Circle().fill(Ink.ember).frame(width: 5, height: 5).offset(y: -2).accessibilityHidden(true) }
                    Text(line.title).font(.system(size: Face.label, weight: .medium)).foregroundStyle(Ink.ink)
                        .lineLimit(2).multilineTextAlignment(.leading).fixedSize(horizontal: false, vertical: true)
                }
                if !line.detail.isEmpty {
                    Text(line.detail).font(.system(size: Face.small)).foregroundStyle(Ink.soft)
                        .lineLimit(2).multilineTextAlignment(.leading).fixedSize(horizontal: false, vertical: true)
                }
                if kind != .mind, line.days != nil {
                    // the number runs to its value once, when the line first shows
                    HStack(spacing: 0) {
                        if kind == .waiting, (line.days ?? 0) > 0 { Ticker(value: Double(days)); Text((line.days ?? 0) == 1 ? " day" : " days") }
                        else if kind == .waiting { Text("today") }
                        else { Text(NowData.ago(line.days) + (line.src.isEmpty ? "" : " · " + Catalog.info(line.src).name)) }
                    }
                    .font(.system(size: 10, design: .monospaced)).foregroundStyle(Ink.faint).lineLimit(1)
                    .padding(.top, 1)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.bottom, Space.m)
            .contentShape(Rectangle())
        }
        .buttonStyle(Pressable())
        // a conversation known only by a number has nothing to open: the line is said, and is not a button
        .disabled(!opens).allowsHitTesting(opens)
        .onHover { hover = $0 }
        .animation(Motion.hover, value: hover)
        .opacity(shown ? 1 : 0).offset(y: shown ? 0 : 8)
        .onAppear {
            let still = Probe.still || reduce
            if still || shown { shown = true; days = line.days ?? 0; return }
            withAnimation(Motion.settle(reduce, index)) { shown = true; days = line.days ?? 0 }
        }
        .onChange(of: line.days) { _, d in days = d ?? 0 }
        .accessibilityLabel(said)
        .accessibilityHint(!opens ? "" : (kind == .mind ? "puts a question about it in the input" : "opens the conversation it came from"))
        .ring(Radius.chip, inset: 2)
        .help(line.thread.isEmpty ? line.title : line.thread)
        .teachMenu(thread: line.thread)
        .probe("desk.line", .block, group: "desk.lines", scrolls: true)
    }

    private var opens: Bool { !line.thread.isEmpty }

    private var said: String {
        switch kind {
        case .waiting: return [line.title, line.detail, "waiting " + NowData.waited(line.days)].filter { !$0.isEmpty }.joined(separator: ", ")
        case .promised: return [line.title, NowData.ago(line.days)].filter { !$0.isEmpty }.joined(separator: ", ")
        case .mind: return [line.title, line.detail].filter { !$0.isEmpty }.joined(separator: ", ")
        }
    }

    /// The conversation it came from, in the panel on the right. A line with no message behind it (what is on their
    /// mind is a count, not a message) puts a question about it in the input.
    private func open() {
        guard !line.row.isEmpty else {
            model.ask.homeDraft = "what is new with \(line.title) this month?"
            model.focusAsk += 1
            return
        }
        let hit = Hit(id: "now:0:" + line.row, src: line.src, kind: "message", ts: line.when, thread: line.thread, threadID: "", who: "", sender: "", text: line.detail.isEmpty ? line.title : line.detail, url: "", offset: 0)
        model.ask.peekThread(hit, turn: -9, model.engine)
    }
}

/// The whole archive as one strip: a bar a month, as tall as what that month holds, this month dark.
/// It grows from its baseline, left to right, once.
struct ArchiveStrip: View {
    @Environment(\.accessibilityReduceMotion) private var reduce
    let months: [NowData.Month]
    @State private var grown = Probe.still

    /// At most 120 bars: a longer run is folded two months, or more, to a bar.
    static func per(_ months: [NowData.Month]) -> Int { max(1, Int((Double(months.count) / 120).rounded(.up))) }
    static func bars(_ months: [NowData.Month]) -> [Int] {
        let per = per(months)
        return stride(from: 0, to: months.count, by: per).map { i in months[i..<min(i + per, months.count)].reduce(0) { $0 + $1.n } }
    }

    var body: some View {
        let bars = ArchiveStrip.bars(months), top = max(1, bars.max() ?? 1)
        VStack(alignment: .leading, spacing: 4) {
            GeometryReader { geo in
                HStack(alignment: .bottom, spacing: bars.count > 80 ? 1 : 2) {
                    ForEach(Array(bars.enumerated()), id: \.offset) { i, n in
                        // a square-root scale: the last years hold far more than the first (browsing, likes), and on a
                        // straight scale the early years would be a flat line
                        let h = max(2, geo.size.height * CGFloat((Double(n) / Double(top)).squareRoot()))
                        RoundedRectangle(cornerRadius: 1).fill(i == bars.count - 1 ? Ink.ink : Ink.soft.opacity(0.32))
                            .frame(height: h)
                            .scaleEffect(y: grown ? 1 : 0.02, anchor: .bottom)
                            .animation(Motion.grow(reduce, Double(i) / Double(max(1, bars.count - 1))), value: grown)
                    }
                }
                .frame(height: geo.size.height, alignment: .bottom)
            }
            .frame(height: 40)
            .probe("desk.strip", .block, group: "desk.top", scrolls: true)
            HStack {
                Text(months.first.map { String($0.ym.prefix(4)) } ?? "")
                Spacer(minLength: 8)
                Text(months.last.map { Words.monthLong($0.ym) } ?? "").foregroundStyle(Ink.soft)
            }
            .font(.system(size: 9.5, design: .monospaced)).foregroundStyle(Ink.faint).lineLimit(1)
        }
        .onAppear { grown = true }
        .help("a bar is one month\(ArchiveStrip.per(months) > 1 ? " (\(ArchiveStrip.per(months)) months where the strip is long)" : ""): everything kept from it, messages, notes, pages and saves. taller is more; the scale is eased so the early years still show. the dark bar is this month.")
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("your archive by month, from \(months.first?.ym ?? "") to \(months.last?.ym ?? "")")
    }
}
