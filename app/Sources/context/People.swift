import AppKit
import Observation
import SwiftUI

/// Someone the owner talks to, as the engine lists them.
/// {"cmd": "people"} -> [{"name", "aliases", "apps", "threads", "messages", "mine", "first", "last", "group"?, "unnamed"?}].
struct Person: Identifiable, Equatable {
    var name: String
    var aliases: [String] = []
    var apps: [String] = []
    var last = ""               // iso time of the last message either way
    var threads = 0
    var who = ""                // who they are to them, in a few words
    var id: String { name.lowercased() }

    init(name: String, aliases: [String] = [], apps: [String] = [], last: String = "", threads: Int = 0, who: String = "") {
        self.name = name; self.aliases = aliases; self.apps = apps; self.last = last; self.threads = threads; self.who = who
    }

    init?(_ d: [String: Any]) {
        // someone the engine could not put a name to is not something to find in a line of text
        guard let n = d["name"] as? String, !n.trimmingCharacters(in: .whitespaces).isEmpty, d["unnamed"] as? Bool != true else { return nil }
        name = n
        aliases = d["aliases"] as? [String] ?? []
        apps = d["apps"] as? [String] ?? []
        last = d["last"] as? String ?? ""
        threads = d["threads"] as? Int ?? (d["threads"] as? [Any])?.count ?? 0
        who = d["about"] as? String ?? d["who"] as? String ?? ""
    }
}

/// One person, opened in the panel on the right.
/// {"cmd": "person", "name": "..."} -> the list's fields plus "about", "threads": [{"id", "app", "title", "messages", "last",
/// "summary"}], "open": [...], "recent": [{"id", "ts", "who", "text"}]. Promises both ways are shown when the engine sends
/// "promised": {"by_me": [...], "to_me": [...]}.
struct PersonPage: Equatable {
    struct App: Equatable, Identifiable { var src: String; var rows = 0; var last = ""; var id: String { src } }
    struct Line: Equatable, Identifiable { var text: String; var ts = ""; var src = ""; var row = ""; var id: String { row + ts + text } }
    var name: String
    var who = ""
    var apps: [App] = []
    var last: Line?
    var open: [Line] = []
    var threads: [Line] = []    // the conversations with them
    var mine: [Line] = []       // what the owner said the owner would do for them
    var theirs: [Line] = []     // what they said they would do for them
    var loading = false
    var known = true            // false: neither the engine nor the pages have this person

    static func lines(_ v: Any?) -> [Line] {
        ((v as? [Any]) ?? []).compactMap { one in
            if let s = one as? String { return s.isEmpty ? nil : Line(text: s) }
            guard let d = one as? [String: Any] else { return nil }
            let text = (d["text"] as? String ?? d["title"] as? String ?? d["summary"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            return text.isEmpty ? nil : Line(text: text, ts: d["ts"] as? String ?? d["last"] as? String ?? "", src: d["src"] as? String ?? d["app"] as? String ?? "", row: d["id"] as? String ?? "")
        }
    }

    mutating func take(_ d: [String: Any]) {
        if let n = d["name"] as? String, !n.isEmpty { name = n }
        who = d["about"] as? String ?? d["who"] as? String ?? who
        // the conversations with them, most recent first; each app's figures are the sum of its conversations
        let convs = (d["threads"] as? [[String: Any]]) ?? []
        threads = convs.compactMap { t in
            let title = (t["title"] as? String ?? "").trimmingCharacters(in: .whitespaces)
            let sum = (t["summary"] as? String ?? "").trimmingCharacters(in: .whitespaces)
            guard !title.isEmpty || !sum.isEmpty else { return nil }
            return Line(text: sum.isEmpty ? title : sum, ts: t["last"] as? String ?? "", src: t["app"] as? String ?? "", row: t["id"] as? String ?? "")
        }
        if let list = d["apps"] as? [String], !convs.isEmpty {
            apps = list.map { src in
                let mine = convs.filter { $0["app"] as? String == src }
                return App(src: src, rows: mine.reduce(0) { $0 + ($1["messages"] as? Int ?? 0) }, last: mine.compactMap { $0["last"] as? String }.max() ?? "")
            }
        } else if let list = d["apps"] as? [[String: Any]] {
            apps = list.compactMap { a in (a["src"] as? String).map { App(src: $0, rows: a["rows"] as? Int ?? 0, last: a["last"] as? String ?? "") } }
        } else if let list = d["apps"] as? [String] {
            apps = list.map { App(src: $0) }
        }
        if let l = d["last"] as? [String: Any] {
            last = Line(text: l["text"] as? String ?? "", ts: l["ts"] as? String ?? "", src: l["src"] as? String ?? "", row: l["id"] as? String ?? "")
        } else if let r = ((d["recent"] as? [[String: Any]]) ?? []).max(by: { ($0["ts"] as? String ?? "") < ($1["ts"] as? String ?? "") }) {
            last = Line(text: r["text"] as? String ?? "", ts: r["ts"] as? String ?? "", src: r["app"] as? String ?? apps.max { $0.last < $1.last }?.src ?? "", row: r["id"] as? String ?? "")
        } else if let ts = d["last"] as? String, !ts.isEmpty {
            last = Line(text: "", ts: ts, src: apps.max { $0.last < $1.last }?.src ?? "")
        }
        open = PersonPage.lines(d["open"])
        let p = d["promised"] as? [String: Any] ?? [:]
        mine = PersonPage.lines(p["by_me"])
        theirs = PersonPage.lines(p["to_me"])
    }
}

/// The people in their history as things to open: a list to find names by, and the one that is open.
@Observable final class PeopleModel {
    var list: [Person] = [] { didSet { index() } }
    var open: PersonPage?
    var fromEngine = false
    @ObservationIgnored weak var engine: Engine?
    @ObservationIgnored private var needles: [(words: [String], name: String)] = []
    @ObservationIgnored private var byLabel: [String: String] = [:]
    @ObservationIgnored private var asked = Date.distantPast

    var isEmpty: Bool { list.isEmpty }

    /// Names and other names as runs of lowercase words, longest first, so "sam okafor" is found before "sam".
    private func index() {
        var out: [(words: [String], name: String)] = []
        var labels: [String: String] = [:]
        for p in list {
            for label in [p.name] + p.aliases {
                let words = label.lowercased().split(whereSeparator: { !$0.isLetter && !$0.isNumber && $0 != "'" && $0 != "-" }).map(String.init)
                guard !words.isEmpty, words.joined().count >= 3 else { continue }
                out.append((words, p.name))
                labels[label.lowercased()] = p.name
            }
            // a first name stands for the person when nobody else in the list has it
            if let first = p.name.split(separator: " ").first.map({ $0.lowercased() }), first.count >= 3, p.name.contains(" "),
               list.filter({ $0.name.lowercased().hasPrefix(first + " ") || $0.name.lowercased() == first }).count == 1 {
                out.append(([first], p.name))
                labels[first] = labels[first] ?? p.name
            }
        }
        needles = out.sorted { $0.words.count > $1.words.count }
        byLabel = labels
    }

    private static func bare(_ w: String) -> String {
        var s = w.lowercased()
        for tail in ["'s", "\u{2019}s"] where s.hasSuffix(tail) { s = String(s.dropLast(2)) }
        return s.trimmingCharacters(in: CharacterSet.letters.union(.decimalDigits).inverted)
    }

    /// Which words of a line are part of a known name: word index -> that person. A single-word name only counts
    /// where the text gives it a capital, so "will" and "may" stay words.
    func match(_ words: [String]) -> [Int: String] {
        var out: [Int: String] = [:]
        for r in runs(words) { for k in r.at..<(r.at + r.count) { out[k] = r.name } }
        return out
    }

    /// Each mention of a known name in a line, as one run of words: where it starts, how many words, who. "Sam Okafor"
    /// is one run of two, and is set, pressed and read as one thing.
    func runs(_ words: [String]) -> [(at: Int, count: Int, name: String)] {
        guard !needles.isEmpty, !words.isEmpty else { return [] }
        let low = words.map(PeopleModel.bare)
        var out: [(at: Int, count: Int, name: String)] = []
        var i = 0
        while i < words.count {
            var took = 0
            for n in needles where i + n.words.count <= words.count {
                var ok = true
                for (k, w) in n.words.enumerated() where low[i + k] != w { ok = false; break }
                if ok, n.words.count == 1, !(words[i].first { $0.isLetter }?.isUppercase ?? false) { ok = false }
                if ok { out.append((i, n.words.count, n.name)); took = n.words.count; break }
            }
            i += max(1, took)
        }
        return out
    }

    /// The person a label names outright: a sender, the title of a one-to-one conversation.
    func resolve(_ label: String) -> String? {
        let l = label.lowercased().trimmingCharacters(in: .whitespacesAndNewlines)
        if let n = byLabel[l] { return n }
        // "sam (landlord)" names sam
        if let cut = l.firstIndex(of: "("), let n = byLabel[l[..<cut].trimmingCharacters(in: .whitespaces)] { return n }
        return nil
    }

    /// The list from the engine. Until it has the command, the names are the headings of the people page.
    func load(pages: [ProfilePage]) {
        if !Engine.debug, let engine, Date().timeIntervalSince(asked) > 300 {
            asked = Date()
            engine.client.call(["cmd": "people"], timeout: 30) { [weak self] reply in
                guard let self else { return }
                let rows = (reply as? [[String: Any]]) ?? ((reply as? [String: Any])?["people"] as? [[String: Any]]) ?? []
                let found = rows.compactMap { Person($0) }
                if !found.isEmpty { self.list = found; self.fromEngine = true }
            }
        }
        if !fromEngine { list = PeopleModel.fromPage(pages.first { $0.id == "people" }) }
    }

    /// Each heading of the people page under the first is a person; the lines under it say who they are.
    static func fromPage(_ page: ProfilePage?) -> [Person] {
        guard let page else { return [] }
        var out: [Person] = []
        for b in page.blocks {
            if b.kind == .heading, b.level >= 2 {
                let name = b.plain.trimmingCharacters(in: .whitespaces)
                if !name.isEmpty, name.count <= 48 { out.append(Person(name: name)) }
            } else if b.kind == .paragraph || b.kind == .item, !out.isEmpty, out[out.count - 1].who.isEmpty {
                out[out.count - 1].who = b.plain.trimmingCharacters(in: .whitespaces)
            }
        }
        return out
    }

    /// Opens a person in the panel on the right: what the list has at once, then the engine's page when it comes.
    func show(_ name: String, seen: [Hit] = []) {
        let listed = list.first { $0.name.lowercased() == name.lowercased() } ?? resolve(name).flatMap { n in list.first { $0.name == n } }
        var page = PersonPage(name: listed?.name ?? name)
        page.who = listed?.who ?? ""
        page.apps = (listed?.apps ?? []).map { PersonPage.App(src: $0) }
        if let l = listed, !l.last.isEmpty { page.last = PersonPage.Line(text: "", ts: l.last, src: l.apps.first ?? "") }
        // what this answer's own rows show of them, until the engine says more
        let mine = seen.filter { resolve($0.sender) == page.name || resolve($0.thread) == page.name || $0.sender.lowercased() == name.lowercased() }
        for h in mine where !page.apps.contains(where: { $0.src == h.src }) { page.apps.append(PersonPage.App(src: h.src)) }
        if page.last == nil, let h = mine.max(by: { $0.ts < $1.ts }) { page.last = PersonPage.Line(text: h.snippet, ts: h.ts, src: h.src, row: h.id) }
        page.known = listed != nil || !mine.isEmpty
        page.loading = !Engine.debug && engine != nil
        open = page
        guard page.loading, let engine else { return }
        let asked = page.name
        engine.client.call(["cmd": "person", "name": asked], timeout: 30) { [weak self] reply in
            guard let self, var p = self.open, p.name == asked else { return }
            p.loading = false
            if let d = reply as? [String: Any], d["error"] == nil { p.take(d); p.known = true }
            self.open = p
        }
    }

    func close() { open = nil }
}

extension EngineClient {
    /// One request to the warm engine, answered with whatever it put under "result": an object, a list, or nil when the
    /// engine does not know the command or is not there.
    func call(_ request: [String: Any], timeout: TimeInterval = 20, done: @escaping (Any?) -> Void) {
        guard let w = warmEngine else { done(nil); return }
        var result: Any?
        var answered = false
        let id = w.send(request, event: { d in if let r = d["result"] { result = r } }, end: { if !answered { answered = true; done(result) } })
        if let id { DispatchQueue.main.asyncAfter(deadline: .now() + timeout) { [weak w] in w?.cancel(id); w?.finish(id) } }
    }
}

extension AppModel {
    /// A name was clicked: that person, in the panel on the right.
    func showPerson(_ name: String) {
        guard saved.onboarded, tab == .home || tab == .profile else { return }
        let turn = ask.sourcesFor.flatMap { id in ask.turns.first { $0.id == id } } ?? ask.turns.last
        people.show(name, seen: turn?.answer?.cites ?? [])
    }

    /// "ask about sam": home, with that person as a limit on the next question.
    func askAbout(_ name: String) {
        var s = ask.scope
        if !s.people.contains(name) { s.people.append(name) }
        ask.scope = s
        people.close()
        if tab != .home { tab = .home }
        focusAsk += 1
    }
}

// MARK: the person, in the panel

struct PersonPane: View {
    @Environment(AppModel.self) private var model
    let page: PersonPage

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                Text(page.name).font(.system(size: 22, weight: .semibold, design: .serif)).foregroundStyle(Ink.ink)
                    .fixedSize(horizontal: false, vertical: true)
                    .probe("refs.person.name", .text, scrolls: true)
                    .accessibilityAddTraits(.isHeader)
                if !page.who.isEmpty {
                    Text(page.who).font(.system(size: 14, design: .serif)).foregroundStyle(Ink.ink.opacity(0.86)).lineSpacing(3)
                        .fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
                        .probe("refs.person.who", .text, scrolls: true)
                        .padding(.top, 6)
                } else if !page.known, !page.loading {
                    Text("context has no page for this person yet. the read-through writes one for everyone you talk to.")
                        .font(.system(size: 12)).foregroundStyle(Ink.soft).lineSpacing(2)
                        .fixedSize(horizontal: false, vertical: true)
                        .probe("refs.person.who", .text, scrolls: true)
                        .padding(.top, 6)
                }
                Button("ask about \(page.name.split(separator: " ").first.map { $0.lowercased() } ?? page.name.lowercased())") { model.askAbout(page.name) }
                    .buttonStyle(SwitchButton()).ring(14, inset: 1)
                    .help("the next question is limited to what you and \(page.name) wrote")
                    .probe("refs.person.ask", .button, scrolls: true)
                // how much this person counts, in three quiet words that write the sentence for them
                TeachWords { RulesModel.sentence($0, person: page.name.lowercased()) }.padding(.top, Space.s)
                    .padding(.top, 14)
                if let id = model.wiki.personPages[page.name.lowercased()], !(model.tab == .profile && model.wiki.openID == id && !model.wiki.briefing) {
                    Button("open full page") { model.people.close(); model.tab = .profile; model.wiki.show(id) }
                        .buttonStyle(QuietButton(size: 12))
                        .help("everything context has written about \(page.name)")
                        .probe("refs.person.page", .button, scrolls: true)
                        .padding(.top, 10)
                }

                if !page.apps.isEmpty {
                    head("where you talk")
                    ForEach(page.apps) { a in
                        HStack(spacing: 9) {
                            SourceIcon(id: a.src, size: 18)
                            Text(Catalog.info(a.src).name).font(.system(size: 13, weight: .medium)).foregroundStyle(Ink.ink).lineLimit(1)
                            Spacer(minLength: 6)
                            Text(([a.rows > 0 ? Words.count(a.rows) : ""] + [a.last.isEmpty ? "" : Words.day(a.last)]).filter { !$0.isEmpty }.joined(separator: "  ·  "))
                                .font(.system(size: 11, weight: .medium)).monospacedDigit().foregroundStyle(Ink.soft).lineLimit(1).fixedSize()
                        }
                        .frame(height: 30)
                        .accessibilityElement(children: .combine)
                        .probe("refs.person.app", .block, group: "refs.person.apps", scrolls: true)
                    }
                }
                if let l = page.last, !l.ts.isEmpty {
                    head("last contact")
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        if !l.src.isEmpty { SourceIcon(id: l.src, size: 14).alignmentGuide(.firstTextBaseline) { $0[.bottom] - 2 } }
                        Text(Words.ago(l.ts) + (l.src.isEmpty ? "" : "  ·  " + Catalog.info(l.src).name))
                            .font(.system(size: 13, weight: .medium)).monospacedDigit().foregroundStyle(Ink.ink).lineLimit(1)
                    }
                    .probe("refs.person.last", .block, scrolls: true)
                    if !l.text.isEmpty {
                        Text(l.text).font(.system(size: 12)).foregroundStyle(Ink.soft).lineSpacing(2.5).lineLimit(3)
                            .fixedSize(horizontal: false, vertical: true)
                            .padding(.top, 4)
                    }
                }
                lines("open between you", page.open)
                lines("conversations", Array(page.threads.prefix(6)))
                lines("you said you would", page.mine)
                lines("they said they would", page.theirs)
                if page.loading {
                    HStack(spacing: 8) {
                        Spinner(size: 10)
                        Text("looking through your history").font(.system(size: 12, weight: .medium)).foregroundStyle(Ink.soft)
                    }
                    .padding(.top, 20)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 16).padding(.top, 16).padding(.bottom, 24)
        }
    }

    private func head(_ text: String) -> some View {
        Text(text).font(.system(size: 11, weight: .semibold)).foregroundStyle(Ink.soft).lineLimit(1).fixedSize()
            .padding(.top, 22).padding(.bottom, 6)
            .accessibilityAddTraits(.isHeader)
            .probe("refs.head", .line, scrolls: true)
    }

    @ViewBuilder private func lines(_ title: String, _ list: [PersonPage.Line]) -> some View {
        if !list.isEmpty {
            head(title)
            ForEach(list) { l in
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text(l.text).font(.system(size: 13)).foregroundStyle(Ink.ink.opacity(0.9)).lineSpacing(2.5)
                        .fixedSize(horizontal: false, vertical: true)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    if !l.ts.isEmpty {
                        Text(Words.day(l.ts)).font(.system(size: 11, weight: .medium)).monospacedDigit().foregroundStyle(Ink.soft).lineLimit(1).fixedSize()
                    }
                }
                .padding(.vertical, 7)
                .overlay(alignment: .bottom) { Rectangle().fill(Ink.line).frame(height: 1) }
                .accessibilityElement(children: .combine)
                .probe("refs.person.line", .block, group: "refs.person.lines", scrolls: true)
            }
        }
    }
}

/// A person's name where it stands in a line: a word that can be pressed. It opens their page.
struct PersonName: View {
    let name: String            // who it opens
    let text: String            // the word as written
    @State private var hover = false

    var body: some View {
        Text(text).underline(true, pattern: .dot, color: hover ? Ink.ink : Ink.faint)
            .contentShape(Rectangle())
            .onTapGesture { AppModel.shared.showPerson(name) }
            .onHover { hover = $0 }
            .focusable()
            .onKeyPress(.return) { AppModel.shared.showPerson(name); return .handled }
            .onKeyPress(.space) { AppModel.shared.showPerson(name); return .handled }
            .ring(3, inset: 1)
            .help("open \(name)")
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(text)
            .accessibilityHint("opens \(name)")
            .accessibilityAddTraits(.isButton)
    }
}

// MARK: checks

extension LayoutTest {
    static let peopleList: [Person] = [
        Person(name: "Sam Okafor", aliases: ["sam (landlord)"], apps: ["whatsapp", "email"], last: "2026-11-11T10:00:00Z", threads: 3, who: "Your landlord since 2019."),
        Person(name: "Ines Marchetti", aliases: ["ines"], apps: ["imessage"], last: "2026-11-09T10:00:00Z", threads: 1, who: "You share the flat."),
        Person(name: "Maya Lindqvist", apps: ["slack"], last: "2026-10-30T10:00:00Z", threads: 2, who: "Design partner at the studio since 2022."),
    ]

    /// Three people named in full, one of them at the end of a line where the name has to go over whole, one with a possessive.
    static let fullNames: [String: Any] = [
        "answer": "Three people. Sam Okafor asked twice about the renewal [1], and the second time he also asked about the deposit, which nobody has answered yet as far as Ines Marchetti "
            + "can tell. Maya Lindqvist's pricing page is the third thing: you said you would send it this week.",
        "cites": [source(1, "whatsapp", "sam (landlord)", "them", "the lease renewal is due on the first.")],
        "searched": ["waiting"], "found": 12, "secs": 8.0, "strength": "strong", "error": ""]

    /// How many times a known person is named in an answer: each mention is one thing on the page.
    static func mentions(_ a: Answer, _ people: PeopleModel) -> Int {
        a.md.reduce(0) { n, b in n + people.runs(MD.words(b.bits).map { $0.span.code || $0.span.link != nil ? "" : $0.text }).count }
    }

    static var personPage: PersonPage {
        var p = PersonPage(name: "Sam Okafor")
        p.take(["who": "Your landlord since 2019. Plain and fair with you; he asks twice before he chases.",
                "apps": [["src": "whatsapp", "rows": 450, "last": "2026-11-11T10:00:00Z"], ["src": "email", "rows": 40, "last": "2026-11-11T09:00:00Z"]],
                "recent": [["id": "R2", "ts": "2026-11-11T10:00:00Z", "who": "them", "app": "whatsapp", "text": "did you see my message about the renewal? i also need to know about the deposit."]],
                "open": ["the lease renewal: he asked twice whether you are staying, and whether the deposit carries over to the new term", "the boiler repair"],
                "threads": [["id": "t1", "app": "whatsapp", "title": "sam (landlord)", "messages": 450, "last": "2026-11-11T10:00:00Z", "summary": "rent, repairs and the renewal, since 2019"]],
                "promised": ["by_me": [["text": "check with the others and come back to him", "ts": "2026-10-20T10:00:00Z"]],
                             "to_me": [["text": "send the new terms in writing", "ts": "2026-11-11T10:00:00Z"]]]])
        return p
    }

    static func peopleScreens(_ m: AppModel, main: @escaping (Tab) -> Void) -> [(String, () -> Void)] {
        func chat(_ after: () -> Void = {}) {
            main(.home)
            m.people.list = peopleList
            m.ask.turns = [Turn(id: 0, q: "where do i stand on the lease?", answer: Answer(report, tag: "t0"))]
            m.ask.asking = false
            m.ask.sourcesFor = 0
            after()
        }
        return [
            ("person-names", { chat() }),                                   // names in the answer and in the source rows
            ("person-full-names", {                                         // a name of two words is one thing to press, not two
                chat()
                m.ask.sourcesFor = nil
                m.ask.turns = [Turn(id: 0, q: "who is waiting on me?", answer: Answer(fullNames, tag: "t0"))]
            }),
            ("person-open", { chat { m.people.open = personPage } }),
            ("person-loading", { chat { var p = PersonPage(name: "Ines Marchetti"); p.who = "You share the flat."; p.apps = [PersonPage.App(src: "imessage")]; p.loading = true; m.people.open = p } }),
            ("person-unknown", { chat { var p = PersonPage(name: longName); p.known = false; m.people.open = p } }),
            ("person-from-profile", {                                       // opened from the people page, with no chat under it
                main(.profile)
                m.profile.pages = ProfilePage.order.compactMap { id in profilePages[id].map { ProfilePage(id: id, text: $0, rebuilt: nil) } }
                m.profile.page = "people"
                m.people.list = PeopleModel.fromPage(m.profile.pages.first { $0.id == "people" })
                m.people.open = personPage
            }),
        ]
    }
}
