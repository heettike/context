import AppKit
import SwiftUI

// What can read the archive (DESIGN.md): the programs on this mac that read the archive through the local api, what each
// one's key opens, what each really pulled, and what no key may read. The engine's shapes (ctx/api.py `command`):
//   api-keys        {}                        {"keys": [{"name","made","used","calls","expires" (0: never),"expired","kind": all|rows|profile|none,"reads","scope",
//                                               "preset","rows_per_day","calls_today","rows_today","calls_7d","rows_7d","unusual","held","narrowed"?}],
//                                              "running","url","never","hold_unusual","presets": {name: what it reads}}
//   api-log         {"key", "days"?: 14}      {"key","days": [{"day","calls","rows","bytes","sources","refusals"}]}  oldest first
//   api-key-make    {"name","preset"? | "scope"? | "all"?: true,"days"?: 30}   {"name","key" (shown once),"reads","expires","url","warning"?}
//   api-key-revoke  {"name"}                  {"revoked": bool}
//   api-key-set     {"name","preset"? | "scope"? | "all"?,"days"?,"rows_per_day"?,"clear"?: true}   the key's row
//   api-never       {} | {"sources"?,"people"?,"ranges"?: [[after, before]]} | {"hold_unusual": bool}   {"never","hold_unusual"}
// A mistake comes back as {"error": sentence}. What a key reads is said in the engine's own words (`reads`, `presets`,
// `warning`): the app never makes that sentence up.

struct ApiKey: Identifiable, Equatable {
    var name: String
    var reads = ""
    var kind = "none"           // all, rows, profile, none
    var preset = ""
    var expires: Double = 0     // 0: never
    var expired = false
    var rowsPerDay = 0
    var callsToday = 0, rowsToday = 0, calls7 = 0, rows7 = 0
    var unusual = false
    var held = false
    var narrowed = ""           // the engine's sentence when an update narrowed it: it read everything under an older key file
    var sources: [String] = []  // its own limits, as the engine keeps them
    var people: [String] = []
    var after = ""
    var before = ""
    var via = "api"             // "mcp": an ai app connected on this mac, named mcp:<app>. "api": a program with a key
    var id: String { name }
    var mcp: Bool { via == "mcp" }
    /// what the row is called: an ai app goes by its own name, without the engine's "mcp:" in front
    var shown: String { mcp && name.hasPrefix("mcp:") ? String(name.dropFirst(4)).replacingOccurrences(of: "_", with: " ") : name }
    /// closed by them: it stays listed and reads nothing
    var closed: Bool { kind == "none" && reads.contains("closed") }

    init?(_ any: Any?) {
        guard let d = any as? [String: Any], let n = d["name"] as? String, !n.isEmpty else { return nil }
        name = n
        via = d["via"] as? String ?? (n.hasPrefix("mcp:") ? "mcp" : "api")
        reads = (d["reads"] as? String ?? "").lowercased()
        kind = d["kind"] as? String ?? "none"
        preset = d["preset"] as? String ?? ""
        expires = (d["expires"] as? Double) ?? Double(d["expires"] as? Int ?? 0)
        expired = d["expired"] as? Bool ?? false
        rowsPerDay = d["rows_per_day"] as? Int ?? 0
        callsToday = d["calls_today"] as? Int ?? 0
        rowsToday = d["rows_today"] as? Int ?? 0
        calls7 = d["calls_7d"] as? Int ?? 0
        rows7 = d["rows_7d"] as? Int ?? 0
        unusual = d["unusual"] as? Bool ?? false
        held = d["held"] as? Bool ?? false
        narrowed = (d["narrowed"] as? String ?? "").lowercased()
        let sc = d["scope"] as? [String: Any] ?? [:]
        sources = sc["sources"] as? [String] ?? []
        people = sc["people"] as? [String] ?? []
        after = sc["after"] as? String ?? ""
        before = sc["before"] as? String ?? ""
    }

    /// Days until it expires, from a given moment; nil when it never does.
    func daysLeft(_ now: Date = Date()) -> Int? { expires > 0 ? Int(((expires - now.timeIntervalSince1970) / 86400).rounded(.up)) : nil }

    /// "expires in 12 days", "expires today", "expired", "does not expire"
    func expiry(_ now: Date = Date()) -> String {
        if expired { return "expired" }
        guard let d = daysLeft(now) else { return "does not expire" }
        return d <= 0 ? "expires today" : "expires in \(d) day\(d == 1 ? "" : "s")"
    }

    /// the kind, said plainly
    var kindWord: String { ["all": "everything", "rows": "some messages", "profile": "the short profile only", "none": "nothing yet"][kind] ?? kind }

    /// "today 240 messages in 8 calls · 7 days 1,600 in 50"
    var today: String { "today \(Words.count(rowsToday)) message\(rowsToday == 1 ? "" : "s") in \(Words.count(callsToday)) call\(callsToday == 1 ? "" : "s")" }
    var week: String { "7 days \(Words.count(rows7)) in \(Words.count(calls7))" }
}

struct ApiDay: Identifiable, Equatable {
    var day: String
    var calls = 0, rows = 0, refusals = 0
    var sources: [String] = []
    var id: String { day }
    init?(_ any: Any?) {
        guard let d = any as? [String: Any], let day = d["day"] as? String else { return nil }
        self.day = day
        calls = d["calls"] as? Int ?? 0
        rows = d["rows"] as? Int ?? 0
        refusals = d["refusals"] as? Int ?? 0
        sources = d["sources"] as? [String] ?? []
    }
}

struct ApiNever: Equatable {
    var sources: [String] = []
    var people: [String] = []
    var ranges: [[String]] = []
    init() {}
    init(_ any: Any?) {
        let d = any as? [String: Any] ?? [:]
        sources = d["sources"] as? [String] ?? []
        people = d["people"] as? [String] ?? []
        ranges = (d["ranges"] as? [[Any]] ?? []).map { $0.map { $0 as? String ?? "" } }.filter { $0.count == 2 }
    }
    /// "2019-01-01 to 2019-12-31, until 2015-06-30"
    var rangesText: String { ranges.map { r in r[0].isEmpty ? "until \(r[1])" : (r[1].isEmpty ? "from \(r[0])" : "\(r[0]) to \(r[1])") }.joined(separator: ", ") }
    var isEmpty: Bool { sources.isEmpty && people.isEmpty && ranges.isEmpty }
}

struct NewKey: Equatable {
    var name = "", key = "", reads = "", url = "", warning = ""
    var expires: Double = 0
    init?(_ any: Any?) {
        guard let d = any as? [String: Any], let k = d["key"] as? String, !k.isEmpty else { return nil }
        name = d["name"] as? String ?? ""
        key = k
        reads = (d["reads"] as? String ?? "").lowercased()
        url = d["url"] as? String ?? ""
        warning = (d["warning"] as? String ?? "").lowercased()
        expires = (d["expires"] as? Double) ?? Double(d["expires"] as? Int ?? 0)
    }
}

@Observable final class KeysModel {
    var known: Bool?                // nil until asked; false when the engine has no api-keys
    var keys: [ApiKey] = []
    var presets: [(name: String, reads: String)] = []
    var never = ApiNever()
    var holdUnusual = true
    var url = ""
    var running = true
    /// The engine's sentence for a key that reads everything. `api-keys` may carry it as "warning"; until it does, this
    /// is the sentence `api-key-make` answers with, word for word.
    var warning = "this key reads the whole archive, through every endpoint."
    var open: String?               // the key that is unfolded
    var log: [String: [ApiDay]] = [:]
    var fault = ""
    // making one
    var making = false
    var draftName = ""
    var pick = ""                   // a preset's name, "own", or "all"; "" is nothing chosen, which is how it starts
    var draftNever = false          // the new key never expires. off, it lasts 30 days
    var draftSources = ""           // limits of their own for the new key
    var draftPeople = ""
    var draftAfter = ""
    var draftBefore = ""
    var made: NewKey?
    var copied = false
    var revoking: String?           // a key whose revoke has been pressed once
    var reopening: String?          // a closed ai app being opened again: its slices are shown to choose from
    // the opened key's own limits, as they are being typed
    var ownSources = ""
    var ownPeople = ""
    var ownAfter = ""
    var ownBefore = ""
    // the never list, as it is being typed
    var neverPeople = ""
    var neverSources = ""
    var neverRanges = ""
    var neverFault = ""             // what was wrong with the days the owner typed: said under the field, and nothing saved
    @ObservationIgnored weak var engine: Engine?

    /// The one quiet line for the sources page: a key that is held, or one that expires within three days. nil otherwise.
    var notice: String? {
        if let k = keys.first(where: { $0.held }) { return (k.mcp ? "\(k.shown) is held" : "the key for \(k.name) is held") + ": it read far more than it usually does today." }
        if let k = keys.first(where: { !$0.mcp && !$0.expired && ($0.daysLeft() ?? 99) <= 3 }) { return "the key for \(k.name) \(k.expiry())." }
        return nil
    }

    private func take(_ any: Any?) {
        guard let d = any as? [String: Any] else { if known == nil { known = false }; return }
        if let e = d["error"] as? String { fault = e.lowercased(); return }
        fault = ""
        if let rows = d["keys"] as? [[String: Any]] {
            known = true
            keys = rows.compactMap { ApiKey($0) }
            url = d["url"] as? String ?? url
            running = d["running"] as? Bool ?? true
            if let w = d["warning"] as? String, !w.isEmpty { warning = w.lowercased() }
            presets = ((d["presets"] as? [String: String]) ?? [:]).sorted { $0.key < $1.key }.map { ($0.key, $0.value.lowercased()) }
        }
        if d["never"] != nil {
            never = ApiNever(d["never"])
            holdUnusual = d["hold_unusual"] as? Bool ?? holdUnusual
            neverPeople = never.people.joined(separator: ", ")
            neverSources = never.sources.joined(separator: ", ")
            neverRanges = never.rangesText
        }
    }

    func load(_ engine: Engine) {
        self.engine = engine
        guard !Probe.on else { return }
        engine.client.call(["cmd": "api-keys"], timeout: 30) { [weak self] reply in self?.take(reply) }
    }

    private func call(_ req: [String: Any], then: ((Any?) -> Void)? = nil) {
        guard !Probe.on, let engine else { return }
        engine.client.call(req, timeout: 30) { [weak self] reply in
            guard let self else { return }
            if let e = (reply as? [String: Any])?["error"] as? String { self.fault = e.lowercased(); return }
            self.fault = ""
            then?(reply)
            self.load(engine)
        }
    }

    func toggle(_ name: String) {
        open = open == name ? nil : name
        revoking = nil
        fillOwn()
        guard let name = open, !Probe.on, let engine else { return }
        engine.client.call(["cmd": "api-log", "key": name, "days": 14], timeout: 30) { [weak self] reply in
            guard let d = reply as? [String: Any], let days = d["days"] as? [[String: Any]] else { return }
            self?.log[name] = days.compactMap { ApiDay($0) }
        }
    }

    /// The fields under "or set its limits yourself" start from what the opened key has.
    func fillOwn() {
        let k = keys.first { $0.name == open }
        ownSources = k?.sources.joined(separator: ", ") ?? ""
        ownPeople = k?.people.joined(separator: ", ") ?? ""
        ownAfter = k?.after ?? ""
        ownBefore = k?.before ?? ""
    }

    /// Only the parts the owner filled in are sent; the engine says so in a sentence when one cannot be read.
    static func scope(_ sources: String, _ people: String, _ after: String, _ before: String) -> [String: Any] {
        var scope: [String: Any] = [:]
        if !list(sources).isEmpty { scope["sources"] = list(sources) }
        if !list(people).isEmpty { scope["people"] = list(people) }
        let a = after.trimmingCharacters(in: .whitespaces), b = before.trimmingCharacters(in: .whitespaces)
        if !a.isEmpty { scope["after"] = a }
        if !b.isEmpty { scope["before"] = b }
        return scope
    }

    func saveOwn(_ name: String) {
        let scope = KeysModel.scope(ownSources, ownPeople, ownAfter, ownBefore)
        guard !scope.isEmpty else { return }
        set(name, ["scope": scope])
    }

    func set(_ name: String, _ change: [String: Any]) { var req = change; req["cmd"] = "api-key-set"; req["name"] = name; call(req) }
    func clear(_ name: String) { set(name, ["clear": true]) }

    /// Revoke takes two presses: the first arms it.
    func revoke(_ name: String) {
        guard revoking == name else { revoking = name; return }
        revoking = nil
        open = nil
        call(["cmd": "api-key-revoke", "name": name])
    }

    func make() {
        let name = draftName.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !name.isEmpty, !pick.isEmpty else { return }
        var req: [String: Any] = ["cmd": "api-key-make", "name": name]
        if draftNever { req["never"] = true } else { req["days"] = 30 }
        if pick == "all" { req["all"] = true }
        else if pick == "own" {
            let scope = KeysModel.scope(draftSources, draftPeople, draftAfter, draftBefore)
            guard !scope.isEmpty else { fault = "give the key at least one limit: sources, people, or a day it starts or ends."; return }
            req["scope"] = scope
        } else { req["preset"] = pick }
        call(req) { [weak self] reply in
            guard let self, let k = NewKey(reply) else { return }
            self.made = k
            self.copied = false
            self.making = false
            self.draftName = ""
            self.pick = ""
            self.draftNever = false
            self.draftSources = ""; self.draftPeople = ""; self.draftAfter = ""; self.draftBefore = ""
        }
    }

    static func list(_ s: String) -> [String] { s.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces).lowercased() }.filter { !$0.isEmpty } }

    /// "2019-01-01 to 2019-12-31, until 2015-06-30, from 2024-01-01" -> [[after, before]]
    static func ranges(_ s: String) -> [[String]] {
        list(s).compactMap { part in
            let day = #"\d{4}-\d{2}-\d{2}"#
            let found = (try? NSRegularExpression(pattern: day))?.matches(in: part, range: NSRange(part.startIndex..., in: part)).compactMap { Range($0.range, in: part).map { String(part[$0]) } } ?? []
            if found.count == 2 { return [found[0], found[1]] }
            if found.count == 1 { return part.hasPrefix("until") || part.hasPrefix("before") ? ["", found[0]] : [found[0], ""] }
            return nil
        }
    }

    /// The parts of the days field that could not be read as a stretch of days.
    static func unread(_ s: String) -> [String] { list(s).filter { ranges($0).isEmpty } }

    func saveNever() {
        let bad = KeysModel.unread(neverRanges)
        guard bad.isEmpty else {
            neverFault = "could not read \(bad.map { "\"\($0)\"" }.joined(separator: ", ")) as days, so nothing was saved. write a stretch as 2019-01-01 to 2019-12-31, until 2015-06-30, or from 2024-01-01."
            return
        }
        neverFault = ""
        call(["cmd": "api-never", "people": KeysModel.list(neverPeople), "sources": KeysModel.list(neverSources), "ranges": KeysModel.ranges(neverRanges)]) { [weak self] reply in self?.take(reply) }
    }
    func hold(_ on: Bool) { holdUnusual = on; call(["cmd": "api-never", "hold_unusual": on]) { [weak self] reply in self?.take(reply) } }

    func reset() {
        known = nil; keys = []; presets = []; never = ApiNever(); holdUnusual = true; url = ""; running = true; open = nil; log = [:]; fault = ""
        making = false; draftName = ""; pick = ""; made = nil; copied = false; revoking = nil; reopening = nil; ownSources = ""; ownPeople = ""; ownAfter = ""; ownBefore = ""; neverPeople = ""; neverSources = ""; neverRanges = ""; neverFault = ""; draftNever = false; draftSources = ""; draftPeople = ""; draftAfter = ""; draftBefore = ""
    }
}

// MARK: the pane

struct KeysPane: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let k = model.keys
        if k.known == false {
            SetCard(title: "what can read your archive") {
                SetRow(title: "not in this engine", about: "the engine on this mac does not list what reads the archive. update context and look again.", last: true)
            }
        } else {
            if let made = k.made { MadeKeyCard(key: made) }
            let apps = k.keys.filter(\.mcp), programs = k.keys.filter { !$0.mcp }
            // ai apps first: they are connected over mcp, each with limits of its own, and hold no key
            if !apps.isEmpty {
                SetCard(title: "ai apps connected on this mac", note: "each ai app reads through its own connection. it starts at the short profile, and reads more only when you choose a slice or limits for it here. connect and remove apps under connected ais.") {
                    ForEach(Array(apps.enumerated()), id: \.element.id) { i, key in KeyRow(key: key, last: i == apps.count - 1) }
                }
                .probe("key.apps", .block, scrolls: true)
            }
            SetCard(title: "programs with a key", note: (k.running ? "" : "the api is not running now, so no key is being answered. ") + "a program on this mac that holds a key reads what that key opens, and nothing else. every call is counted here.") {
                if programs.isEmpty {
                    SetRow(title: "no keys yet", about: "nothing can read your archive over the api until you make a key and give it to a program.", last: !k.fault.isEmpty ? false : true)
                        .probe("key.none", .block, scrolls: true)
                }
                ForEach(Array(programs.enumerated()), id: \.element.id) { i, key in KeyRow(key: key, last: i == programs.count - 1 && k.fault.isEmpty) }
                if !k.fault.isEmpty { SetRow(title: "that did not work", about: k.fault, last: true).probe("key.fault", .block, scrolls: true) }
            }
            MakeKeyCard()
            NeverCard()
        }
    }
}

/// One key: its name, what it reads in the engine's words, how it stands, and what it pulled. Opened: its days, and
/// the ways to change it.
struct KeyRow: View {
    @Environment(AppModel.self) private var model
    let key: ApiKey
    let last: Bool

    var body: some View {
        let k = model.keys
        let open = k.open == key.name
        // a key that reads everything always carries that mark, whatever else is true of it
        let marks = [key.held ? "held" : (key.unusual ? "unusual today" : ""), key.expired ? "expired" : "", key.kind == "all" ? "reads everything" : "",
                     key.narrowed.isEmpty ? "" : "narrowed by an update"].filter { !$0.isEmpty }
        let state: (String, Tone) = marks.isEmpty ? (key.kind == "none" ? (key.closed ? "closed" : "reads nothing", .quiet) : ("", .quiet)) : (marks.joined(separator: " · "), .warn)
        SetRow(title: key.shown, about: key.reads.isEmpty ? key.kindWord + "." : key.reads, pill: state.0, tone: state.1, last: last && !open, control: {
            SetFold(word: "details", open: Binding(get: { open }, set: { _ in k.toggle(key.name) }))
        }, more: {
            // a key that reads everything says so twice: in its mark, and here in words
            Flow(spacing: Space.m, lineSpacing: 2) {
                ForEach([key.kind == "all" || key.closed ? "" : key.kindWord, key.expired || key.mcp ? "" : key.expiry(), key.today, key.week].filter { !$0.isEmpty }, id: \.self) { w in
                    SetText.label(w, size: 10.5, weight: .regular, color: Ink.faint)
                }
            }
            .padding(.top, 2)
            if !key.narrowed.isEmpty {
                // it read everything before an update and was narrowed: the engine's own words, and the presets that open it again
                VStack(alignment: .leading, spacing: Space.s) {
                    SetText.about(key.narrowed)
                    Flow(spacing: Space.s, lineSpacing: Space.s) {
                        ForEach(k.presets, id: \.name) { p in
                            Button(p.name) { k.set(key.name, ["preset": p.name]) }
                                .buttonStyle(Starter())
                                .help(p.reads).accessibilityLabel("let \(key.shown) read \(p.name): \(p.reads)")
                                .probe("key.narrowed.slice", .block, group: "key.narrowed", scrolls: true)
                        }
                    }
                }
                .padding(.top, Space.s)
            }
            if key.closed, key.mcp {
                // closed by the owner: one press to open it again, which asks what it may read
                VStack(alignment: .leading, spacing: Space.s) {
                    if k.reopening == key.name {
                        SetText.about("open it again to read what?")
                        Flow(spacing: Space.s, lineSpacing: Space.s) {
                            ForEach(k.presets, id: \.name) { p in
                                Button(p.name) { k.reopening = nil; k.set(key.name, ["preset": p.name]) }
                                    .buttonStyle(Starter())
                                    .help(p.reads).accessibilityLabel("open \(key.shown) again to read \(p.name): \(p.reads)")
                                    .probe("key.reopen.slice", .block, group: "key.reopen", scrolls: true)
                            }
                        }
                    } else {
                        SetButton(word: "open again") { k.reopening = key.name }
                            .accessibilityLabel("open \(key.shown) again. you choose what it may read")
                            .probe("key.reopen", .button, scrolls: true)
                    }
                }
                .padding(.top, Space.s)
            }
            if key.held || key.unusual {
                // under the counts, not beside the name: the row keeps its width, and the reason sits with the way out
                HStack(alignment: .firstTextBaseline, spacing: Space.m) {
                    SetText.about(key.held ? "it read far more than it usually does today, so its calls are refused until you clear it." : "it read far more than it usually does today.")
                    SetButton(word: "clear") { k.clear(key.name) }
                        .accessibilityLabel("clear the \(key.held ? "hold" : "mark") on \(key.name)")
                        .probe("key.clear", .button, scrolls: true)
                }
                .padding(.top, Space.s)
            }
            if open { KeyDetail(key: key).padding(.top, Space.m) }
        })
        .probe("key.row", .block, scrolls: true)
    }
}

/// A key, opened: a strip of its last fourteen days, what it touched, and the ways to change, renew, limit and revoke it.
struct KeyDetail: View {
    @Environment(AppModel.self) private var model
    let key: ApiKey

    private func own(_ name: String, _ prompt: String, _ text: Binding<String>) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: Space.m) {
            Text(name).font(.system(size: Face.small, weight: .medium)).foregroundStyle(Ink.soft).frame(width: 56, alignment: .leading)
            TextField("", text: text, prompt: Text(prompt).foregroundStyle(Ink.faint))
                .textFieldStyle(.plain).font(.system(size: Face.small)).foregroundStyle(Ink.ink).tint(Ink.ember)
                .onSubmit { model.keys.saveOwn(key.name) }
                .accessibilityLabel("this key's limits: \(name)")
        }
        .padding(.vertical, 7)
        .overlay(alignment: .bottom) { Rectangle().fill(Ink.line).frame(height: 1) }
        .probe("key.own", .block, group: "key.owns", scrolls: true)
    }

    var body: some View {
        @Bindable var k = model.keys
        let days = k.log[key.name] ?? []
        let top = max(1, days.map(\.rows).max() ?? 1)
        VStack(alignment: .leading, spacing: Space.m) {
            // the strip: a bar a day for the messages it was given, the calls under it, a dot where it was refused
            VStack(alignment: .leading, spacing: 4) {
                SetText.label(days.isEmpty ? "the last 14 days" : "the last \(days.count) days: messages given", size: 10.5, weight: .regular, color: Ink.faint)
                if days.isEmpty { SetText.about("no calls yet.") } else {
                HStack(alignment: .bottom, spacing: 3) {
                    ForEach(days) { d in
                        VStack(spacing: 2) {
                            Circle().fill(Ink.ember).frame(width: 4, height: 4).opacity(d.refusals > 0 ? 1 : 0)
                            RoundedRectangle(cornerRadius: 1).fill(d.rows > 0 ? Ink.ink : Ink.line)
                                .frame(height: d.rows > 0 ? max(3, 36 * CGFloat((Double(d.rows) / Double(top)).squareRoot())) : 1)
                            Text(String(d.day.suffix(2))).font(.system(size: 8, design: .monospaced)).foregroundStyle(Ink.faint)
                        }
                        .frame(maxWidth: .infinity, alignment: .bottom)
                        .help("\(Words.day(d.day)): \(Words.count(d.rows)) messages in \(Words.count(d.calls)) calls" + (d.sources.isEmpty ? "" : ", from \(d.sources.joined(separator: ", "))") + (d.refusals > 0 ? ". refused \(d.refusals) time\(d.refusals == 1 ? "" : "s")" : ""))
                        .accessibilityElement(children: .ignore)
                        .accessibilityLabel("\(Words.day(d.day)): \(d.rows) messages, \(d.calls) calls, \(d.refusals) refused")
                    }
                }
                .frame(height: 58, alignment: .bottom)
                .probe("key.strip", .block, scrolls: true)
                }
                let touched = Array(Set(days.flatMap(\.sources))).sorted()
                let refused = days.reduce(0) { $0 + $1.refusals }
                if !days.isEmpty { SetText.about((touched.isEmpty ? "it touched no source in these days." : "it touched: " + touched.map { Catalog.info($0).name }.joined(separator: ", ") + ".") + (refused > 0 ? " it was refused \(refused) time\(refused == 1 ? "" : "s"), marked with a dot: it asked for something its key does not open." : "")) }
            }
            // what it reads: one of the engine's own slices, each said in the engine's words
            VStack(alignment: .leading, spacing: 6) {
                SetText.label("change what it reads", size: 10.5, weight: .regular, color: Ink.faint)
                Flow(spacing: Space.s, lineSpacing: Space.s) {
                    ForEach(k.presets, id: \.name) { p in
                        Button(p.name) { k.set(key.name, ["preset": p.name]) }
                            .buttonStyle(key.preset == p.name ? Starter(lead: true) : Starter())
                            .help(p.reads).accessibilityLabel("\(p.name): \(p.reads)")
                            .probe("key.preset", .block, group: "key.presets", scrolls: true)
                    }
                }
            }
            VStack(alignment: .leading, spacing: 0) {
                SetText.label("or set its limits yourself. return saves.", size: 10.5, weight: .regular, color: Ink.faint).padding(.bottom, 4)
                own("sources", "for example slack, email", $k.ownSources)
                own("people", "names, with commas between", $k.ownPeople)
                own("from", "a day, as 2024-01-01", $k.ownAfter)
                own("until", "a day, as 2025-12-31", $k.ownBefore)
            }
            Flow(spacing: Space.l, lineSpacing: Space.s) {
                if !key.mcp { Button("renew for 30 days") { k.set(key.name, ["days": 30]) }.buttonStyle(QuietButton(size: Face.small)) }
                if key.expires > 0, !key.mcp {
                    Button("never expires") { k.set(key.name, ["never": true]) }.buttonStyle(QuietButton(size: Face.small))
                        .help("the key works until you revoke it. a key that expires is the safer one.")
                        .accessibilityLabel("make \(key.name) a key that never expires")
                }
                Menu {
                    ForEach([200, 1000, 5000, 20000], id: \.self) { n in
                        Toggle(isOn: Binding(get: { key.rowsPerDay == n }, set: { _ in k.set(key.name, ["rows_per_day": n]) })) { Text("\(Words.count(n)) messages a day") }
                    }
                } label: { Text(key.rowsPerDay > 0 ? "at most \(Words.count(key.rowsPerDay)) a day" : "messages a day").font(.system(size: Face.small, weight: .medium)).foregroundStyle(Ink.soft) }
                .menuStyle(.borderlessButton).menuIndicator(.hidden).fixedSize()
                .accessibilityLabel("how many messages a day this key may be given")
                // an ai app is closed, not deleted: it stays listed, reading nothing, until it is given something to read again
                let word = key.mcp ? "close" : "revoke"
                Button(k.revoking == key.name ? "press again to \(word)" : word) { k.revoke(key.name) }
                    .buttonStyle(QuietButton(size: Face.small))
                    .help(key.mcp ? "the app reads nothing from then on. it stays listed here: choose what it reads above to open it again." : "the key stops working at once. the program that holds it will be refused.")
                    .accessibilityLabel(k.revoking == key.name ? "press again to \(word) \(key.shown)" : "\(word) \(key.shown). a second press is asked for")
                    .probe("key.revoke", .button, scrolls: true)
            }
        }
        .probe("key.detail", .block, scrolls: true)
    }
}

/// Making a key: a name, then a slice. Nothing is chosen for them, and everything is the last choice.
struct MakeKeyCard: View {
    @Environment(AppModel.self) private var model
    @FocusState private var naming: Bool

    var body: some View {
        @Bindable var k = model.keys
        SetCard(title: "make a key") {
            if !k.making {
                SetRow(title: "a key for a program", about: "name the program, then choose what it may read. the key lasts 30 days and can be renewed, unless you say it never expires.", last: true) {
                    SetButton(word: "make a key") { k.making = true }
                }
            } else {
                VStack(alignment: .leading, spacing: Space.m) {
                    TextField("", text: $k.draftName, prompt: Text("the program's name, for example cursor").foregroundStyle(Ink.faint))
                        .textFieldStyle(.plain).font(.system(size: Face.body)).foregroundStyle(Ink.ink).tint(Ink.ember)
                        .focused($naming)
                        .onAppear { if !Probe.on { naming = true }; model.sideTyping = true }
                        .onDisappear { model.sideTyping = false }
                        .accessibilityLabel("the program's name")
                        .padding(.horizontal, 10).frame(height: 32)
                        .background(Ink.paper, in: RoundedRectangle(cornerRadius: Radius.row, style: .continuous))
                        .overlay(RoundedRectangle(cornerRadius: Radius.row, style: .continuous).strokeBorder(Ink.line, lineWidth: 1))
                    SetText.label("what may it read? choose one.", size: 10.5, weight: .regular, color: Ink.faint)
                    VStack(alignment: .leading, spacing: 0) {
                        ForEach(k.presets, id: \.name) { p in choice(p.name, p.name, p.reads) }
                        // the last choice, and the widest: said as what it is
                        choice("own", "limits of your own", "only the sources, people and days you name.")
                        if k.pick == "own" {
                            VStack(alignment: .leading, spacing: 0) {
                                own("sources", "for example slack, email", $k.draftSources)
                                own("people", "names, with commas between", $k.draftPeople)
                                own("from", "a day, as 2024-01-01", $k.draftAfter)
                                own("until", "a day, as 2025-12-31", $k.draftBefore)
                            }
                            .padding(.leading, 20).padding(.bottom, Space.s)
                        }
                        choice("all", "everything", k.warning)
                    }
                    HStack(alignment: .firstTextBaseline, spacing: Space.m) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("never expires").font(.system(size: Face.label, weight: .medium)).foregroundStyle(Ink.ink)
                            Text(k.draftNever ? "the key works until you revoke it." : "off: the key lasts 30 days and can be renewed.").font(.system(size: Face.small)).foregroundStyle(Ink.soft)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        Spacer(minLength: Space.s)
                        SetSwitch(label: "the new key never expires", on: k.draftNever) { k.draftNever = $0 }
                    }
                    .probe("key.forever", .block, scrolls: true)
                    if !k.fault.isEmpty { SetText.about(k.fault, Ink.ink) }
                    HStack(spacing: Space.l) {
                        let ready = !k.draftName.trimmingCharacters(in: .whitespaces).isEmpty && !k.pick.isEmpty
                        Button(k.pick == "all" ? "make a key that reads everything" : "make the key") { k.make() }.buttonStyle(PingButton())
                            .disabled(!ready).opacity(ready ? 1 : 0.35)
                            .probe("key.make", .button, scrolls: true)
                        Button("not now") { k.making = false; k.pick = ""; k.draftName = ""; k.fault = "" }.buttonStyle(QuietButton(size: Face.small))
                        Spacer(minLength: 0)
                    }
                }
                .padding(Space.l)
                .probe("key.making", .block, scrolls: true)
            }
        }
    }

    private func own(_ name: String, _ prompt: String, _ text: Binding<String>) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: Space.m) {
            Text(name).font(.system(size: Face.small, weight: .medium)).foregroundStyle(Ink.soft).frame(width: 56, alignment: .leading)
            TextField("", text: text, prompt: Text(prompt).foregroundStyle(Ink.faint))
                .textFieldStyle(.plain).font(.system(size: Face.small)).foregroundStyle(Ink.ink).tint(Ink.ember)
                .accessibilityLabel("the new key's limits: \(name)")
        }
        .padding(.vertical, 7)
        .overlay(alignment: .bottom) { Rectangle().fill(Ink.line).frame(height: 1) }
        .probe("key.make.own", .block, group: "key.make.owns", scrolls: true)
    }

    private func choice(_ id: String, _ name: String, _ reads: String) -> some View {
        let k = model.keys, on = k.pick == id
        return Button { k.pick = on ? "" : id } label: {
            HStack(alignment: .firstTextBaseline, spacing: Space.s) {
                Circle().strokeBorder(on ? Ink.ink : Ink.faint, lineWidth: 1.5).background(Circle().fill(on ? Ink.ink : .clear).padding(3)).frame(width: 12, height: 12).offset(y: 1)
                VStack(alignment: .leading, spacing: 2) {
                    Text(name).font(.system(size: Face.label, weight: .medium)).foregroundStyle(Ink.ink)
                    Text(reads).font(.system(size: Face.small)).foregroundStyle(Ink.soft).lineSpacing(2).multilineTextAlignment(.leading).fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 0)
            }
            .padding(.vertical, 7)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(name): \(reads)").accessibilityAddTraits(on ? [.isSelected] : [])
        .overlay(alignment: .top) { Rectangle().fill(Ink.line).frame(height: 1) }
        .probe("key.choice", .block, group: "key.choices", scrolls: true)
    }
}

/// A key just made: shown once, with the way to copy it and the sentence that it will not be shown again.
struct MadeKeyCard: View {
    @Environment(AppModel.self) private var model
    let key: NewKey

    var body: some View {
        let k = model.keys
        SetCard(title: "the key for \(key.name)", note: "copy it now and give it to the program. it will not be shown again: context keeps no copy it can show you.") {
            VStack(alignment: .leading, spacing: Space.m) {
                SetText.mono(key.key)
                if !key.reads.isEmpty, key.warning.isEmpty { SetText.about("it reads: " + key.reads) }
                // the engine's own warning, when the key reads everything
                if !key.warning.isEmpty { SetText.about(key.warning, Ink.ink).probe("key.warning", .block, scrolls: true) }
                if !key.url.isEmpty { SetText.label("the program calls " + key.url, size: 10.5, weight: .regular, color: Ink.faint) }
                HStack(spacing: Space.l) {
                    Button(k.copied ? "copied" : "copy the key") { Clip.copy(key.key); k.copied = true }.buttonStyle(PingButton())
                        .probe("key.copy", .button, scrolls: true)
                    Button("i have it") { k.made = nil }.buttonStyle(QuietButton(size: Face.small))
                        .help("puts the key away. it cannot be shown again; a lost key is revoked and a new one made.")
                    Spacer(minLength: 0)
                }
            }
            .padding(Space.l)
            .probe("key.made", .block, scrolls: true)
        }
    }
}

/// What no key may read, whatever it was given: people, sources, stretches of days. And the switch that holds a key
/// which reads far more than it usually does.
struct NeverCard: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        @Bindable var k = model.keys
        SetCard(title: "never share", note: "what is never handed out, whatever a key was made to read. the api, ais connected over mcp and this app's own answers all leave it out.") {
            field("people", "names, with commas between", $k.neverPeople)
            field("sources", "for example imessage, apple_notes", $k.neverSources)
            field("days", "for example 2019-01-01 to 2019-12-31, until 2015-06-30", $k.neverRanges)
            if !k.neverFault.isEmpty {
                SetText.about(k.neverFault, Ink.ink).padding(.horizontal, Space.l).padding(.vertical, Space.s)
                    .accessibilityLabel(k.neverFault)
                    .probe("key.never.fault", .block, scrolls: true)
            }
            SetRow(title: "hold a key that reads far more than usual", about: "its calls are refused for the rest of the day, until you clear it here.", last: true) {
                SetSwitch(label: "hold a key that reads far more than usual", on: k.holdUnusual) { k.hold($0) }
            }
        }
        .probe("key.never", .block, scrolls: true)
    }

    private func field(_ name: String, _ prompt: String, _ text: Binding<String>) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: Space.m) {
            Text(name).font(.system(size: Face.label, weight: .medium)).foregroundStyle(Ink.ink).frame(width: 64, alignment: .leading)
            TextField("", text: text, prompt: Text(prompt).foregroundStyle(Ink.faint))
                .textFieldStyle(.plain).font(.system(size: Face.label)).foregroundStyle(Ink.ink).tint(Ink.ember)
                .onSubmit { model.keys.saveNever() }
                .accessibilityLabel("never share: \(name)")
                .help("return saves it")
        }
        .padding(.horizontal, Space.l).padding(.vertical, 12)
        .overlay(alignment: .bottom) { Rectangle().fill(Ink.line).frame(height: 1).padding(.leading, Space.l) }
        .probe("key.never.field", .block, group: "key.never.fields", scrolls: true)
    }
}

/// On the sources page, only when there is something to say: a key that is held, or one about to expire.
struct KeyNotice: View {
    @Environment(AppModel.self) private var model
    var body: some View {
        if let line = model.keys.notice {
            Button { model.openSettings(.keys) } label: {
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Circle().fill(Ink.ember).frame(width: 5, height: 5).offset(y: -2)
                    Text(line + "  ·  settings").multilineTextAlignment(.leading).fixedSize(horizontal: false, vertical: true)
                        .font(.system(size: Face.small, weight: .medium)).foregroundStyle(Ink.soft)
                        .probe("key.notice", .block, scrolls: true)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(Pressable())
            .accessibilityLabel(line + " open settings")
            .padding(.top, Space.m)
        }
    }
}

// MARK: in the gate

extension LayoutTest {
    static func keyScreens(_ m: AppModel, main: @escaping (Tab) -> Void) -> [(String, () -> Void)] {
        let now = Date().timeIntervalSince1970
        let presets = [("people", "messages with people, from whatsapp, imessage, telegram, slack, x and linkedin."), ("profile", "the short profile and the briefing. no messages."),
                       ("work", "slack, mail, drive, calendar, notion and linkedin."), ("writing", "what you wrote yourself, in notes, the journal, docs and posts.")]
        func rows() -> [ApiKey] {
            [["name": "cursor", "reads": "slack, mail, drive, calendar, notion and linkedin.", "kind": "rows", "preset": "work", "expires": now + 12 * 86400, "expired": false, "rows_per_day": 1000,
              "calls_today": 8, "rows_today": 240, "calls_7d": 50, "rows_7d": 1_600, "unusual": false, "held": false],
             ["name": "a-script-with-a-long-name-from-one-evening", "reads": "the whole archive, through every endpoint.", "kind": "all", "preset": "", "expires": now + 2 * 86400, "expired": false,
              "rows_per_day": 5000, "calls_today": 400, "rows_today": 40_000, "calls_7d": 35, "rows_7d": 1_000, "unusual": true, "held": true],
             ["name": "an-old-notebook", "reads": "the short profile and the briefing. no messages.", "kind": "profile", "preset": "profile", "expires": now - 86400, "expired": true, "rows_per_day": 200,
              "calls_today": 0, "rows_today": 0, "calls_7d": 0, "rows_7d": 0, "unusual": false, "held": false]].compactMap { ApiKey($0) }
        }
        func apps() -> [ApiKey] {
            [["name": "mcp:claude_code", "via": "mcp", "reads": "slack, mail, drive, calendar, notion and linkedin.", "kind": "rows", "preset": "work", "expires": 0, "expired": false,
              "rows_per_day": 1000, "calls_today": 6, "rows_today": 180, "calls_7d": 30, "rows_7d": 900, "unusual": false, "held": false],
             ["name": "mcp:cursor", "via": "mcp", "reads": "nothing: closed by the owner", "kind": "none", "preset": "", "expires": 0, "expired": false,
              "rows_per_day": 0, "calls_today": 0, "rows_today": 0, "calls_7d": 0, "rows_7d": 0, "unusual": false, "held": false],
             ["name": "mcp:unnamed", "via": "mcp", "reads": "the short profile and the briefing. no messages.", "kind": "profile", "preset": "profile", "expires": 0, "expired": false,
              "rows_per_day": 0, "calls_today": 2, "rows_today": 50, "calls_7d": 10, "rows_7d": 300, "unusual": false, "held": false]].compactMap { ApiKey($0) }
        }
        func pane(_ more: () -> Void = {}) {
            main(.settings); m.settingsPane = .keys; m.settings.loaded = true; m.settings.answered = true
            m.keys.known = true; m.keys.presets = presets; m.keys.url = "http://127.0.0.1:8765/v1"
            more()
        }
        return [
            ("keys-none", { pane() }),
            ("keys-three", { pane { m.keys.keys = rows() } }),
            // ai apps connected over mcp sit in a group of their own: one open, one closed, one with no name of its own
            ("keys-apps", { pane { m.keys.keys = apps() + Array(rows().prefix(1)) } }),
            ("keys-app-reopen", { pane { m.keys.keys = apps(); m.keys.reopening = "mcp:cursor" } }),
            ("keys-app-open", { pane { m.keys.keys = apps(); m.keys.open = "mcp:claude_code" } }),
            ("keys-open", { pane {
                m.keys.keys = rows(); m.keys.open = "cursor"; m.keys.ownSources = "slack, email"; m.keys.ownAfter = "2024-01-01"
                m.keys.log["cursor"] = (0..<14).compactMap { i in ApiDay(["day": String(format: "2026-11-%02d", 9 + i), "calls": i % 3 == 0 ? 0 : 4 + i, "rows": i % 3 == 0 ? 0 : 40 + i * i * 9,
                                                                             "sources": i % 3 == 0 ? [String]() : ["slack", "email"], "refusals": i == 11 ? 3 : 0]) }
            } }),
            ("keys-revoking", { pane { m.keys.keys = rows(); m.keys.open = "cursor"; m.keys.revoking = "cursor"; m.keys.running = false } }),
            // making one: the name typed and nothing chosen; then everything chosen; then the key, shown once, with the engine's warning
            ("keys-make", { pane { m.keys.keys = Array(rows().prefix(1)); m.keys.making = true; m.keys.draftName = "raycast" } }),
            ("keys-make-all", { pane { m.keys.making = true; m.keys.draftName = "raycast"; m.keys.pick = "all" } }),
            // limits of their own while making it, and a key that never expires
            ("keys-make-own", { pane { m.keys.making = true; m.keys.draftName = "raycast"; m.keys.pick = "own"; m.keys.draftSources = "slack, email"; m.keys.draftAfter = "2024-01-01"; m.keys.draftNever = true } }),
            // a stretch of days the owner mistyped: said under the field, and nothing saved
            ("keys-never-mistyped", { pane { m.keys.neverRanges = "2019-01-01 to 2019-12-31, last summer"; m.keys.saveNever() } }),
            ("keys-made", { pane {
                m.keys.keys = Array(rows().prefix(1))
                m.keys.made = NewKey(["name": "raycast", "key": "ctx_made-up-key-for-the-layout-gate-0000000000000000000000000000", "reads": "the whole archive, through every endpoint.",
                                      "expires": now + 30 * 86400, "url": "http://127.0.0.1:8765/v1", "warning": "this key reads the whole archive, through every endpoint."])
            } }),
            ("keys-never", { pane {
                m.keys.never = ApiNever(["people": ["ines marchetti"], "sources": ["imessage"], "ranges": [["2019-01-01", "2019-12-31"], ["", "2015-06-30"]]])
                m.keys.neverPeople = "ines marchetti"; m.keys.neverSources = "imessage"; m.keys.neverRanges = m.keys.never.rangesText; m.keys.holdUnusual = false
            } }),
            ("keys-fault", { pane { m.keys.keys = rows(); m.keys.fault = "there is already a key called cursor. revoke it first, or pick another name." } }),
            ("keys-unknown", { main(.settings); m.settingsPane = .keys; m.settings.loaded = true; m.settings.answered = true; m.keys.known = false }),
            // the sources page says nothing of keys unless one is held or about to expire
            ("sources-key-held", { main(.sources); m.keys.known = true; m.keys.keys = rows() }),
            ("sources-key-quiet", { main(.sources); m.keys.known = true; m.keys.keys = Array(rows().prefix(1)) }),
        ]
    }

    static func keyCheck(_ screen: String, _ at: String, _ found: [ProbeInfo]) -> [String] {
        var out: [String] = []
        func has(_ n: String) -> Bool { found.contains { $0.name == n } }
        func count(_ n: String) -> Int { found.filter { $0.name == n }.count }
        let m = AppModel.shared
        switch screen {
        case "keys-none": if !has("key.none") || !has("key.never") || has("key.row") { out.append("\(at): with no keys the pane does not say so, or has no never list") }
        case "keys-apps":
            if !has("key.apps") || count("key.row") != 4 || !has("key.reopen") { out.append("\(at): ai apps over mcp are not a group of their own beside the programs with a key, or a closed one cannot be opened again") }
            if m.keys.keys.contains(where: { $0.mcp && $0.kind == "all" }) { out.append("\(at): the fixture has an ai app that reads everything by default, which the engine no longer allows") }
            if m.keys.keys.filter(\.mcp).count != 3 || m.keys.keys.first?.shown != "claude code" { out.append("\(at): an ai app is not told from a key by the engine's via, or wears the engine's prefix") }
        case "keys-app-reopen": if count("key.reopen.slice") != 4 { out.append("\(at): opening a closed app again does not ask which slice") }
        case "keys-app-open": if !has("key.detail") || !has("key.revoke") || count("key.preset") != 4 { out.append("\(at): an opened ai app has no slices to change to or no way to close it") }
        case "keys-three":
            if has("key.apps") { out.append("\(at): the group of ai apps is drawn with none in it") }
            if !has("key.clear") { out.append("\(at): a held key has no way to clear it") }
            if count("key.row") != 3 { out.append("\(at): \(count("key.row")) keys are listed, not 3") }
            if m.keys.keys.filter({ $0.kind == "all" }).count != 1 || m.keys.keys.filter(\.held).count != 1 || m.keys.keys.filter(\.expired).count != 1 { out.append("\(at): the keys' kinds and states are not read as the engine gives them") }
        case "keys-open": if !has("key.detail") || !has("key.strip") || count("key.preset") != 4 || count("key.own") != 4 || !has("key.revoke") { out.append("\(at): an opened key has no strip of days, no slices to change to, or no revoke") }
        case "keys-revoking": if !has("key.revoke") || m.keys.revoking != "cursor" { out.append("\(at): revoke does not wait for a second press") }
        case "keys-make-own": if count("key.make.own") != 4 || !has("key.forever") || !has("key.make") { out.append("\(at): a key cannot be given limits of their own, or made to never expire, while it is made") }
        case "keys-never-mistyped": if !has("key.never.fault") || !m.keys.neverFault.contains("last summer") { out.append("\(at): a stretch of days that cannot be read is dropped without a word") }
        case "keys-make":
            if count("key.choice") != 6 || !has("key.forever") { out.append("\(at): \(count("key.choice")) choices, not the engine's four, limits of their own, and everything; or no way to say it never expires") }
            if !m.keys.pick.isEmpty { out.append("\(at): a slice is chosen for them before the owner chooses") }
            let ys = found.filter { $0.name == "key.choice" }.map(\.frame.minY)
            if let lastY = ys.max(), ys.filter({ $0 == lastY }).count != 1 { out.append("\(at): everything is not the last choice by itself") }
        case "keys-make-all": if !has("key.make") { out.append("\(at): there is no way to make the key") }
        case "keys-made": if !has("key.made") || !has("key.copy") || !has("key.warning") { out.append("\(at): a new key is not shown once with its copy and the engine's warning") }
        case "keys-never": if count("key.never.field") != 3 || KeysModel.ranges(m.keys.neverRanges) != [["2019-01-01", "2019-12-31"], ["", "2015-06-30"]] { out.append("\(at): the never list does not show people, sources and days, or its days are not read back as written") }
        case "keys-fault": if !has("key.fault") { out.append("\(at): the engine's sentence for a mistake is not shown") }
        case "keys-unknown": if has("key.row") || has("key.never") { out.append("\(at): keys are offered though the engine has none") }
        case "sources-key-held": if !has("key.notice") { out.append("\(at): a held key is not said on the sources page") }
        case "sources-key-quiet": if has("key.notice") { out.append("\(at): the sources page speaks of keys though none is held or about to expire") }
        default: break
        }
        if screen.hasPrefix("sources") || screen.hasPrefix("home-") || screen.hasPrefix("frame-"), screen != "sources-key-held", has("key.notice") { out.append("\(at): a line about keys is drawn with nothing to say") }
        return out
    }
}
