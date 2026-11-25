import SwiftUI

private func stateWords(_ engine: Engine, _ id: String) -> (String, Bool) {
    let info = Catalog.info(id)
    switch engine.state(id) {
    // a row counts its parts too: the same thing read a second way
    case .done: let rows = engine.rowsWithParts(id); return (rows == 0 ? "empty" : Words.count(rows), true)
    case .kept: return (Words.count(engine.rowsWithParts(id)), true)
    case .reading: return (Words.count(engine.live[id] ?? 0), true)
    case .skipped(let why): return (Blocked(why, info).word, false)
    case .waiting: return ("next", false)
    case .idle: return ("not read", false)
    }
}

struct SourcesView: View {
    @Environment(AppModel.self) var model
    @Environment(\.accessibilityReduceMotion) private var reduce
    let minute = Timer.publish(every: 20, on: .main, in: .common).autoconnect()
    @State private var now = Date()

    var body: some View {
        let e = model.engine
        ScrollViewReader { proxy in
        ScrollView {
            ScrollTop()
            VStack(alignment: .leading, spacing: 0) {
                // one small line for when it was read, and under it one sentence, in the serif, for what it holds.
                // the sentence is the shelf's own: it turns into whatever tile the pointer is on
                Text(SourcesView.heading(e, next: model.nextSync, at: now))
                    .font(.system(size: Face.small, weight: .medium)).foregroundStyle(Ink.soft)
                    .probe("sources.heading", .line, scrolls: true)
                    .id(now)
                KeyNotice()
                TelegramCard()
                // tried and saved, never switched on: said here, each with the one button that finishes it
                if !model.pending.isEmpty {
                    Text(model.pending.count == 1 ? "tried, not switched on" : "\(model.pending.count) tried, not switched on")
                        .font(Face.heading).foregroundStyle(Ink.soft).padding(.top, Space.l)
                        .probe("sources.pending.head", .line, scrolls: true)
                    VStack(spacing: 0) {
                        ForEach(Array(model.pending.enumerated()), id: \.element.id) { i, p in
                            if i > 0 { Rectangle().fill(Ink.line).frame(height: 1).padding(.leading, Space.l) }
                            PendingRow(source: p)
                        }
                    }
                    .background(Ink.raised, in: RoundedRectangle(cornerRadius: Radius.card, style: .continuous))
                    .overlay(RoundedRectangle(cornerRadius: Radius.card, style: .continuous).strokeBorder(Ink.line, lineWidth: 1))
                    .padding(.top, Space.s).padding(.bottom, Space.l)
                }

                if let f = e.failure {
                    Text(f).font(.system(size: 13, weight: .medium)).foregroundStyle(Color(0xC2412D, 0xEC6A57)).padding(.top, 10)
                }

                // every source as an object, and at the end what waits on them and the way to add one
                Shelf().padding(.top, Space.s).padding(.bottom, 4)
                    .probe("home.shelf", .block, scrolls: true)

                let shown = e.order.filter { !Catalog.hidden.contains($0) }.filter { Catalog.info($0).via != .archive || e.state($0).rows > 0 || model.requests.services.isEmpty }
                    .filter { $0 != "journal" || e.state($0).rows > 0 }     // their own journal is a page of the app, not a source to list while it is empty
                if let sch = e.schedule {
                    // three tiers, as the engine refreshes them
                    let daily = shown.filter { sch.daily.sources.contains($0) }
                    let weekly = shown.filter { Catalog.info($0).via == .archive }
                    let fast = shown.filter { !daily.contains($0) && !weekly.contains($0) }
                    tier(Schedule.words("every 15 min", sch.fast, since: sch.at), nil, nil)
                    VStack(spacing: 0) { ForEach(fast, id: \.self) { SourceRow(id: $0) } }.padding(.top, 6)
                    tier(Schedule.words("daily", sch.daily, since: sch.at), "read these now", "daily")
                    VStack(spacing: 0) {
                        ForEach(daily, id: \.self) { id in
                            SourceRow(id: id, note: sch.daily.results[id].flatMap { $0.state == "ok" || $0.detail.isEmpty ? nil : $0.detail })
                        }
                    }
                    .padding(.top, 6)
                    if !weekly.isEmpty {
                        tier("weekly  ·  exports. context asks the site in \(model.requests.browser?.name ?? "your browser") and reads what lands in downloads",
                             "check now", "weekly")
                        VStack(spacing: 0) { ForEach(weekly, id: \.self) { SourceRow(id: $0) } }.padding(.top, 6)
                    }
                } else {
                    VStack(spacing: 0) { ForEach(shown, id: \.self) { SourceRow(id: $0) } }.padding(.top, 20)
                }
                // exports that still need something from them, and nothing else: one that arrived is a source above
                ExportList()

                // the foot: the one thing done here, and two quiet words. what keeps the archive current, what opens
                // at login and what may ping them are settings, and live there
                Rectangle().fill(Ink.line).frame(height: 1).padding(.top, Space.xxl)
                HStack(alignment: .center, spacing: Space.xl) {
                    Button(e.syncing ? "reading" : "sync now") { e.sync(tick: true, tier: "fast") }
                        .buttonStyle(PrimaryButton(hint: "⌘R")).disabled(e.syncing).fixedSize()
                    Spacer(minLength: Space.m)
                    Button("search exact words") { model.exactSearch() }.buttonStyle(QuietButton(size: Face.label)).help("find lines by their exact words. ⌘F").fixedSize()
                    Button("sync and pings") { model.openSettings(.sync) }.buttonStyle(QuietButton(size: Face.label)).help("how often it reads, what opens at login, and what may ping you: in settings").fixedSize()
                }
                .padding(.top, Space.l)
                .id("end")
            }
            .frame(maxWidth: 700, alignment: .leading)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.leading, Grid.edge).padding(.trailing, Grid.trailing).padding(.top, 34).padding(.bottom, 40)
        }
        .onAppear {    // development: draw the lower half when taking an offscreen render
            if ProcessInfo.processInfo.environment["CONTEXT_DEBUG"]?.contains("bottom") == true {
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) { proxy.scrollTo("end", anchor: .bottom) }
            }
        }
        }
        .onReceive(minute) { now = $0 }
        // what the tab shows is what is on disk now, not what was read when the app started
        .onAppear { if !Probe.on { e.loadStatus(); model.heal(); model.loadPending(); model.exports.load(e); model.keys.load(e) } }
    }
}

extension SourcesView {
    /// The big number is what the archive holds. Only the first full read, which starts from nothing, counts up live.
    static func total(_ e: Engine) -> Int {
        e.syncing && !e.ticking ? max(e.live.values.reduce(0, +), 0) : e.totalRows
    }

    /// "reading whatsapp" only while something is being read; otherwise when it was last synced.
    static func heading(_ e: Engine, next: String, at now: Date) -> String {
        if let doing = e.doing(at: now) { return doing + " now" }
        if e.syncing, !e.ticking { return "reading now" }
        return "synced \(Words.since(e.lastSync))" + (next.isEmpty ? "" : "  ·  \(next)")
    }

    /// A quiet heading for one refresh tier: how often, when last or next, and a word that runs it now.
    func tier(_ text: String, _ action: String?, _ name: String?) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 14) {
            Text(text).font(Face.heading).foregroundStyle(Ink.soft).lineLimit(1)
            Spacer(minLength: 8)
            if let action, let name, !model.engine.syncing {
                Button(action) { model.engine.sync(tick: true, tier: name) }.buttonStyle(QuietButton(size: 12))
            }
        }
        .padding(.top, Space.xxl)
    }
}

extension SourceRow {
    /// The line under a source that could not be read. Rows kept from last time come with the engine's own reason,
    /// shown as it is; a source with nothing gets the plain words for what is in the way.
    static func under(_ state: SourceState, why: String, blocked: Blocked, healing: Bool) -> String {
        if healing { return state.rows > 0 ? "kept from last time. full disk access is on, so it is being read again." : "full disk access is on. reading it again." }
        if case .kept = state { return "kept from last time. " + why.lowercased() }
        return blocked.line
    }
}

struct SourceRow: View {
    @Environment(AppModel.self) private var model
    let id: String
    var compact = false
    var note: String?          // the last result of a daily refresh, when it did not go through
    @State private var hover = false

    var body: some View {
        let e = model.engine
        let info = Catalog.info(id)
        let state = e.state(id)
        let (word, good) = stateWords(e, id)
        VStack(alignment: .leading, spacing: 3) {
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                // the same icon as on the home shelf: the app's own, or the monogram
                // as tall as the name from cap to descender, and centred on it
                SourceIcon.inline(id: id, font: .systemFont(ofSize: compact ? 13 : 15, weight: .semibold), muted: !good)
                    .probe("sources.icon", .block, scrolls: true)
                Text(info.name).font(.system(size: compact ? 13 : 15, weight: .semibold)).foregroundStyle(good ? Ink.ink : Ink.soft)
                if !compact, good, let s = e.spans[id] {
                    Text(Words.range(s.first, s.last)).font(.system(size: 13)).foregroundStyle(Ink.faint)
                }
                Spacer(minLength: 8)
                Text(word)
                    .font(.system(size: compact ? 13 : 15, weight: good ? .semibold : .medium)).monospacedDigit()
                    .foregroundStyle(good ? Ink.ink : Ink.faint)
                    .contentTransition(.numericText())
                if !compact, hover, state.finished, !e.syncing, !e.running.contains(id) {
                    // a source that came from an export: a fresh copy is asked for here, on the source itself
                    if let s = model.requests.arrived(for: id), !model.requests.busy.contains(s.id) {
                        Button("ask for a newer copy") { model.requests.askAfterAll(s.id) }.buttonStyle(QuietButton(size: 12))
                            .help("asks \(s.name) for a new export. it replaces this one when it arrives.")
                    }
                    Button("read again") { e.readRun.remove(id); e.read(id, first: true) }.buttonStyle(QuietButton(size: 12))
                }
                if !compact, good { Text(info.noun).font(.system(size: 13)).foregroundStyle(Ink.faint).frame(width: 74, alignment: .leading) }
            }
            if !compact, let why = { () -> String? in
                switch state {
                case .skipped(let w): return w
                case .kept(_, let w): return w
                default: return nil
                }
            }() {
                let b = Blocked(why, info)
                // macos lets the app in, so a note that says it does not is old: the source is being read again, not waiting on them
                let healing = b.fix == .settings && model.access
                HStack(spacing: 12) {
                    Text(SourceRow.under(state, why: why, blocked: b, healing: healing)).font(.system(size: 13)).foregroundStyle(Ink.faint).textSelection(.enabled)
                        .probe("sources.why", .block, scrolls: true)
                    if b.fix != nil, !healing { Button(b.fixLabel) { b.run() }.buttonStyle(QuietButton(size: 13)) }
                }
                .padding(.leading, 28)
            }
            if !compact, let note {
                Text(note).font(.system(size: 13)).foregroundStyle(Ink.faint).padding(.leading, 28)
            }
        }
        .padding(.vertical, compact ? 5 : 10)
        .contentShape(Rectangle())
        .probe("sources.row", .block, group: compact ? "" : "sources.rows", scrolls: true)
        .onHover { hover = $0 }
        .overlay(alignment: .bottom) { if !compact { Rectangle().fill(Ink.line).frame(height: 1) } }
    }
}

struct PopoverView: View {
    @Environment(AppModel.self) private var model
    let open: () -> Void

    private var quietTime: String {
        let f = DateFormatter()
        f.dateFormat = "HH:mm"
        return f.string(from: Date(timeIntervalSince1970: model.saved.quietUntil))
    }

    var body: some View {
        let e = model.engine
        let act = model.activity
        let doing = e.doing()
        VStack(alignment: .leading, spacing: 0) {
            // the head: the menu bar's own mark and the name, and what the owner has been in today
            HStack(alignment: .center, spacing: Space.s) {
                Image(nsImage: LogoMark.menuBarImage()).renderingMode(.template).foregroundStyle(Ink.ink).accessibilityHidden(true)
                Text("context").font(.system(size: Face.label, weight: .medium)).foregroundStyle(Ink.ink)
                Spacer(minLength: Space.s)
                if model.saved.onboarded, !act.app.isEmpty {
                    Text("\(act.app.lowercased())  ·  \(Activity.clock(act.total)) today")
                        .font(.system(size: Face.micro)).monospacedDigit().foregroundStyle(Ink.soft).lineLimit(1)
                }
            }
            .probe("pop.head", .block, group: "pop.rows")
            PingQueue(showWindow: open)
            if !model.saved.onboarded {
                Text("setup is not finished.").font(.system(size: Face.label)).foregroundStyle(Ink.soft).padding(.top, Space.m)
            } else if model.coach.current != nil || model.pinger.queue.isEmpty {
                NudgeBlock(nudge: model.coach.current, size: 17, compact: true).padding(.top, Space.l)
                    .probe("pop.nudge", .block, group: "pop.rows")
            }
            // what waits on them ends in a rule of its own: one rule, not two
            if model.pinger.queue.isEmpty || !model.saved.onboarded || model.coach.current != nil {
                Rectangle().fill(Ink.line).frame(height: 1).padding(.top, Space.l)
            }
            Color.clear.frame(height: Space.m)
            // the archive in two lines: every source as its icon, then the count and when it was read
            HStack(spacing: 5) {
                ForEach(e.order.filter { Catalog.info($0).via != .archive || e.state($0).rows > 0 }.prefix(16), id: \.self) { id in
                    SourceIcon(id: id, size: 13, muted: !e.state(id).finished || e.state(id).rows == 0)
                        .help(Catalog.info(id).name)
                }
                Spacer(minLength: 0)
            }
            .probe("pop.icons", .block, group: "pop.rows")
            HStack(alignment: .firstTextBaseline, spacing: 0) {
                Text(Words.count(e.totalRows)).font(.system(size: Face.small, weight: .medium)).monospacedDigit().foregroundStyle(Ink.ink)
                Text(" things  ·  " + (doing ?? "synced \(Words.since(e.lastSync))")).font(.system(size: Face.small)).foregroundStyle(Ink.soft)
            }
            .lineLimit(1)
            .padding(.top, Space.s)
            .probe("pop.count", .block, group: "pop.rows")
            if doing != nil { Sweep().frame(width: 96, height: 1.5).padding(.top, 6).accessibilityHidden(true) }
            let blocked = e.blocked
            if !blocked.isEmpty, !e.syncing {
                Text("not read: " + blocked.map { Catalog.info($0).name }.joined(separator: ", "))
                    .font(.system(size: Face.small)).foregroundStyle(Ink.faint).lineSpacing(2).padding(.top, Space.xs)
                    .fixedSize(horizontal: false, vertical: true)
                    .probe("pop.blocked", .text, group: "pop.rows")
            }
            // the plan is said here only when it cannot answer
            if let plan = model.plan, !plan.ready {
                Text(plan.line).font(.system(size: Face.small)).foregroundStyle(Ink.faint).lineSpacing(2).padding(.top, Space.xs)
                    .fixedSize(horizontal: false, vertical: true)
                    .probe("pop.plan", .text, group: "pop.rows")
            }
            // the foot: one button for the thing a menu bar click is for, then quiet words
            HStack(spacing: Space.m) {
                Button("open") { open() }.buttonStyle(SetButtonStyle())
                    .accessibilityLabel("open context")
                Button(e.syncing ? "reading" : "sync now") { e.sync(tick: true, tier: "fast") }
                    .buttonStyle(QuietButton(size: Face.small)).disabled(e.syncing || !model.saved.onboarded)
                Button(model.pinger.quiet ? "pings back on" : "quiet for an hour") { model.pinger.setQuiet(!model.pinger.quiet) }
                    .buttonStyle(QuietButton(size: Face.small))
                    .help(model.pinger.quiet ? "quiet until \(quietTime)" : "no pings for an hour")
                Spacer(minLength: 0)
                Button("quit") { NSApp.terminate(nil) }.buttonStyle(QuietButton(size: Face.small))
            }
            .padding(.top, Space.l)
            .probe("pop.foot", .button, group: "pop.rows")
        }
        .padding(Space.l)
        .frame(width: 320)
        .background(Ink.paper)
        .probe("pop.panel", .block)
    }
}

/// The popover drawn inside the test window, on the ground the ping is drawn on.
struct PopoverProof: View {
    var body: some View {
        VStack(spacing: 0) {
            PopoverView(open: {})
                .clipShape(RoundedRectangle(cornerRadius: Radius.card, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: Radius.card, style: .continuous).strokeBorder(Ink.line, lineWidth: 1))
                .padding(.top, 40)
            Spacer(minLength: 0)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Ink.wash)
    }
}
