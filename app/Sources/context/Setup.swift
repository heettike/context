import AppKit
import ApplicationServices
import SwiftUI

// MARK: permissions

enum Grant: Equatable { case off, asked, on
    var word: String { self == .on ? "on" : (self == .asked ? "asked" : "off") }
}

/// The macos "context wants to control calendar" pop-ups, asked for up front instead of mid-read.
enum Automation {
    static func status(_ bundle: String) -> Grant { check(bundle, ask: false) }

    /// Opens the app out of sight if it is not running (macos can only ask about a running app), then asks.
    static func ask(_ bundle: String) -> Grant {
        if NSRunningApplication.runningApplications(withBundleIdentifier: bundle).isEmpty,
           let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: bundle) {
            let cfg = NSWorkspace.OpenConfiguration()
            cfg.activates = false
            cfg.hides = true
            cfg.addsToRecentItems = false
            NSWorkspace.shared.openApplication(at: url, configuration: cfg, completionHandler: nil)
            for _ in 0..<30 where NSRunningApplication.runningApplications(withBundleIdentifier: bundle).isEmpty { usleep(200_000) }
            usleep(400_000)
        }
        return check(bundle, ask: true)
    }

    private static func check(_ bundle: String, ask: Bool) -> Grant {
        guard !NSRunningApplication.runningApplications(withBundleIdentifier: bundle).isEmpty else { return .off }
        var target = AEAddressDesc()
        let data = Data(bundle.utf8)
        let made = data.withUnsafeBytes { AECreateDesc(typeApplicationBundleID, $0.baseAddress, data.count, &target) }
        guard made == noErr else { return .off }
        defer { AEDisposeDesc(&target) }
        return AEDeterminePermissionToAutomateTarget(&target, typeWildCard, typeWildCard, ask) == noErr ? .on : .off
    }
}

/// A word that changes in place: the old one goes out whole, and only then does the new one come in. Never two
/// versions of a line on top of each other, however fast it is told to change.
struct Flap: View {
    let text: String
    var font: Font = .system(size: 13, weight: .medium)
    var color: Color = Ink.soft
    var lines = 1
    @Environment(\.accessibilityReduceMotion) private var reduce
    @State private var shown: String?
    @State private var lit = true
    @State private var turn = 0

    var body: some View {
        Text(shown ?? text).font(font).foregroundStyle(color).lineLimit(lines).fixedSize(horizontal: false, vertical: lines > 1)
            .opacity(lit ? 1 : 0).offset(y: lit || reduce ? 0 : -3)
            .onAppear { shown = text }
            .onChange(of: text) { _, new in
                guard shown != nil, !reduce else { shown = new; return }
                turn += 1
                let mine = turn
                withAnimation(.easeIn(duration: 0.08)) { lit = false }
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.09) {
                    guard mine == turn else { return }
                    shown = new
                    withAnimation(.easeOut(duration: 0.18)) { lit = true }
                }
            }
            .accessibilityLabel(text)
    }
}

/// The round light at the end of a row: empty, half lit while macos is asking, full when on.
struct Lamp: View {
    let grant: Grant
    @Environment(\.accessibilityReduceMotion) private var reduce
    var body: some View {
        ZStack {
            Circle().strokeBorder(grant == .off ? Ink.faint : Ink.ink, lineWidth: 1.5)
            Circle().fill(Ink.ink).padding(grant == .on ? 0 : 4.5).opacity(grant == .off ? 0 : 1)
                .scaleEffect(grant == .off ? 0.2 : 1)
        }
        .frame(width: 16, height: 16)
        .animation(Motion.snap(reduce, 0.5), value: grant)
    }
}

/// The small label and the heading, at the same place on every step.
struct StepHead: View {
    let label: String
    let title: String
    var size: CGFloat = 34
    var logo = false
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 8) {
                if logo { LogoMark(size: 20) }
                Flap(text: label, font: .system(size: 14, weight: .semibold))
            }
            .frame(height: 22, alignment: .leading).probe("head.label", .block, group: "head").reveal(0)
            Text(title).display(size).foregroundStyle(Ink.ink).lineSpacing(-2)
                .fixedSize(horizontal: false, vertical: true)
                .probe("head.title", .text, group: "head")
                .contentTransition(.opacity)
                .padding(.top, 6).reveal(1)
        }
    }
}

// MARK: one source, live

struct FeedLine: Identifiable, Equatable { let id: Int; let text: String }

/// What is being read, as it is read: the last few threads, titles or pages, moving up and out.
struct Feed: View {
    let lines: [FeedLine]
    let tint: Color
    @Environment(\.accessibilityReduceMotion) private var reduce
    @State private var blink = false
    static let rows = 5, rowHeight: CGFloat = 22   // everything on this screen sits on a 22 pt line

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(Array(lines.enumerated()), id: \.element.id) { i, line in
                let age = lines.count - 1 - i
                Text(line.text)
                    .font(.system(size: 13, weight: age == 0 ? .medium : .regular))
                    .foregroundStyle(age == 0 ? Ink.ink : Ink.soft)
                    .lineLimit(1).truncationMode(.tail)
                    .frame(height: Feed.rowHeight, alignment: .leading)
                    .opacity([1, 0.62, 0.38, 0.2, 0.09][min(age, 4)])
                    .overlay(alignment: .leading) {
                        Circle().fill(tint).frame(width: 5, height: 5).offset(x: -13).opacity(age == 0 ? (blink || reduce ? 1 : 0.25) : 0)
                    }
                    .transition(reduce ? .opacity : .asymmetric(
                        insertion: .offset(y: Feed.rowHeight).combined(with: .opacity),
                        removal: .offset(y: -Feed.rowHeight).combined(with: .opacity)))
            }
        }
        .frame(height: CGFloat(Feed.rows) * Feed.rowHeight, alignment: .topLeading)
        .frame(maxWidth: .infinity, alignment: .leading)
        .clipped()
        .animation(Motion.snap(reduce, 0.5), value: lines)
        .onAppear { if !reduce { withAnimation(.easeInOut(duration: 0.5).repeatForever(autoreverses: true)) { blink = true } } }
    }
}

/// The big number. It ticks while rows come in and takes one long breath out when the read lands. The animation is
/// its own, set on the figure itself, so a page that lets nothing else move still lets its numbers run.
struct LiveNumber: View {
    let target: Int
    let settle: Bool
    @State private var shown = 0
    @State private var long = false
    @Environment(\.accessibilityReduceMotion) private var reduce
    var body: some View {
        Ticker(value: Double(shown))
            .animation(reduce || Probe.on ? nil : (long ? .easeOut(duration: 0.85) : .linear(duration: 0.13)), value: shown)
            .onAppear { set() }
            .onChange(of: target) { _, _ in set() }
    }
    private func set() {
        long = settle && abs(target - shown) > max(40, shown / 4)
        shown = target
    }
}

struct SourceStep: View {
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduce
    let id: String
    @State private var cursor = 0          // how far the number has got through the read
    @State private var said = 0            // how far the words have got: they move a few times a second, not every tick
    @State private var beat = 0
    private let tick = Timer.publish(every: 0.07, on: .main, in: .common).autoconnect()

    var body: some View {
        let e = model.engine
        let info = Catalog.info(id)
        let state = e.state(id)
        let log = e.log[id] ?? []
        let upto = min(cursor, log.count)
        let now = upto > 0 ? log[upto - 1] : nil
        let heard = min(said, log.count) > 0 ? log[min(said, log.count) - 1] : nil
        let settled = state.finished && cursor >= log.count
        let copy = Catalog.says(id)

        VStack(alignment: .leading, spacing: 0) {
            StepHead(label: place(info), title: info.name)
            VStack(alignment: .leading, spacing: 0) {
                line(copy.what, Ink.soft)
                line(copy.reads, Ink.soft)
                line("it stays in ~/.context on this mac.", Ink.soft.opacity(0.72))
            }
            .padding(.top, 10).reveal(2)

            // the number, the line under it and the feed are one block with fixed heights, so nothing jumps
            Group {
                if let word = word(state, settled: settled) {
                    Text(word).display(56).foregroundStyle(state.finished ? Ink.ink : Ink.faint)
                } else {
                    LiveNumber(target: settled ? state.rows : (now?.rows ?? (state == .reading ? 0 : e.previous[id] ?? 0)), settle: settled)
                        .display(92).foregroundStyle(state == .reading || state.finished ? Ink.ink : Ink.faint)
                }
            }
            .lineLimit(1).minimumScaleFactor(0.5)
            .frame(height: 110, alignment: .bottomLeading)
            .probe("source.number", .block, group: "source.column")
            .padding(.top, 12).reveal(3)

            Flap(text: under(state, now: heard, settled: settled, info: info), font: .system(size: 15, weight: .medium))
                .frame(height: 22, alignment: .leading)
                .probe("source.status", .block, group: "source.column")
                .padding(.top, 6).reveal(4)

            ZStack(alignment: .topLeading) {
                Feed(lines: settled ? [] : feed(log, min(said, log.count)), tint: info.color)
                if settled, let text = aside(state, info) {
                    Text(text).font(.system(size: 15)).foregroundStyle(Ink.soft).lineSpacing(4)
                        .fixedSize(horizontal: false, vertical: true)
                        .frame(maxWidth: 420, alignment: .leading)
                        .probe("source.aside", .text, group: "source.column")
                        .transition(.opacity)
                }
            }
            .frame(height: CGFloat(Feed.rows) * Feed.rowHeight, alignment: .topLeading)
            .padding(.top, 10).reveal(5)
        }
        .animation(Motion.quick(reduce), value: settled)
        .onAppear { if reduce || Probe.on { cursor = log.count; said = cursor } }
        .onReceive(tick) { _ in
            let n = model.engine.log[id]?.count ?? 0
            if cursor < n { cursor += reduce ? n : max(1, (n - cursor) / 9) }
            beat += 1
            if beat % 12 == 0 || cursor >= n || reduce { said = cursor }
            if model.engine.state(id).finished, cursor >= n, model.settled != id {
                model.settled = id
                model.seen.insert(id)
            }
        }
    }

    /// "messages  ·  3 of 25": which shelf this is on, and how far along.
    private func place(_ info: SourceInfo) -> String {
        let order = model.engine.stepOrder
        guard let i = order.firstIndex(of: id) else { return info.group }
        return "\(info.group)  ·  \(i + 1) of \(order.count)"
    }

    private func line(_ text: String, _ color: Color) -> some View {
        Text(text).font(.system(size: 15)).foregroundStyle(color).lineLimit(1).minimumScaleFactor(0.85)
            .frame(height: 22, alignment: .leading)
    }

    /// The last few distinct labels up to where the replay has got to.
    private func feed(_ log: [Sample], _ upto: Int) -> [FeedLine] {
        var out: [FeedLine] = []
        var i = upto - 1
        while i >= 0, out.count < Feed.rows {
            let l = log[i].label
            if !l.isEmpty, out.last?.text != l { out.append(FeedLine(id: i, text: l.lowercased())) }
            i -= 1
        }
        return out.reversed()
    }

    /// A word in place of the number, when there is no number to show.
    private func word(_ state: SourceState, settled: Bool) -> String? {
        switch state {
        case .skipped(let why): return settled ? Blocked(why, Catalog.info(id)).word : nil
        case .waiting: return (model.engine.previous[id] ?? 0) > 0 ? nil : "in line"
        case .idle: return "not read"
        default: return nil
        }
    }

    private func under(_ state: SourceState, now: Sample?, settled: Bool, info: SourceInfo) -> String {
        if !settled, state == .reading || state.finished {
            if let p = now?.phase, !p.isEmpty, p != "starting" { return p }
            if let at = now?.at, !at.isEmpty { return "reading " + Words.monthLong(at) }
            return "starting"
        }
        switch state {
        case .done(let rows, let secs):
            if rows == 0 { return "nothing in here yet." }
            var s = info.noun
            if let span = model.engine.spans[id] { s += "  ·  " + Words.range(span.first, span.last) }
            if secs >= 0.1 { s += "  ·  " + String(format: "%.1f s", secs) }
            return s
        case .kept: return info.noun + "  ·  kept from last time"
        case .skipped: return "nothing was read from here"
        case .waiting: return (model.engine.previous[id] ?? 0) > 0 ? "from last time. its turn comes in a moment." : "its turn comes in a moment."
        default: return "the reading has not started."
        }
    }

    /// The plain sentence under a step that could not be read.
    private func aside(_ state: SourceState, _ info: SourceInfo) -> String? {
        switch state {
        case .kept(_, let why): return "could not refresh it this time. " + Blocked(why, info).line
        case .skipped(let why): return Blocked(why, info).line
        case .done where info.via == .browser && info.id != "telegram": return "context reads this one itself, once a day, where you are signed in."
        default: return nil
        }
    }
}

// MARK: the payoff

struct Facts: Equatable {
    var lines: [String]
    var waiting: [String]
    var total: Int
    var sources: Int

    init(_ obj: [String: Any]?, engine: Engine) {
        var all = (obj?["lines"] as? [String]) ?? []
        if let i = all.firstIndex(where: { $0.contains("waiting on a reply") }) { all.append(all.remove(at: i)) }   // end on who is waiting
        total = obj?["total"] as? Int ?? engine.totalRows
        sources = obj?["sources"] as? Int ?? engine.readCount
        if all.isEmpty { all = ["context read \(Words.count(engine.totalRows)) things from \(engine.readCount) sources."] }
        lines = all
        let people = (obj?["waiting"] as? [[String: Any]]) ?? []
        waiting = people.prefix(6).compactMap { ($0["name"] as? String)?.split(separator: " ").first.map { $0.lowercased() } }
        if !all.contains(where: { $0.contains("waiting on a reply") }) { waiting = [] }
    }
}

/// A sentence whose numbers roll up to their value.
struct RollingLine: View, Animatable {
    let text: String
    var progress: Double
    var animatableData: Double {
        get { progress }
        set { progress = newValue }
    }
    var body: some View { Text(RollingLine.render(text, progress)) }

    static func render(_ text: String, _ p: Double) -> String {
        guard p < 1 else { return text }
        var out = "", digits = ""
        func flush() {
            guard !digits.isEmpty else { return }
            let plain = digits.replacingOccurrences(of: ",", with: "")
            if let n = Int(plain), n >= 20, !(1900...2100).contains(n) || digits.contains(",") {
                let v = Int(Double(n) * p)
                out += digits.contains(",") ? Words.count(v) : String(v)
            } else { out += digits }
            digits = ""
        }
        for ch in text {
            if ch.isNumber || (ch == "," && !digits.isEmpty) { digits.append(ch) } else {
                if digits.hasSuffix(",") { digits.removeLast(); flush(); out += "," } else { flush() }
                out.append(ch)
            }
        }
        flush()
        return out
    }
}

// MARK: whose model

/// Model calls run on the user's own plan, through a signed-in claude code or codex. This is what the engine found.
struct ModelPlan: Equatable {
    var using: String      // claude, codex, api, none
    var plan: String       // "your claude plan"
    var fix: String        // one line, when nothing is signed in

    init(_ d: [String: Any]) {
        using = d["using"] as? String ?? "none"
        plan = (d["plan"] as? String ?? "").lowercased()
        fix = (d["fix"] as? String ?? "").lowercased()
    }

    var ready: Bool { using != "none" }
    var line: String {
        if ready { return "runs on " + (plan.isEmpty ? "your own plan" : plan) }
        return fix.isEmpty ? "sign in to claude code or codex once" : fix
    }
}
