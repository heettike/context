import AppKit
import SwiftUI

// The panes of settings: nine of them, eight here and keys in Keys.swift. Each is a few cards; each row is a name, a
// pill for how it stands, a whole sentence, and one control. Every word comes through SetText, so nothing here is ever
// cut with an ellipsis.

// MARK: general

struct GeneralPane: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let st = model.settings
        let e = model.engine
        let connected = st.apps.filter(\.good)
        let off = (model.access ? 0 : 1) + (model.browserOn ? 0 : 1)
        SetCard(title: "at a glance", note: "where things stand. each line opens its own pane.") {
            SetRow(title: "your ai plan", about: model.planTrouble.map { $0 + ". answers wait on it." } ?? (model.models?.runsOn.isEmpty == false ? model.models!.runsOn + "." : "answers and the read-through run on your own plan."),
                   pill: model.plan == nil ? "checking" : (model.planTrouble == nil ? "signed in" : "needs you"), tone: model.plan == nil ? .quiet : (model.planTrouble == nil ? .good : .warn)) {
                SetButton(word: "models") { model.settingsPane = .models }
            }
            SetRow(title: "connected ais", about: st.apps.isEmpty ? "looking for ai apps on this mac." : (connected.isEmpty ? "no ai app reads your context yet." : connected.map(\.name).joined(separator: ", ") + "."),
                   pill: st.apps.isEmpty ? "checking" : (st.apps.contains(where: \.broken) ? "needs you" : (connected.isEmpty ? "none" : "\(connected.count) connected")),
                   tone: st.apps.contains(where: \.broken) ? .warn : (connected.isEmpty ? .quiet : .good)) {
                SetButton(word: "open") { model.settingsPane = .ais }
            }
            SetRow(title: "permissions", about: off == 0 ? "full disk access and your browser are both on." : "what is off only means those sources wait.",
                   pill: off == 0 ? "all on" : "\(off) off", tone: off == 0 ? .good : .warn) {
                SetButton(word: "open") { model.settingsPane = .permissions }
            }
            SetRow(title: "your archive", about: e.totalRows > 0 ? "\(Words.count(e.totalRows)) things from \(e.readCount) source\(e.readCount == 1 ? "" : "s"), in a folder on this mac." : "nothing has been read yet.", last: true) {
                SetButton(word: "your data") { model.settingsPane = .data }
            }
        }
        SetCard(title: "on this mac") {
            SetRow(title: "open context when you log in", about: "it sits in the menu bar and keeps the archive current. nothing is registered with macos until you switch this on.") {
                SetSwitch(label: "open context when you log in", on: model.loginItem) { model.setLoginItem($0) }
            }
            SetRow(title: "keep the archive current", about: "while context is open it reads again by itself: this mac every few minutes, signed-in sources once a day. off, it reads only when you press sync now.") {
                SetSwitch(label: "keep the archive current", on: model.saved.hourly) { model.setHourly($0) }
            }
            SetRow(title: "sound", about: "one soft note when an answer lands while you are in another app.") {
                SetSwitch(label: "sound", on: !model.saved.soundOff) { model.saved.soundOff = !$0; model.persist() }
            }
            SetRow(title: "fetch source icons from their sites", about: model.saved.webIcons
                   ? "on: for a source with no app on this mac, context asks that service's own site once for its icon. the site sees a request from this mac that says it is context. no cookies go with it."
                   : "off: a source wears its app's icon when the app is on this mac, and a letter when it is not. nothing is asked of any site.", last: true) {
                SetSwitch(label: "fetch source icons from their sites", on: model.saved.webIcons) { model.saved.webIcons = $0; model.persist(); IconStore.shared.version += 1 }
            }
            .probe("setting.icons", .block, scrolls: true)
        }
        SetCard(title: "in answers") {
            // the engine's own word when its report carries it; the app's copy only for an engine that does not say
            let linksOn = model.settings.linksFromOthers ?? model.saved.linksFromOthers
            SetRow(title: "links from other people's messages", about: linksOn
                   ? "on: an address that only someone else's message holds is a link in an answer and in the wiki, like any other."
                   : "off: an address that only someone else's message holds is shown as its site's name in plain words, and cannot be opened from an answer or the wiki. addresses you wrote or saved are links.", last: true) {
                SetSwitch(label: "links from other people's messages", on: linksOn) {
                    model.saved.linksFromOthers = $0; model.persist(); model.settings.set("links_from_others", $0 ? "on" : "off")
                    model.settings.raw["links_from_others"] = $0 ? "on" : "off"      // said at once; the engine's report says it again when it reloads
                    model.wiki.relink()
                }
            }
            .probe("setting.links", .block, scrolls: true)
        }
        OwnCard()
    }
}

/// What context does without being asked, and what each costs on their plan. Nothing here runs without its switch.
struct OwnCard: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let s = model.saved
        let weekly = model.settings.weeklyReread, night = model.exports.catchup
        SetCard(title: "what context does on its own", note: "each of these calls your ai plan without a click from you. switch off what you do not want spent.") {
            row("nudges worded by your plan", "at most one call every 20 minutes, and only when you drift from what you set out to do or change the kind of app you are in. it sends the app in front, its window title when macos lets context read it, and today's apps, which are kept on this mac for 14 days. off: nudges come from plain rules on this mac, no call is made and nothing about your apps is written down.",
                s.nudgeModel) { model.saved.nudgeModel = $0 }
            row("name a new chat", "one small call after the first answer of a chat, sending the question and the start of the answer. off: a chat keeps its first words as its name.",
                s.nameChats) { model.saved.nameChats = $0 }
            row("look longer after an unsure answer", "when a quick answer is weak, up to three more rounds of searching and reading follow by themselves. off: the first answer stands, and deep is there when you want it.",
                s.lookDeeper) { model.saved.lookDeeper = $0 }
            row("from your past, while you write", "one call for each paragraph of twelve words or more you write in the journal, three seconds after you stop, sending that paragraph. off: the margin stays empty.",
                s.relatePast) { model.saved.relatePast = $0 }
            row("the morning card", "one call a day, during the daily read, to pick one thing from your history worth a glance. off: no card is shown.",
                s.morningCard) { model.saved.morningCard = $0; if !$0 { model.card = nil } }
            row("measure the models once a day", "one tiny call to each model your plan can run, during the daily read, to know which answer and how fast. off: the last measure stands until you press test.",
                s.modelCheck, last: weekly == nil && night == nil) { model.saved.modelCheck = $0 }
            // two the engine keeps itself, in its own settings
            if let weekly {
                row("read again every week", "once a week the engine reads again what changed, on your plan. off: it reads through only when you start it under your data.", weekly, last: night == nil, save: false) {
                    model.settings.set("reread_weekly", $0 ? "on" : "off")
                }
            }
            if let night {
                row("catch up at night", night.nightly > 0 ? "at most \(night.nightly) calls a night, on conversations not yet read and pages gone stale."
                                                           : "off: nothing is read or written at night.", night.nightly > 0, last: true, save: false) {
                    model.settings.set("nightly_calls", $0 ? "40" : "0"); model.exports.catchup?.nightly = $0 ? 40 : 0
                }
            }
        }
        .probe("setting.own.card", .block, scrolls: true)
    }

    private func row(_ title: String, _ about: String, _ on: Bool, last: Bool = false, save: Bool = true, set: @escaping (Bool) -> Void) -> some View {
        SetRow(title: title, about: about, last: last) {
            SetSwitch(label: title, on: on) { set($0); if save { model.persist() } }
        }
        .probe("setting.own", .block, group: "setting.own", scrolls: true)
    }
}

// MARK: models

struct ModelsPane: View {
    @Environment(AppModel.self) private var model
    @State private var perJob = false
    @State private var asking = false

    var body: some View {
        let st = model.settings
        let p = model.plan
        SetCard(title: "your plan", note: "answers, the first read and the wiki run on the ai plan you already pay for. context adds no charge of its own.") {
            SetRow(title: p?.ready == true ? (p!.plan.isEmpty ? "your own plan" : p!.plan) : "no plan signed in",
                   about: p == nil ? "asking the engine which plan is signed in." : (p!.ready ? (st.test.isEmpty ? "signed in on this mac. test asks it one small question, to see that it answers and how fast." : st.test + ".") : p!.line + "."),
                   pill: p == nil ? "checking" : (p!.ready ? "signed in" : "needs you"), tone: p == nil ? .quiet : (p!.ready ? .good : .warn), last: model.models?.limits.isEmpty != false && st.callsToday == nil) {
                if p?.ready == true { SetButton(word: st.testing ? "testing" : "test", busy: st.testing) { st.testPlan() } }
                else if p != nil { SetButton(word: "check again") { model.plan = nil; model.loadPlan() } }
            }
            ForEach(model.models?.limits ?? [], id: \.plan) { l in
                SetRow(title: "\(l.plan) is at its limit", about: (l.why.isEmpty ? "the plan's allowance is used up for now." : l.why) + (l.until > Date() ? " it lifts at \(Words.hourMinute(l.until))." : ""),
                       pill: "limit reached", tone: .warn, last: st.callsToday == nil)
            }
            if let today = st.callsToday {
                SetRow(title: "usage", about: "\(Words.count(today)) call\(today == 1 ? "" : "s") today  ·  \(Words.count(st.callsWeek ?? 0)) this week." + (st.cost.isEmpty ? "" : " " + st.cost + "."), last: true)
            }
        }
        if let r = model.models {
            SetCard(title: "which model does the work", note: "one choice sets all four jobs: everyday answers, long analysis, the first read, and steering the search.") {
                VStack(alignment: .leading, spacing: 12) {
                    PresetPicker(report: r) { model.setPreset($0) }
                    VStack(alignment: .leading, spacing: 8) {
                        ForEach(r.presets) { preset in
                            HStack(alignment: .firstTextBaseline, spacing: 10) {
                                SetText.label(preset.id, weight: .semibold, color: preset.id == r.preset ? Ink.ink : Ink.soft).frame(width: 62, alignment: .leading)
                                SetText.about(ModelsPane.sentence(preset.says) + (preset.recommended ? " recommended." : ""), preset.id == r.preset ? Ink.ink : Ink.soft)
                            }
                        }
                    }
                    SetFold(word: "choose per job", open: $perJob)
                }
                .padding(.horizontal, 14).padding(.vertical, 14)
                .overlay(alignment: .bottom) { Rectangle().fill(Ink.line).frame(height: 1).padding(.leading, 14) }
                .probe("setting.row", .block, group: "setting.rows", scrolls: true)
                if perJob || Probe.on && ModelsPane.unfolded {
                    ForEach(r.roles) { role in
                        SetRow(title: ModelsReport.jobWords[role.id] ?? role.id, about: ModelsPane.sentence(role.why), pill: role.chosen ? "your choice" : "", tone: .quiet) {
                            SetMenu(word: role.name, label: "model for " + (ModelsReport.jobWords[role.id] ?? role.id)) {
                                Button("follow \(r.preset)") { model.setJob(role.id, "preset") }
                                Divider()
                                ForEach(r.plans, id: \.self) { plan in
                                    Section(plan) {
                                        ForEach(r.models.filter { $0.plan == plan && $0.ok }) { m in
                                            Toggle(isOn: Binding(get: { role.ask == m.ask }, set: { _ in model.setJob(role.id, m.ask) })) {
                                                Text(m.name)
                                                Text(m.line)
                                            }
                                        }
                                    }
                                }
                            }
                        }
                        .probe("setting.job", .block, scrolls: true)
                    }
                }
                SetRow(title: "when your plan reaches its limit",
                       about: r.fallbackOn ? "on: context carries on with the quickest model your plan still runs, and says so under the answer."
                           : "off: context stops and says so, until the limit lifts.", last: true) {
                    SetSwitch(label: "carry on with a quicker model at a limit", on: r.fallbackOn) { model.setFallback($0) }
                }
            }
            SetCard(title: "speed on this mac") {
                SetRow(title: asking ? "measure now?" : (model.measuring ? "measuring" : "time to first words"),
                       about: asking ? "this asks every model a set of questions on your plan, which uses some of its allowance. it takes a few minutes."
                           : (model.measuring ? "asking each model the same questions. you can leave this page." : ModelsPane.speeds(r)), last: r.notes.isEmpty) {
                    if asking {
                        HStack(spacing: 12) {
                            Button("not now") { asking = false }.buttonStyle(QuietButton(size: 12)).fixedSize()
                            SetButton(word: "measure") { asking = false; model.measureModels() }
                        }
                    } else if !model.measuring {
                        SetButton(word: "measure on this mac") { asking = true }
                    }
                }
                .probe("setting.measure", .block, scrolls: true)
                ForEach(Array(r.notes.prefix(3).enumerated()), id: \.offset) { i, n in
                    SetRow(title: "note", about: ModelsPane.sentence(n), last: i == min(3, r.notes.count) - 1)
                }
            }
        } else {
            SetCard(title: "which model does the work") {
                SetRow(title: "models", about: model.settings.loaded ? "the engine has not said which models your plan can run. sign in to a plan first." : "asking the engine.", last: true)
            }
        }
    }

    /// set by the layout check, to see the folded rows without a click
    static var unfolded = false

    /// The engine's sentence, ending in a full stop.
    static func sentence(_ s: String) -> String {
        let t = s.trimmingCharacters(in: .whitespacesAndNewlines)
        return t.isEmpty || t.hasSuffix(".") || t.hasSuffix("?") ? t : t + "."
    }

    /// "plan a medium 2.1 s · plan a large 4.2 s. measured 2 h ago."
    static func speeds(_ r: ModelsReport) -> String {
        let timed = r.models.filter { $0.ok && $0.secs != nil }
        guard !timed.isEmpty else { return "not measured on this mac yet. until then the figures above are the engine's general ones." }
        return timed.map { "\($0.name) \(String(format: "%.1f", $0.secs!)) s" }.joined(separator: "  ·  ") + "." + (r.measuredAt.map { " measured \(Words.since($0))." } ?? "")
    }
}

/// balanced · best · lean, as one control: the three stand side by side and one is lit.
struct PresetPicker: View {
    let report: ModelsReport
    let pick: (String) -> Void

    var body: some View {
        HStack(spacing: 2) {
            ForEach(report.presets) { p in
                let on = p.id == report.preset
                Button { pick(p.id) } label: {
                    Text(p.id).font(.system(size: 12, weight: on ? .semibold : .medium)).foregroundStyle(on ? Ink.ink : Ink.soft).lineLimit(1).fixedSize()
                        .padding(.horizontal, 16).frame(height: 26)
                        .background(on ? Ink.raised : Color.clear, in: Capsule())
                        .overlay(Capsule().strokeBorder(on ? Ink.line : Color.clear, lineWidth: 1))
                        .contentShape(Capsule())
                }
                .buttonStyle(.plain).ring(13, inset: 0)
                .accessibilityLabel(p.id + (p.recommended ? ", recommended" : ""))
                .accessibilityAddTraits(on ? .isSelected : [])
            }
        }
        .padding(2)
        .background(Ink.wash, in: Capsule())
        .fixedSize()
        .probe("setting.preset", .button, scrolls: true)
    }
}

// MARK: connected ais

struct AIsPane: View {
    @Environment(AppModel.self) private var model
    @State private var details: Set<String> = []

    var body: some View {
        let st = model.settings
        let here = st.apps.filter { !$0.missing && !$0.remote }
        let missing = st.apps.filter(\.missing)
        let remote = st.apps.filter(\.remote)
        SetCard(title: "on this mac", note: "each app reads your context through one local connection that it starts itself. read only: none of them can change the archive.") {
            if here.isEmpty {
                SetRow(title: "ai apps", about: st.loaded ? "the engine has not found an ai app on this mac yet." : "looking for ai apps on this mac.", last: true)
            }
            ForEach(here) { app in
                let show = details.contains(app.id) || Probe.on && AIsPane.unfolded
                SetRow(title: app.name, about: st.said[app.id] ?? AIsPane.says(app), pill: AIsPane.pill(app).0, tone: AIsPane.pill(app).1, icon: app.id, last: app.id == here.last?.id, control: {
                    if st.busy.contains(app.id) { SetButton(word: "working", busy: true) {} }
                    else if app.changed { SetButton(word: "write it again") { st.fix(app.id) }.probe("setting.rewrite", .button, scrolls: true) }
                    else if AIsPane.needsFix(app) { SetButton(word: "fix") { st.fix(app.id) } }
                    else if app.canConnect { SetButton(word: "connect") { st.connect(app.id) } }
                    else if app.good { SetButton(word: "remove") { st.remove(app.id) } }
                }, more: {
                    if !app.path.isEmpty {
                        SetFold(word: "details", open: Binding(get: { details.contains(app.id) }, set: { if $0 { details.insert(app.id) } else { details.remove(app.id) } }))
                        if show { SetText.mono(app.path).probe("setting.path", .block, scrolls: true) }
                    }
                })
            }
        }
        // apps that are not on this mac do not get a row each
        if !missing.isEmpty {
            SetText.about("not on this mac, and ready when they are: " + missing.map(\.name).joined(separator: ", ") + ".")
                .probe("setting.missing", .block, scrolls: true)
                .padding(.top, -14).padding(.bottom, 28)
        }
        SetCard(title: st.remoteOn ? "remote (on)" : "remote (off)") {
            SetRow(title: remote.isEmpty ? "chatgpt and claude.ai" : remote.map { AIsPane.short($0.name) }.joined(separator: " and "),
                   about: "these two only take a connector they can reach over the internet. turning that on puts a door to your archive outside this mac, so it stays off until you choose it."
                       + (st.remoteOn && !st.remoteHost.isEmpty ? " it is on now, at \(st.remoteHost)." : ""),
                   pill: st.remoteOn ? "on" : "off", tone: st.remoteOn ? .warn : .quiet, last: true, control: { EmptyView() }, more: {
                if let how = remote.first(where: { !$0.how.isEmpty })?.how {
                    SetFold(word: "details", open: Binding(get: { details.contains("remote") }, set: { if $0 { details.insert("remote") } else { details.remove("remote") } }))
                    if details.contains("remote") || Probe.on && AIsPane.unfolded { SetText.about(ModelsPane.sentence(how)) }
                }
            })
        }
    }

    static var unfolded = false

    /// "chatgpt (web, then every chatgpt app)" -> "chatgpt"
    static func short(_ name: String) -> String { name.split(separator: "(").first.map { $0.trimmingCharacters(in: .whitespaces) } ?? name }

    /// claude code says for itself whether the server answers; an entry it does not list as connected is not working
    static func needsFix(_ a: MCPApp) -> Bool { a.broken || (a.id == "claude_code" && a.state == "registered") }

    static func pill(_ a: MCPApp) -> (String, Tone) {
        if a.changed { return ("changed", .warn) }
        if needsFix(a) { return ("needs you", .warn) }
        if a.state == "connected" { return ("connected", .good) }
        if a.state == "registered" { return ("registered", .good) }
        return ("not connected", .quiet)
    }

    /// One plain sentence on how an app stands.
    static func says(_ a: MCPApp) -> String {
        let name = short(a.name)
        if a.changed { return a.detail.isEmpty ? "another program changed the entry context wrote for \(name). write it again to put it back." : ModelsPane.sentence(a.detail) }
        if a.detail.contains("another server") { return "\(name) still points at an older context server, so it cannot read this archive. fix replaces that entry with this one. then quit \(name) and open it again." }
        if a.detail.contains("cannot import") || a.detail.contains("python") { return "the entry in \(name) points at a python that cannot run context. fix writes it again." }
        if a.broken { return ModelsPane.sentence(a.detail) }
        if a.id == "claude_code", a.state == "registered" { return "the entry is there, but \(name) does not list context as connected. fix writes it again." }
        if a.state == "connected" { return "\(name) lists context as connected, and can read your archive now." }
        if a.state == "registered" { return "the entry is in place. \(name) starts context by itself the next time it opens." }
        return "\(name) is on this mac and does not read your context yet."
    }
}

// MARK: sources & sync

struct SyncPane: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let e = model.engine
        let st = model.settings
        if let sch = e.schedule {
            let mins = st.fastMinutes ?? 15
            tier("on this mac", "files and apps that keep their data here. reading them is quick, so it happens often.", sch.fast.sources, "fast",
                 when: SyncPane.when(sch.fast.last, sch.fast.nextIn, sch.at),
                 cadence: "every \(mins) minutes") {
                SetMenu(word: "change", label: "how often this mac is read") {
                    ForEach([5, 10, 15, 30, 60, 120], id: \.self) { m in
                        Toggle(isOn: Binding(get: { mins == m }, set: { _ in st.set("fast_minutes", "\(m)") })) { Text("every \(m) minutes") }
                    }
                }
            }
            tier("where you are signed in", "read in your browser, from the calendar app and through telegram, once a day.", sch.daily.sources, "daily",
                 when: SyncPane.when(sch.daily.last, sch.daily.nextIn, sch.at),
                 cadence: st.dailyHour.map { "once a day, at the first look after \($0):00" } ?? "once a day, at any hour") {
                SetMenu(word: "change", label: "the hour of the daily read") {
                    Toggle(isOn: Binding(get: { st.dailyHour == nil }, set: { _ in st.set("daily_hour", "any") })) { Text("any hour") }
                    ForEach([4, 7, 9, 12, 18, 22], id: \.self) { h in
                        Toggle(isOn: Binding(get: { st.dailyHour == h }, set: { _ in st.set("daily_hour", "\(h)") })) { Text("after \(h):00") }
                    }
                }
            }
            let asked = sch.weekly.keys.sorted()
            tier("exports", "archives each site sends when asked. context asks again for the ones you chose, and reads in whatever has arrived.", asked, "weekly",
                 when: SyncPane.exports(sch), cadence: st.weeklyDay.map { "once a week, on \($0)" } ?? "once a week, on any day", services: true) {
                SetMenu(word: "change", label: "the day exports are asked for") {
                    Toggle(isOn: Binding(get: { st.weeklyDay == nil }, set: { _ in st.set("weekly_day", "any") })) { Text("any day") }
                    ForEach(["mon", "tue", "wed", "thu", "fri", "sat", "sun"], id: \.self) { d in
                        Toggle(isOn: Binding(get: { st.weeklyDay == d }, set: { _ in st.set("weekly_day", d) })) { Text(d) }
                    }
                }
            }
        } else {
            SetCard(title: "sync") {
                SetRow(title: "schedule", about: "the engine has not said when it reads. you can still read this mac now.", last: true) {
                    SetButton(word: e.syncing ? "reading" : "sync now", busy: e.syncing) { e.sync(tick: true, tier: "fast") }
                }
            }
        }
        ExportsEveryCard()
        DeclinedCard()
    }

    private func tier<C: View>(_ name: String, _ note: String, _ sources: [String], _ id: String, when: String, cadence: String, services: Bool = false,
                               @ViewBuilder change: @escaping () -> C) -> some View {
        let e = model.engine
        let names = sources.filter { !Catalog.hidden.contains($0) }.map { services ? $0 : Catalog.info($0).name }
        return SetCard(title: name, note: note) {
            SetRow(title: names.isEmpty ? "nothing in this tier yet" : "\(names.count) \(services ? "site" : "source")\(names.count == 1 ? "" : "s")", about: names.joined(separator: ", ") + (names.isEmpty ? "" : "."), control: { EmptyView() }, more: {
                if !services { Flow(spacing: 5, lineSpacing: 5) { ForEach(sources.filter { !Catalog.hidden.contains($0) }, id: \.self) { SourceIcon(id: $0, size: 18) } }.padding(.top, 2).accessibilityHidden(true) }
            })
            SetRow(title: "last and next", about: when) {
                SetButton(word: e.syncing ? "reading" : "sync now", busy: e.syncing) { e.sync(tick: true, tier: id) }
            }
            SetRow(title: "how often", about: cadence + ".", last: true, control: change)
        }
    }

    /// "last read 6 min ago. next in 9 min."
    static func when(_ last: Double, _ nextIn: Double, _ at: Date) -> String {
        let left = max(0, nextIn - Date().timeIntervalSince(at))
        let next = left < 60 ? "due now" : "next in " + (left >= 3600 ? "\(Int(left / 3600)) h" : "\(Int(left / 60)) min")
        return (last <= 0 ? "not read yet" : "last read \(Words.since(Date(timeIntervalSince1970: last)))") + ". " + next + "."
    }

    static func exports(_ sch: Schedule) -> String {
        let last = sch.weekly.values.map(\.last).max() ?? 0
        let next = sch.weekly.values.compactMap(\.nextIn).min()
        return (last <= 0 ? "nothing asked for yet" : "last asked \(Words.since(Date(timeIntervalSince1970: last)))") + "."
            + (next.map { " next in " + ($0 >= 86400 ? "\(Int($0 / 86400)) days" : "\(max(1, Int($0 / 3600))) h") + "." } ?? "")
    }
}

// MARK: permissions

struct PermissionsPane: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let req = model.requests
        let browser = req.browser?.name.isEmpty == false ? req.browser!.name : "your browser"
        SetCard(title: "what opens the most", note: "checked every two seconds. nothing here is taken on trust: a switch shows what macos really allows.") {
            SetRow(title: "full disk access", about: "imessage, mail, notes and safari are locked without it. context only reads.",
                   pill: model.access ? "on" : "needs you", tone: model.access ? .good : .warn) {
                if !model.access { SetButton(word: "open settings") { model.grant(1) } }
            }
            SetRow(title: browser, about: "slack, drive and x bookmarks are read in \(browser), where you are already signed in.",
                   pill: model.browserOn ? "on" : "needs you", tone: model.browserOn ? .good : .warn) {
                if !model.browserOn { SetButton(word: Blocked.route().button) { model.grant(2) } }
            }
            // a second ability, said by itself: reading can be on while this is off
            SetRow(title: "ask sites for exports", about: model.canAskExports ? "context can ask each site for your archive in \(browser), and read it when it lands." : model.askExportsNeeds,
                   pill: model.canAskExports ? "on" : "off", tone: model.canAskExports ? .good : .quiet, last: true)
                .probe("setting.ask", .block, scrolls: true)
        }
        SetCard(title: "asked by macos, once each", note: "macos asks before context may read another app's data. an app that is never asked is read a slower way, or waits.") {
            ForEach(Array(AppModel.automated.enumerated()), id: \.offset) { i, pair in
                let g = model.automation[pair.0] ?? .off
                SetRow(title: pair.1, about: PermissionsPane.reads[pair.1] ?? "", pill: g == .on ? "on" : (g == .asked ? "asked" : "not asked"), tone: g == .on ? .good : .quiet,
                       icon: ["calendar": "calendar", "notes": "apple_notes", "mail": "email"][pair.1] ?? "", last: i == AppModel.automated.count - 1) {
                    if g != .on { SetButton(word: "ask now", busy: model.askingAutomation) { model.askAutomation() } }
                }
            }
        }
        SetCard(title: "optional") {
            SetRow(title: "window titles", about: "optional. this is accessibility, used only for nudges and pings about what is on screen. context reads, searches and answers without it.",
                   pill: model.activity.trusted ? "on" : "optional", tone: model.activity.trusted ? .good : .quiet, last: true) {
                if !model.activity.trusted { SetButton(word: "turn on") { model.askForTitles() } }
            }
        }
    }

    static let reads = ["calendar": "three years of events, and what is coming up.", "notes": "every note that is not locked with a password.", "mail": "mail you sent, and mail from people you write to."]
}

// MARK: your data

struct DataPane: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let st = model.settings
        let b = model.wikiBuild
        let things = st.archiveRows ?? model.engine.totalRows
        SetCard(title: "the archive", note: "everything context has read. it is a folder of plain files on this mac, and it stays here.") {
            SetRow(title: "where it is", about: "", control: {
                SetButton(word: "reveal in finder") { NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: st.archivePath)]) }
            }, more: { SetText.mono(st.archiveShown) })
            SetRow(title: "what is in it", about: ([st.archiveBytes.map(SettingsModel.size)].compactMap { $0 } + ["\(Words.count(things)) thing\(things == 1 ? "" : "s")"]).joined(separator: "  ·  ")
                   + (st.archiveKinds.isEmpty ? "." : ": " + st.archiveKinds + "."))
            SetRow(title: "a copy", about: st.exported.isEmpty ? "copies only the rows context has read, the pages written from them, your journal, chats and rules, to a place you pick. everything else stays on this mac: the telegram sign-in, every key, token and .env file, the backups (other apps' settings and the rows you asked to forget), the raw exports in imports, caches, logs and settings. nothing is moved or deleted." : st.exported + ".", last: true) {
                SetButton(word: "export a copy", busy: st.exported == "copying") { st.exportCopy() }
            }
        }
        SetCard(title: "what context has understood", note: "both run on your own plan, and both say what they would take before they start.") {
            let u = st.understand
            SetRow(title: "the read-through",
                   about: u.map { $0.read >= $0.total ? "every conversation has been read once: \(Words.count($0.total)) of them. context keeps what each one means."
                       : "context reads each conversation once and keeps what it means. \(Words.count($0.total - $0.read)) are left" + (st.readLeftCalls.map { $0 > 0 ? ", about \(Words.count($0)) calls on your plan." : "." } ?? ".")
                         + (ProfileModel.nightLine.isEmpty ? "" : " " + ProfileModel.nightLine) }
                       ?? "the engine has not said how far it has read.",
                   pill: u.map { $0.read >= $0.total ? "done" : "\(Words.count($0.read)) of \(Words.count($0.total))" } ?? "", tone: u.map { $0.read >= $0.total ? .good : .quiet } ?? .quiet) {
                if let u, u.read < u.total { SetButton(word: st.reading ? "reading" : "read the rest", busy: st.reading) { st.readRest() } }
            }
            SetRow(title: "read again every week", about: "once a week, conversations that have changed are read again.") {
                if let on = st.weeklyReread { SetSwitch(label: "read again every week", on: on) { st.set("reread_weekly", $0 ? "on" : "off") } }
            }
            SetRow(title: "the wiki", about: "pages about you, written from the archive: the people, the projects, the years. it is what about you shows.",
                   pill: b.pill.0, tone: b.pill.1, last: true, control: { EmptyView() }, more: { WikiBuildBlock().padding(.top, 2) })
        }
        SetCard(title: "help and repair") {
            SetRow(title: "run setup again", about: "goes back to the first-run wall and reads every source once more. nothing already read is lost.") {
                SetButton(word: "run setup again") { model.restartOnboarding() }
            }
            SetRow(title: "a tester report", about: st.report.isEmpty
                   ? "writes a file of counts, states and timings from this mac: what worked and what broke. no message, name, address or path of yours is in it."
                   : "saved. read it before you send it: it is plain text, and you can delete any line you would rather not share.", last: true, control: {
                if st.report.isEmpty { SetButton(word: st.reporting ? "writing" : "save a report", busy: st.reporting) { st.saveReport() } }
                else { SetButton(word: "show the file") { NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: (st.report as NSString).expandingTildeInPath)]) } }
            }, more: { if !st.report.isEmpty { SetText.mono(st.report) } })
        }
    }
}

// MARK: notifications

struct NotificationsPane: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let off = model.saved.pingsOff
        let book = model.saved.pings
        SetCard(title: "pings", note: "a small panel under the menu-bar mark. one an hour and three a day at most, never at night, never twice for one thing.") {
            SetRow(title: "pings", about: off ? "off: nothing comes up by itself. what waits on you is still listed under the menu-bar mark." : "on, for the kinds switched on below.") {
                SetSwitch(label: "pings", on: !off) { model.saved.pingsOff = !$0; model.persist() }
            }
            ForEach(Array(PingKind.raised.enumerated()), id: \.offset) { i, k in
                let on = book.on(k)
                SetRow(title: k.word, about: ModelsPane.sentence(k.about), last: i == PingKind.raised.count - 1) {
                    SetSwitch(label: k.word, on: on && !off, enabled: !off) { model.saved.pings.kinds[k.rawValue] = $0; model.persist() }
                }
                .opacity(off ? 0.6 : 1)
                .probe("setting.ping.kind", .block, scrolls: true)
            }
        }
        SetCard(title: "the last ten", note: book.last.isEmpty ? "" : "newest first, and why each came up.") {
            if book.last.isEmpty {
                SetRow(title: "none yet", about: "when a ping comes up it is listed here with the reason.", last: true)
            }
            ForEach(Array(book.last.enumerated()), id: \.element.id) { i, n in
                HStack(alignment: .firstTextBaseline, spacing: 12) {
                    SetText.label(SettingsView.stamp(n.at), size: 12).frame(width: 92, alignment: .leading)
                    VStack(alignment: .leading, spacing: 3) {
                        SetText.about(n.text, Ink.ink)
                        if !n.why.isEmpty { SetText.about(n.why) }
                    }
                }
                .padding(.horizontal, 14).padding(.vertical, 10)
                .overlay(alignment: .bottom) { if i < book.last.count - 1 { Rectangle().fill(Ink.line).frame(height: 1).padding(.leading, 14) } }
                .accessibilityElement(children: .combine)
                .probe("setting.ping.note", .block, group: "setting.rows", scrolls: true)
            }
        }
    }
}

// MARK: about

struct AboutPane: View {
    @Environment(AppModel.self) private var model
    @State private var showKeys = false

    var body: some View {
        let st = model.settings
        let want = model.saved.hotkey, live = model.liveKey
        let version = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "0.1"
        SetCard(title: "context") {
            SetRow(title: "context \(version)", about: "runs on this mac, and the archive stays here. what goes out: what your own ai plan reads; requests to the sites and services you connect; and source icons, only if you switch that on.", last: st.repoLink.isEmpty)
            if !st.repoLink.isEmpty {
                SetRow(title: "source", about: "", last: true, control: {
                    SetButton(word: "open") { if let u = URL(string: st.repoLink.hasPrefix("http") ? st.repoLink : "https://" + st.repoLink) { NSWorkspace.shared.open(u) } }
                }, more: { SetText.mono(st.repoLink) })
            }
        }
        SetCard(title: "ask from anywhere", note: "a field that comes up over whatever you are doing.") {
            SetRow(title: live == "off" ? "no key" : HotKey.word(live),
                   about: want == "off" ? "off. the panel still opens from the menu-bar mark."
                       : (live == want ? "press it in any app. the menu-bar mark opens the same panel."
                          : (live == "off" ? "macos would not give context a key. pick another." : "macos would not give \(HotKey.word(want)), so \(HotKey.word(live)) is the key for now.")),
                   pill: live == "off" ? "off" : HotKey.glyphs(live), tone: live == "off" ? .quiet : .good, last: true) {
                SetMenu(word: "change", label: "the key that asks from anywhere") {
                    ForEach(HotKey.choices, id: \.id) { c in
                        Toggle(isOn: Binding(get: { want == c.id }, set: { _ in
                            model.saved.hotkey = c.id
                            model.persist()
                            if Engine.debug { model.liveKey = c.id } else { (NSApp.delegate as? AppDelegate)?.setHotKey() }
                        })) { Text(c.word) }
                    }
                }
            }
        }
        let set = st.keys.filter(\.present).count
        SetCard(title: "optional keys") {
            SetRow(title: "keys", about: st.keys.isEmpty ? (st.answered ? "none is set, and none is needed." : "the engine has not listed them.")
                   : "\(set) of \(st.keys.count) set. none is needed: each only widens what one source or model can do. names only are shown; the values stay in \(st.keysWhere).",
                   last: !(showKeys && !st.keys.isEmpty)) {
                if !st.keys.isEmpty { SetButton(word: showKeys ? "hide names" : "show names") { showKeys.toggle() } }
            }
            if showKeys {
                ForEach(Array(st.keys.enumerated()), id: \.element.name) { i, k in
                    HStack(alignment: .firstTextBaseline, spacing: 10) {
                        SetText.mono(k.name)
                        Pill(text: k.present ? "set" : "not set", tone: k.present ? .good : .quiet)
                    }
                    .padding(.horizontal, 14).padding(.vertical, 9)
                    .overlay(alignment: .bottom) { if i < st.keys.count - 1 { Rectangle().fill(Ink.line).frame(height: 1).padding(.leading, 14) } }
                    .probe("setting.key", .block, scrolls: true)
                }
            }
        }
    }
}

// MARK: declined

/// A thing the owner said no to: an export the owner chose not to ask for, a permission macos asked for and did not get. Each can be started again.
struct Declined: Identifiable {
    let id: String
    let name: String
    let about: String
    var icon = ""
    let start: () -> Void
}

extension AppModel {
    var declined: [Declined] {
        var out: [Declined] = exports.rows != nil ? exports.denied.map { r in
            Declined(id: "export:" + r.id, name: r.name + " export", about: exports.fault[r.id] ?? r.sentence, icon: Service(["id": r.id, "name": r.name])?.mark.id ?? "") { [exports] in exports.restart(r.id) }
        } : requests.declined.map { s in
            Declined(id: "export:" + s.id, name: s.name + " export", about: "you chose not to ask \(s.name) for your archive. nothing was requested.", icon: s.mark.id) { [requests] in requests.askAfterAll(s.id) }
        }
        // a source the owner tried and never switched on is not a thing the owner said no to: it stays on the sources page, with its button
        out += AppModel.automated.filter { automation[$0.0] == .asked }.map { pair in
            Declined(id: "permission:" + pair.0, name: pair.1, about: "macos asked whether context may read \(pair.1), and the answer was no. it can be changed in system settings, under privacy, automation.",
                     icon: ["calendar": "calendar", "notes": "apple_notes", "mail": "email"][pair.1] ?? "") {
                guard !Probe.on, let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation") else { return }
                NSWorkspace.shared.open(url)
            }
        }
        return out
    }
}

/// In settings, sources & sync: what the owner declined, each with the one way back. With nothing declined it is not there.
struct DeclinedCard: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let items = model.declined
        if !items.isEmpty {
            SetCard(title: "declined", note: "things you said no to. they stay off until you start them again.") {
                ForEach(Array(items.enumerated()), id: \.element.id) { i, d in
                    SetRow(title: d.name, about: d.about, pill: "declined", tone: .quiet, icon: d.icon, last: i == items.count - 1) {
                        SetButton(word: "start again", action: d.start)
                            .accessibilityLabel("start \(d.name) again")
                    }
                    .probe("setting.declined", .block, scrolls: true)
                }
            }
        }
    }
}
