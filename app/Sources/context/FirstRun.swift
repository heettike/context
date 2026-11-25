import AppKit
import SwiftUI

/// How registering context with one ai app went, in the engine's words.
struct MCPLine: Identifiable, Equatable {
    let name: String
    let status: String     // registered, already there, skipped: why
    var id: String { name }
    var ok: Bool { !status.hasPrefix("skipped") }
}

/// A letter on a quiet ground: how a tool is shown when we are naming it, not launching it.
struct Monogram: View {
    let name: String
    var size: CGFloat = 22
    var lit = false
    var body: some View {
        Text(String(name.prefix(2)))
            .font(.system(size: size * (name.count > 1 ? 0.42 : 0.52), weight: .bold)).foregroundStyle(lit ? Ink.paper : Ink.soft)
            .frame(width: size, height: size)
            .background(lit ? Ink.ink : Ink.wash, in: RoundedRectangle(cornerRadius: size * 0.28, style: .continuous))
    }
}

// MARK: screen 1: what this is, and its four switches

struct SwitchScreen: View {
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduce
    /// the ai apps it feeds: name, and the id their icon goes by
    static let ais = [("claude", "claude"), ("claude code", "claude_code"), ("codex", "codex"), ("cursor", "cursor")]

    var body: some View {
        let req = model.requests
        let browser = req.browser?.name ?? ""
        // set as an answer is: what this is, as a page in the serif on the left, and what it needs as four notes in
        // the margin, each level with nothing but its own number. in a window with no room for a margin the notes
        // follow the page
        ViewThatFits(in: .horizontal) {
            HStack(alignment: .top, spacing: 28) {
                said.frame(width: 316, alignment: .leading)
                needs.frame(width: 336, alignment: .leading)
            }
            VStack(alignment: .leading, spacing: 22) { said; needs }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .animation(Motion.spring(reduce), value: model.mcp)
    }

    /// What it is, said to them: one line, three sentences, and the ai apps it feeds.
    private var said: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("explanation first").font(Face.meta).foregroundStyle(Ink.faint).reveal(0)
            Text("one memory on this mac, for every ai you use.")
                .font(Face.said(26)).tracking(-0.4).lineSpacing(-1).foregroundStyle(Ink.ink)
                .fixedSize(horizontal: false, vertical: true)
                .probe("first.title", .text, group: "first.column")
                .accessibilityAddTraits(.isHeader)
                .padding(.top, Space.xs)
                .reveal(1)
            VStack(alignment: .leading, spacing: 8) {
                claim("it reads what you wrote, saved and built, back to your first message, into one folder on this mac.")
                claim("claude, codex and cursor read that folder through one local connection, so none starts from zero.")
                claim("your archive stays on this mac. the part of it that goes out is what your own ai plan reads to answer you.")
            }
            .padding(.top, 14).reveal(2)
            Flow(spacing: 14, lineSpacing: 6) {
                ForEach(SwitchScreen.ais, id: \.0) { ai, icon in
                    HStack(spacing: 6) {
                        SourceIcon(id: icon, size: 18)
                        Text(ai).font(Face.meta).foregroundStyle(Ink.soft).lineLimit(1).fixedSize()
                    }
                    .accessibilityElement(children: .combine)
                }
            }
            .probe("first.ais", .block, group: "first.column")
            .padding(.top, 16).reveal(3)
        }
    }

    /// What it needs before it reads anything: four switches, each a note with its number, how it stands, why it is
    /// asked for and the one button. Nothing is read until "start reading".
    private var needs: some View {
        let req = model.requests
        let browser = req.browser?.name ?? ""
        return VStack(alignment: .leading, spacing: 0) {
            Text("then four permissions. nothing is read before you say so.").font(Face.meta).foregroundStyle(Ink.faint)
                .fixedSize(horizontal: false, vertical: true).padding(.leading, 12).padding(.bottom, 6).reveal(3)
            VStack(spacing: 0) {
                SwitchRow(key: 1, title: "full disk access", why: "imessage, mail, notes and safari are locked without it.",
                          grant: model.access ? .on : (model.askedForAccess ? .asked : .off),
                          button: model.access ? nil : "open settings",
                          note: model.access ? "imessage, mail, notes and safari can be read." : nil) { model.grant(1) }
                SwitchRow(key: 2, title: browser.isEmpty ? "your browser" : browser,
                          why: "slack, drive, calendar and x bookmarks are read where you are signed in. "
                              + ((req.browser?.howToEnable ?? "").contains("--enable-browser") ? "turn on changes one setting in the browser: it lets context run scripts in its pages."
                                 : "set it up writes a small helper file into each installed browser's own folder, and shows you the extension folder to load."),
                          grant: model.browserOn ? .on : (req.enabling ? .asked : .off),
                          button: model.browserOn ? nil : ((req.browser?.howToEnable ?? "").contains("--enable-browser") ? "turn on" : "set it up"),
                          note: browserNote(req)) { model.grant(2) }
                // reading and asking are two things: once reading is on, whether a site can be asked for an export is said by itself
                if model.browserOn {
                    HStack(alignment: .firstTextBaseline, spacing: 6) {
                        Text(model.canAskExports ? "it can also ask sites for your exports." : "it cannot ask sites for exports yet: " + model.askExportsNeeds)
                            .font(.system(size: 12)).foregroundStyle(Ink.soft).lineSpacing(1)
                            .fixedSize(horizontal: false, vertical: true)
                            .probe("first.ask", .text)
                        Spacer(minLength: 8)
                        Text(model.canAskExports ? "on" : "off").font(Face.meta).foregroundStyle(model.canAskExports ? Ink.ink : Ink.soft)
                        Lamp(grant: model.canAskExports ? .on : .off).accessibilityHidden(true)
                    }
                    .padding(.leading, 12).padding(.trailing, 4).padding(.bottom, 10)
                    .accessibilityElement(children: .combine)
                    .accessibilityLabel("asking sites for exports is \(model.canAskExports ? "on" : "off")" + (model.canAskExports ? "" : ". " + model.askExportsNeeds))
                }
                SwitchRow(key: 3, title: "your ai plan", why: "answers and the first read-through run on your own plan, not ours.",
                          grant: model.plan == nil ? .asked : (model.plan!.ready ? .on : .off),
                          button: model.plan?.ready == true ? nil : "check again",
                          note: model.plan.map { $0.ready ? (model.models.map(\.runsOn).flatMap { $0.isEmpty ? nil : $0 } ?? ($0.plan.isEmpty ? "signed in" : $0.plan + ", signed in")) : $0.line },
                          chooser: model.plan?.ready == true) { model.grant(3) }
                SwitchRow(key: 4, title: "connect your ais", why: "connect writes one entry for context into the config file of each ai app on this mac. the apps can then read; none can change the archive.",
                          grant: model.mcpRunning ? .asked : (model.mcp.contains(where: \.ok) ? .on : .off),
                          button: model.mcpRunning || model.mcp.contains(where: \.ok) ? nil : "connect",
                          note: model.mcp.isEmpty ? nil : model.mcp.map { "\($0.name): \($0.status)" }.joined(separator: "  ·  "), last: true) { model.grant(4) }
            }
            .overlay(alignment: .leading) { Rectangle().fill(Ink.line).frame(width: 1) }
            .reveal(4)
            Text("macos may ask once more, by itself, when a source first needs calendar, notes or mail.")
                .font(.system(size: 12)).foregroundStyle(Ink.faint).fixedSize(horizontal: false, vertical: true)
                .probe("first.note", .text, group: "first.column")
                .padding(.top, 10).padding(.leading, 12).reveal(5)
        }
    }

    private func claim(_ text: String) -> some View {
        Text(text).font(Face.said(15)).foregroundStyle(Ink.ink).lineSpacing(4)
            .fixedSize(horizontal: false, vertical: true)
            .probe("first.claim", .text, group: "first.column")
    }

    /// The engine's own sentence on what this browser needs, without the command it would have you type.
    private func browserNote(_ req: Requests) -> String? {
        if model.browserOn { return model.bridge == true ? "extension connected" : "page scripting is on" }
        if req.enabling { return "reopening it with your tabs" }
        guard let b = req.browser else { return nil }
        if b.name.isEmpty { return "no supported browser found on this mac" }
        return b.howToEnable.contains("--enable-browser") ? "turning it on reopens \(b.name) with your tabs" : "load the context extension in \(b.name)"
    }
}

/// One switch: what it is, why, its live state, and the one button.
struct SwitchRow: View {
    let key: Int
    let title: String
    let why: String
    let grant: Grant
    let button: String?
    let note: String?
    var chooser = false        // the plan's row: "change" opens the choice of preset and model
    var last = false
    let action: () -> Void

    var body: some View {
        let lit = grant != .on
        VStack(alignment: .leading, spacing: 3) {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                // only a key that writes nothing is offered: 2 and 4 write into other apps' folders, so they take a press on their button
                Text(key == 1 || key == 3 ? "\(key)" : " ").font(Face.meta).foregroundStyle(Ink.faint).accessibilityHidden(true)
                Text(title).font(.system(size: 14, weight: .medium)).foregroundStyle(Ink.ink).lineLimit(1).fixedSize()
                    .probe("switch.title", .line)
                Spacer(minLength: 8)
                Flap(text: grant == .asked ? "waiting" : grant.word, font: Face.meta, color: grant == .on ? Ink.ink : Ink.soft)
                    .accessibilityLabel("\(title) is \(grant == .asked ? "waiting" : grant.word)")
                Lamp(grant: grant).accessibilityHidden(true)
            }
            // the name, and under it one line: why it matters, or, once there is something to say, how it stands
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(note?.isEmpty == false ? note! : why).font(.system(size: 12)).foregroundStyle(Ink.soft).lineSpacing(1)
                    .fixedSize(horizontal: false, vertical: true)
                    .probe("switch.why", .text)
                    .contentTransition(.opacity)
                if chooser { PlanChooser() }
            }
            .accessibilityElement(children: .contain)
            if let button {
                Button(button, action: action).buttonStyle(SwitchButton()).ring(14, inset: 1)
                    .probe("switch.button", .button)
                    .padding(.top, 4)
                    .accessibilityLabel("\(title): \(button)")
            }
        }
        .padding(.vertical, 10).padding(.leading, 12).padding(.trailing, 4)
        .frame(maxWidth: .infinity, alignment: .leading)
        // a switch that still needs them is a lit note: the wash and the accent rule a chosen note has beside an answer
        .background(lit ? Ink.wash.opacity(0.6) : .clear)
        .overlay(alignment: .leading) { Rectangle().fill(Ink.ember).frame(width: 1.5).opacity(lit ? 1 : 0) }
        .animation(Motion.lit(false), value: lit)
        .probe("switch.row", .block, group: "switch.rows")
    }
}

/// "change", on the plan's line: the engine's presets with its own sentence for each, then any one model of their plans.
/// A pick here is the default for every chat; the input's own menu still picks for one chat.
struct PlanChooser: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        if let r = model.models, !r.presets.isEmpty {
            Menu {
                ForEach(r.presets) { p in
                    Toggle(isOn: Binding(get: { r.preset == p.id }, set: { _ in model.setPreset(p.id) })) {
                        Text(p.id + (p.recommended ? "  ·  recommended" : ""))
                        Text(p.says)
                    }
                }
                Divider()
                Menu("one model for everything…") {
                    ForEach(r.plans, id: \.self) { plan in
                        Section(plan) {
                            ForEach(r.models.filter { $0.plan == plan && $0.ok }) { m in
                                Button { model.makeDefault(m.ask) } label: {
                                    Text(m.name)
                                    Text(m.line)
                                }
                            }
                        }
                    }
                }
            } label: {
                Text("change").font(.system(size: 12, weight: .semibold)).foregroundStyle(Ink.ink).contentShape(Rectangle())
            }
            .menuStyle(.borderlessButton).menuIndicator(.hidden).fixedSize()
            .help("which model answers, and which reads your archive")
            .accessibilityLabel("change the model that answers")
            .probe("first.change", .button)
        }
    }
}

/// The one button on a switch row: an outlined word, so the filled "start reading" stays the only filled thing.
struct SwitchButton: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View { Label(configuration: configuration) }
    struct Label: View {
        let configuration: Configuration
        @State private var hover = false
        var body: some View {
            configuration.label
                .font(.system(size: 12, weight: .semibold)).lineLimit(1).fixedSize()
                .foregroundStyle(Ink.ink)
                .padding(.horizontal, 12).frame(height: 28)
                .background(hover ? Ink.line : Ink.wash, in: Capsule())
                .scaleEffect(configuration.isPressed ? Motion.press : 1)
                .onHover { hover = $0 }
                .animation(.spring(response: 0.25, dampingFraction: 0.8), value: configuration.isPressed)
        }
    }
}

// MARK: screen 2: the wall. every source is a tile that fills with its own count as the engine reports it

struct ReadRow: Identifiable, Equatable {
    enum Kind: Equatable { case reading, done, waiting, quiet }
    let id: String
    var source: String
    var name: String
    var count: Int?
    var text: String           // where it stands, in a few words about the source as a whole. never a thread or a person
    var kind: Kind
    var button = ""            // the one action a waiting row carries
    var service = ""           // for an export row
    var wait = ""              // the one thing a waiting tile waits on
    var found = false          // the figure is what a slow source found to go through, not what it has read
    var since: Date?           // when its present stage began, for a source that is slow to show a first row
}

struct ReadingScreen: View {
    @Environment(AppModel.self) private var model
    static let columns = [GridItem(.adaptive(minimum: 164, maximum: 240), spacing: 8, alignment: .top)]

    var body: some View {
        let e = model.engine
        let groups = model.readGroups
        let total = e.syncing ? e.live.values.reduce(0, +) : e.totalRows
        let sources = groups.filter { $0.name != "exports" }.flatMap(\.rows)
        let exports = groups.first { $0.name == "exports" }?.rows ?? []
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                LiveNumber(target: total, settle: !e.syncing)
                    // the one big figure, in the serif like everything said to them; its unit in the mono beside it
                    .font(Face.said(Face.figure)).tracking(-1.2).foregroundStyle(Ink.ink).lineLimit(1).fixedSize()
                Text(e.syncing ? "things so far" : (total == 1 ? "thing" : "things"))
                    .font(.system(size: 12, design: .monospaced)).foregroundStyle(Ink.soft).lineLimit(1).fixedSize()
                Spacer(minLength: 8)
                Elapsed(since: model.readingSince, until: model.readingDone)
            }
            .probe("read.total", .line, group: "head")
            .accessibilityElement(children: .combine)
            // changed in place: this line moves several times a second while sources land, and a line that rolls or
            // fades between two values draws both at once
            Text(model.readLine).font(.system(size: 11, design: .monospaced)).foregroundStyle(Ink.soft).lineLimit(1)
                .frame(height: 20, alignment: .leading)
                .probe("read.line", .line, group: "head")
                .padding(.top, 2)
            if sources.isEmpty && exports.isEmpty {
                Text("nothing to read was found on this mac. open context and add a source from the sources page.")
                    .font(.system(size: 13)).foregroundStyle(Ink.soft).fixedSize(horizontal: false, vertical: true)
                    .probe("read.none", .text)
                    .padding(.top, 22)
            } else {
                // extraction, after the permissions: one row a source, in the order people, work, saved, then the
                // exports under their own line. every row lies on the same line of years, so what each source covers,
                // and how far the one being read has got, is seen against all the others
                let span = ReadingScreen.years(model.engine)
                HStack(spacing: 0) {
                    Color.clear.frame(width: ReadTrack.lead, height: 1)
                    YearAxis(first: span.first, last: span.last)
                    Color.clear.frame(width: ReadTrack.tail, height: 1)
                }
                .padding(.top, 14)
                ScrollView(showsIndicators: false) {
                    VStack(alignment: .leading, spacing: 0) {
                        LazyVStack(alignment: .leading, spacing: 0) {
                            ForEach(sources) { WallTile(row: $0, first: span.first, last: span.last) }
                        }
                        if !exports.isEmpty {
                            ExportAsk().padding(.top, sources.isEmpty ? 0 : 18).padding(.bottom, 10)
                            LazyVStack(alignment: .leading, spacing: 0) {
                                ForEach(exports) { WallTile(row: $0, first: span.first, last: span.last) }
                            }
                        }
                    }
                    .padding(.bottom, 10)
                    // nothing here is ever between two states: a row that arrives, moves or changes does so at once.
                    // (a figure still runs: that animation is the figure's own.)
                    .transaction { $0.animation = nil }
                }
                .padding(.top, 4)
            }
        }
    }

    /// The years the rows are laid on: from the first year any source reaches back to, to this one.
    static func years(_ e: Engine) -> (first: Int, last: Int) {
        let now = Calendar.current.component(.year, from: Date())
        var firsts = e.spans.values.compactMap { Words.parts($0.first)?.y }
        firsts += e.log.values.flatMap { $0.compactMap { Int($0.at.prefix(4)) } }
        return (max(1990, min(firsts.min() ?? now - 10, now - 1)), now)
    }
}

/// The measures of a row of the reading screen: the name's column, the line of years, the figure's column.
enum ReadTrack {
    static let lead: CGFloat = 176
    static let tail: CGFloat = 168
}

/// The years over the rows, in the mono: the first, the last, and up to three between.
struct YearAxis: View {
    let first: Int
    let last: Int
    var body: some View {
        let marks = Spine.years(first: first, now: last) + [last]
        GeometryReader { geo in
            ForEach(Array(marks.enumerated()), id: \.offset) { i, y in
                Text(i == marks.count - 1 ? "now" : String(y)).font(.system(size: 9.5, design: .monospaced)).foregroundStyle(i == marks.count - 1 ? Ink.ink : Ink.faint)
                    .lineLimit(1).fixedSize()
                    .position(x: min(max(geo.size.width * CGFloat(y - first) / CGFloat(max(1, last - first)), 12), geo.size.width - 12), y: 7)
            }
        }
        .frame(height: 14)
        .accessibilityHidden(true)
        .probe("read.axis", .block, group: "head")
    }
}

/// One source on the line of years: a hairline for the whole of time, a bar for what it has read (its first day
/// to its last), and while it is being read, the ember dot at the month it is in now.
struct TimeBar: View {
    @Environment(AppModel.self) private var model
    let row: ReadRow
    let first: Int
    let last: Int

    static func at(_ ym: String, _ first: Int, _ last: Int) -> CGFloat? {
        guard let y = Int(ym.prefix(4)) else { return nil }
        let m = Int(ym.dropFirst(5).prefix(2)) ?? 6
        return min(1, max(0, (CGFloat(y - first) + CGFloat(m - 1) / 12) / CGFloat(max(1, last - first + 1))))
    }

    var body: some View {
        let e = model.engine
        let seen = (e.log[row.source] ?? []).map(\.at).filter { !$0.isEmpty }
        let span = e.spans[row.source]
        let from = [span?.first, seen.min()].compactMap { $0 }.min().flatMap { TimeBar.at($0, first, last) }
        let to = [span?.last, seen.max()].compactMap { $0 }.max().flatMap { TimeBar.at($0, first, last) }
        let now = row.kind == .reading ? seen.last.flatMap { TimeBar.at($0, first, last) } : nil
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                Rectangle().fill(Ink.line).frame(height: 1)
                if let from, let to, row.kind == .done || row.kind == .reading {
                    RoundedRectangle(cornerRadius: 1.5).fill(row.kind == .done ? Ink.ink : Ink.soft)
                        .frame(width: max(3, geo.size.width * (to - from)), height: 3)
                        .offset(x: geo.size.width * from)
                }
                if let now { Circle().fill(Ink.ember).frame(width: 7, height: 7).offset(x: geo.size.width * now - 3.5) }
            }
            .frame(height: geo.size.height)
        }
        .frame(height: 12)
        .accessibilityHidden(true)
    }
}

/// The one line over the export tiles: what they are, and the one control that says which to ask for.
struct ExportAsk: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let req = model.requests
        let open = req.services.filter { $0.state != .arrived }
        HStack(alignment: .firstTextBaseline, spacing: 14) {
            Text("these come as downloads from each site.")
                .font(.system(size: 12, weight: .medium)).foregroundStyle(Ink.soft).lineLimit(1).fixedSize()
                .probe("read.exports.line", .line, group: "read.exports", scrolls: true)
            if !open.isEmpty {
                Menu {
                    ForEach(open) { s in
                        Toggle(isOn: Binding(get: { ExportAsk.asked(s, req) }, set: { on in if on { req.request(s.id) } else { req.decline(s.id) } })) {
                            Text(s.name)
                            Text((s.asksFor == "password" ? "asks for your password on the site" : (s.asksFor == "code" ? "sends you a code" : "you are already signed in")) + "  ·  arrives " + s.arrivesWords)
                        }
                    }
                } label: {
                    Text("choose which to ask for").font(.system(size: 12, weight: .semibold)).foregroundStyle(Ink.ink).contentShape(Rectangle())
                }
                .menuStyle(.borderlessButton).menuIndicator(.hidden).fixedSize()
                .help("context asks each site for your archive in your own browser. it arrives by itself and is read in.")
                .accessibilityLabel("choose which exports to ask for")
                .probe("read.exports.choose", .button, group: "read.exports", scrolls: true)
            }
            Spacer(minLength: 0)
        }
    }

    static func asked(_ s: Service, _ req: Requests) -> Bool {
        req.busy.contains(s.id) || s.state == .requested || s.state == .needsYou || s.state == .failed
    }
}

/// Time since the reading began. It stops when the collector does.
struct Elapsed: View {
    let since: Date?
    let until: Date?
    var body: some View {
        if let since {
            TimelineView(.periodic(from: since, by: 1)) { t in
                let s = Probe.on && until == nil ? 72 : max(0, Int((until ?? t.date).timeIntervalSince(since)))
                Text(WallTile.took(s)).font(.system(size: 13, weight: .medium)).monospacedDigit().foregroundStyle(Ink.soft)
                    .accessibilityLabel("time taken")
            }
        }
    }
}

/// One source on the wall. Waiting, it is an outline that says the one thing it waits on. Being read, its count runs
/// as the engine reports it, with how far back it has got under it and a hairline sweeping its lower edge. Read, it
/// is a filled tile with its final count. A click opens that source's own live view, which is where threads are named:
/// the wall itself only ever shows figures and words about a source as a whole, since first run may be on a shared screen.
/// Nothing in a tile rolls or fades between two values: a word or a figure is replaced where it stands.
struct WallTile: View {
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduce
    let row: ReadRow
    var first = 2010
    var last = 2026
    @State private var hover = false
    static let height: CGFloat = 44

    var body: some View {
        let dim = row.kind == .quiet || row.kind == .waiting
        let shape = Rectangle()
        HStack(alignment: .center, spacing: 0) {
            HStack(alignment: .firstTextBaseline, spacing: 7) {
                // the app's own icon, never a dot standing in for it. a source that is waiting or absent is shown paler
                SourceIcon(id: row.source, size: 16).opacity(dim ? 0.5 : 1).alignmentGuide(.firstTextBaseline) { $0[.bottom] - 3 }
                // a source's name is never cut: a long one takes a second line
                Text(row.name).font(.system(size: 13, weight: .medium)).foregroundStyle(dim ? Ink.soft : Ink.ink)
                    .lineSpacing(-1).fixedSize(horizontal: false, vertical: true)
                    .probe("read.name", .text, group: "read.names", scrolls: true)
                if row.kind == .done {
                    Image(systemName: "checkmark").font(.system(size: 8, weight: .bold)).foregroundStyle(Ink.soft)
                }
                Spacer(minLength: 0)
            }
            .frame(width: ReadTrack.lead - 10, alignment: .leading).padding(.trailing, 10)
            TimeBar(row: row, first: first, last: last)
            VStack(alignment: .trailing, spacing: 1) {
                if let n = row.count {
                    LiveNumber(target: n, settle: row.kind == .done)
                        .font(.system(size: 15, weight: .medium)).tracking(-0.2)
                        .foregroundStyle(dim || row.found ? Ink.soft : Ink.ink).lineLimit(1).fixedSize()
                        .probe("read.count", .line, group: "read.figures", scrolls: true)
                } else if !row.wait.isEmpty {
                    Text(row.wait).font(.system(size: 12)).foregroundStyle(Ink.soft).lineSpacing(-0.5).multilineTextAlignment(.trailing)
                        .fixedSize(horizontal: false, vertical: true)
                        .probe("read.wait", .text, group: "read.figures", scrolls: true)
                }
                if !row.button.isEmpty {
                    Button(row.button) { model.readAct(row) }.buttonStyle(QuietButton(size: 12)).fixedSize()
                        .accessibilityLabel("\(row.name): \(row.button)")
                        .probe("read.act", .button, group: "read.subs", scrolls: true)
                } else if let since = row.since {
                    // a slow source: its stage, and the seconds it has been at it, so a figure that stands still is not a row that has stopped
                    TimelineView(.periodic(from: since, by: 1)) { t in
                        TileSub(text: row.text + " · " + WallTile.took(Probe.on ? 48 : Int(t.date.timeIntervalSince(since))))
                    }
                } else if !row.text.isEmpty {
                    TileSub(text: row.text)
                }
            }
            .frame(width: ReadTrack.tail - 22, alignment: .trailing).padding(.leading, 14).padding(.trailing, 8)
        }
        .padding(.vertical, 8)
        .frame(minHeight: WallTile.height)
        .background(shape.fill(row.kind == .reading ? Ink.wash.opacity(hover ? 0.9 : 0.6) : Ink.wash.opacity(hover ? 0.5 : 0))
            .animation(Motion.quick(reduce), value: row.kind))
        .overlay(alignment: .bottom) { Rectangle().fill(Ink.line).frame(height: 1) }
        .overlay(alignment: .bottom) {
            if row.kind == .reading { Sweep().frame(width: ReadTrack.lead - 20, height: 1.5).frame(maxWidth: .infinity, alignment: .leading) }
        }
        .contentShape(shape)
        .onTapGesture { if row.service.isEmpty { model.jump(to: row.source) } }
        .onHover { hover = $0 }
        .focusable(row.service.isEmpty)
        .onKeyPress(.space) { if row.service.isEmpty { model.jump(to: row.source) }; return .handled }
        .ring(10, inset: 0)
        .accessibilityElement(children: .contain)
        .accessibilityLabel(spoken)
        .probe("read.row", .block, group: "read.rows", scrolls: true)
    }

    static func took(_ s: Int) -> String { s < 60 ? "\(max(0, s)) s" : "\(s / 60) min \(String(format: "%02d", s % 60)) s" }

    private var spoken: String {
        let state: String = { switch row.kind { case .reading: return "being read"; case .done: return "read"; case .waiting: return "waiting"; case .quiet: return row.text } }()
        return ([row.name, state] + (row.count.map { [Words.count($0) + (row.found ? " found" : "")] } ?? []) + (row.wait.isEmpty ? [] : [row.wait])).joined(separator: ", ")
    }
}

/// The line at the foot of a tile: up to two lines, whole.
struct TileSub: View {
    let text: String
    var body: some View {
        Text(text).font(.system(size: 10, design: .monospaced)).foregroundStyle(Ink.soft).lineSpacing(-0.5).multilineTextAlignment(.trailing)
            .fixedSize(horizontal: false, vertical: true)
            .probe("read.sub", .text, group: "read.subs", scrolls: true)
    }
}

extension AppModel {
    struct ReadGroup: Equatable { let name: String; var rows: [ReadRow] }

    /// Under the total: how far the reading is, then what it covered. Every figure is the engine's.
    var readLine: String {
        let e = engine
        let rows = readGroups.filter { $0.name != "exports" }.flatMap(\.rows)
        if e.syncing {
            let now = rows.filter { $0.kind == .reading }.count
            if signedIn == .reading {
                let read = rows.filter { $0.kind == .done }.count
                return "\(read) source\(read == 1 ? "" : "s") read" + (now > 0 ? "  ·  \(now) being read where you are signed in" : "  ·  finishing")
            }
            let read = rows.filter { e.state($0.source).finished }.count
            return "\(read) of \(rows.count) source\(rows.count == 1 ? "" : "s") read" + (now > 0 ? "  ·  \(now) being read now" : "")
        }
        guard e.readCount > 0 else { return rows.isEmpty ? "no sources" : "nothing read yet" }
        let since = e.spans.values.compactMap { Words.parts($0.first)?.y }.min()
        return "from \(e.readCount) source\(e.readCount == 1 ? "" : "s")" + (since.map { "  ·  back to \($0)" } ?? "")
    }

    /// Beside "open context": whether it is safe to go, and what is still to come.
    var readHint: String {
        if engine.syncing { return signedIn == .reading ? "this mac is read. the signed-in sources carry on if you leave." : "still reading. it carries on if you leave." }
        let waits = readGroups.flatMap(\.rows).filter { $0.kind == .waiting }.count
        if engine.readCount == 0 { return waits > 0 ? "nothing could be read yet: \(waits) source\(waits == 1 ? " waits" : "s wait") on you." : "nothing was read. you can add sources inside." }
        return "all read." + (waits > 0 ? " \(waits) source\(waits == 1 ? " waits" : "s wait") on you, and start by themselves." : " exports arrive by themselves when the sites send them.")
    }

    /// What a tile says under its figure while it is read: the kind of thing, and how far back it has got. Years only.
    private func reach(_ id: String, _ info: SourceInfo) -> String {
        let years = (engine.log[id] ?? []).compactMap { $0.at.count >= 4 ? String($0.at.prefix(4)) : nil }
        guard let a = years.min(), let b = years.max() else { return info.noun }
        return info.noun + " · " + (a == b ? a : "\(a)\u{2013}\(b)")
    }

    /// A stage as the engine names it, fit for a tile: no full stop, no source name in front, lower case.
    private func stage(_ phase: String) -> String {
        var p = phase.lowercased()
        if let r = p.range(of: ". ") { p = String(p[r.upperBound...]) }       // "found 12,345 emails. working out which address is yours": the figure is shown above
        if let r = p.range(of: ": "), p.distance(from: p.startIndex, to: r.lowerBound) < 14 { p = String(p[r.upperBound...]) }
        return p.hasSuffix(".") ? String(p.dropLast()) : p
    }

    /// Every source as one tile, in four groups, each saying truthfully where it stands.
    var readGroups: [ReadGroup] {
        let e = engine
        var by: [String: [ReadRow]] = [:]
        for id in e.order {
            let info = Catalog.info(id)
            let state = e.state(id)
            if info.via == .archive, state.rows == 0 { continue }       // an export that has not arrived is a tile under exports
            let cluster = info.group == "messages" ? "people" : (info.group == "agents" ? "work" : "saved")
            var row = ReadRow(id: id, source: id, name: info.name, count: nil, text: "", kind: .quiet)
            // read where the owner is signed in, in first run's second part, and not yet heard from
            let signing = signedIn == .reading && e.syncing && AppModel.daily.contains(id) && !e.landed.contains(id) && id != "telegram"
                && (browserOn || !Blocked.inBrowser.contains(id))
            switch state {
            case .reading:
                let last = e.log[id]?.last
                let rows = e.live[id] ?? 0
                row.kind = .reading
                if rows > 0 {
                    row.count = rows
                    row.text = reach(id, info)
                } else {
                    // nothing read yet: say the stage, what it found to go through if it said, and for how long it has been at it
                    let phase = last?.phase ?? ""
                    row.text = phase.isEmpty || phase == "starting" ? "starting" : stage(phase)
                    if let n = e.scanned[id], n > 0 { row.count = n; row.found = true }
                    if phase != "starting", !phase.isEmpty { row.since = e.phaseSince[id] }
                }
            case .done(let rows, _):
                row.kind = .done
                row.count = rows
                row.text = rows == 0 ? "nothing in it yet" : (e.spans[id].flatMap { Words.parts($0.first).map { "\(info.noun) · since \($0.y)" } } ?? info.noun)
            case .kept(let rows, let why):
                let b = Blocked(why, info)
                row.kind = .waiting
                row.count = rows
                row.text = "kept from last time"
                row.button = b.fix == nil ? "" : b.fixLabel
            case .skipped(let why):
                let b = Blocked(why, info)
                if b.empty { continue }                                 // nothing in it yet is not an error, and not a tile
                if signing {
                    row.kind = .reading
                    row.wait = "reading where you are signed in"
                } else if b.notHere { row.text = "not on this mac" } else {
                    row.kind = .waiting
                    row.wait = b.fix == .settings ? "full disk access" : b.word
                    // tried in the daily tier and not read: the engine's own sentence on why, when it has one
                    if b.fix == .daily, let said = e.schedule?.daily.results[id]?.detail, !said.isEmpty, signedIn == .done { row.wait = said }
                    row.text = b.word
                    row.button = b.fix == nil ? "" : b.fixLabel
                }
            case .waiting: row.text = "in line"; row.count = e.previous[id].flatMap { $0 > 0 ? $0 : nil }
            case .idle:
                if signing { row.kind = .reading; row.wait = "reading where you are signed in" } else { row.text = "not read yet" }
            }
            by[cluster, default: []].append(row)
        }
        var exports: [ReadRow] = []
        for s in requests.services {
            var row = ReadRow(id: "export:" + s.id, source: s.mark.id, name: s.name + " export", count: nil, text: "", kind: .quiet, service: s.id)
            if requests.busy.contains(s.id) { row.kind = .reading; row.wait = "asking the site" } else {
                switch s.state {
                case .idle: row.text = "not asked for"
                case .requested: row.wait = "asked"; row.text = "arrives \(s.arrivesWords)"
                case .needsYou: row.kind = .waiting; row.wait = s.detail.isEmpty ? "needs you in the browser" : s.detail; row.button = "check again"
                case .arrived: row.kind = .done; row.wait = "arrived"; row.text = "read"
                case .declined: row.text = "not wanted"
                case .failed: row.kind = .waiting; row.wait = s.detail.isEmpty ? "the site did not take the request" : s.detail; row.button = "try again"
                }
            }
            exports.append(row)
        }
        var out = ["people", "work", "saved"].compactMap { n in by[n].map { ReadGroup(name: n, rows: $0) } }
        if !exports.isEmpty { out.append(ReadGroup(name: "exports", rows: exports)) }
        return out
    }

    /// The one action on a waiting tile.
    func readAct(_ row: ReadRow) {
        if !row.service.isEmpty { requests.request(row.service); return }
        let why: String? = { switch engine.state(row.source) { case .skipped(let w), .kept(_, let w): return w; default: return nil } }()
        if let why { Blocked(why, Catalog.info(row.source)).run() }
    }
}
