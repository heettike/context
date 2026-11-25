import AppKit
import SwiftUI

// Teach (DESIGN.md): the place where the owner tells context how to treat their data, in sentences. The engine reads a
// sentence and says back what it would change; nothing changes until the owner says "do this".
//   {"cmd":"rules-list"}                       -> [{"id","said","kind","target","strength"?,"made","on","affects":{"rows","threads"}}]
//   {"cmd":"rule-propose","text":"…"}          -> {"rule": {...} | null, "says", "ask", "affects":{"rows","threads","from","to"}, "destructive"}
//   {"cmd":"rule-save","rule":{...}}           -> rule
//   {"cmd":"rule-set","rule_id":"…","on":bool} -> rule
//   {"cmd":"rule-remove","rule_id":"…"}        -> {"removed": true}
// An engine that does not know `rules-list` hides the whole of it: no entry in the sidebar, no quiet actions.

struct Rule: Identifiable, Equatable {
    var id: String
    var said: String
    var kind: String            // weigh, leave_out, forget, treat, fact
    var target = ""
    var strength: Double?
    var made = ""
    var on = true
    var rows = 0
    var threads = 0
    var raw = Data()            // as the engine sent it, to hand back unchanged

    init?(_ any: Any?) {
        guard let d = any as? [String: Any], let said = d["said"] as? String else { return nil }
        id = d["id"] as? String ?? ""
        self.said = said.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        kind = d["kind"] as? String ?? ""
        target = (d["target"] as? String ?? "").lowercased()
        strength = (d["strength"] as? Double) ?? (d["strength"] as? Int).map(Double.init)
        made = d["made"] as? String ?? ""
        on = d["on"] as? Bool ?? true
        let a = d["affects"] as? [String: Any] ?? [:]
        rows = a["rows"] as? Int ?? 0
        threads = a["threads"] as? Int ?? 0
        raw = (try? JSONSerialization.data(withJSONObject: d)) ?? Data()
    }

    var dict: [String: Any] { ((try? JSONSerialization.jsonObject(with: raw)) as? [String: Any]) ?? ["id": id, "said": said, "kind": kind] }

    /// What it does, in a few plain words: "counts about twice as much".
    var does: String {
        switch kind {
        case "weigh":
            guard let s = strength else { return "counts differently" }
            if s >= 1.75, s <= 2.25 { return "counts about twice as much" }
            if s > 2.25 { return "counts about \(Int(s.rounded())) times as much" }
            if s > 1 { return "counts a little more" }
            if s >= 0.4, s <= 0.6 { return "counts about half as much" }
            if s < 0.4 { return "counts much less" }
            return s < 1 ? "counts a little less" : "counts the same"
        case "leave_out": return "left out of every answer"
        case "forget": return "forgotten. kept 30 days, then gone"
        case "treat": return "shapes how answers are written"
        case "fact": return "taken as true about you"
        case "show": return "changes how things are shown"
        default: return kind.replacingOccurrences(of: "_", with: " ")
        }
    }

    /// "counts about twice as much · 1 conversation, 3,000 messages"
    var line: String { [does, Rule.touches(rows: rows, threads: threads)].filter { !$0.isEmpty }.joined(separator: " · ") }

    static func touches(rows: Int, threads: Int) -> String {
        var parts: [String] = []
        if threads > 0 { parts.append("\(Words.count(threads)) conversation\(threads == 1 ? "" : "s")") }
        if rows > 0 { parts.append("\(Words.count(rows)) message\(rows == 1 ? "" : "s")") }
        return parts.joined(separator: ", ")
    }
}

/// The engine's reading of one sentence.
struct Proposal: Equatable {
    var rule: Rule?
    var says = ""
    var ask = ""
    var rows = 0
    var threads = 0
    var from = ""
    var to = ""
    var destructive = false

    init?(_ any: Any?) {
        guard let d = any as? [String: Any], d["says"] != nil || d["ask"] != nil || d["rule"] != nil else { return nil }
        rule = Rule(d["rule"])
        says = (d["says"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        ask = (d["ask"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        let a = d["affects"] as? [String: Any] ?? [:]
        rows = a["rows"] as? Int ?? 0
        threads = a["threads"] as? Int ?? 0
        from = a["from"] as? String ?? ""
        to = a["to"] as? String ?? ""
        destructive = d["destructive"] as? Bool ?? (rule?.kind == "forget")
    }

    /// "1 conversation, 3,000 messages · mar 2019 to nov 2026"
    var touches: String {
        let span = from.isEmpty ? "" : (to.isEmpty || Words.monthYear(to) == Words.monthYear(from) ? Words.monthYear(from) : "\(Words.monthYear(from)) to \(Words.monthYear(to))")
        let what = Rule.touches(rows: rows, threads: threads)
        return [what.isEmpty && rule != nil && !destructive ? "nothing in the archive yet" : what, span].filter { !$0.isEmpty }.joined(separator: " · ")
    }
}

/// One exchange on the page: what the owner said, and where the engine's reading of it stands.
struct Teaching: Identifiable, Equatable {
    enum State: Equatable { case reading, proposed, question, saved, dropped, failed(String) }
    let id: Int
    var said: String
    var state: State = .reading
    var proposal: Proposal?
    var armed = false           // a destructive rule, pressed once: the next press does it
}

@Observable final class RulesModel {
    var available: Bool?            // nil until the engine has answered; false when it does not know the commands
    var rules: [Rule] = []
    var talk: [Teaching] = []
    var lit: Set<String> = []       // rules to light: the ones that shaped the answer the owner came from
    var draft = ""
    var focus = 0
    var settled: String?            // the rule that has just been saved, while it settles into the list
    var prefs = Prefs()             // how the owner asked for things to be shown; the engine's `prefs`
    @ObservationIgnored private var next = 0
    @ObservationIgnored weak var engine: Engine?

    var shown: Bool { available == true }

    func load(_ engine: Engine) {
        self.engine = engine
        guard !Probe.on else { return }
        engine.client.call(["cmd": "rules-list"], timeout: 20) { [weak self] reply in
            guard let self else { return }
            guard let rows = reply as? [[String: Any]] else { if self.available == nil { self.available = false }; return }
            self.available = true
            self.rules = rows.compactMap { Rule($0) }
        }
        loadPrefs()
    }

    /// Read at launch and after any rule changes: a rule of the kind "show" changes how things look.
    func loadPrefs() {
        guard !Probe.on, let engine else { return }
        engine.client.call(["cmd": "prefs"], timeout: 20) { [weak self] reply in if let p = Prefs(reply) { self?.prefs = p } }
    }

    /// Their sentence goes up the page and the engine reads it. An answer to a question it asked is read with the sentence it was about.
    func propose(_ text: String) {
        let said = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !said.isEmpty else { return }
        var whole = said
        if let q = talk.last, q.state == .question { whole = q.said + ". " + said }
        next += 1
        let id = next
        talk.append(Teaching(id: id, said: said.lowercased()))
        draft = ""
        guard !Probe.on, let engine else { return }
        engine.client.call(["cmd": "rule-propose", "text": whole], timeout: 60) { [weak self] reply in
            guard let self, let i = self.talk.firstIndex(where: { $0.id == id }) else { return }
            guard let p = Proposal(reply) else { self.talk[i].state = .failed("context could not read that. say it another way."); return }
            self.talk[i].proposal = p
            self.talk[i].state = !p.ask.isEmpty && p.rule == nil ? .question : (p.rule == nil ? .failed(p.says.isEmpty ? "context could not make a rule of that." : p.says) : .proposed)
            if self.talk[i].state == .question { self.focus += 1 }
        }
    }

    /// "do this". A rule that forgets takes two presses: the first arms it, the second does it.
    func accept(_ id: Int) {
        guard let i = talk.firstIndex(where: { $0.id == id }), let p = talk[i].proposal, let rule = p.rule else { return }
        if p.destructive, !talk[i].armed { talk[i].armed = true; return }
        talk[i].state = .saved
        func land(_ r: Rule) {
            rules.removeAll { $0.id == r.id }
            rules.append(r)
            settled = r.id
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) { [weak self] in if self?.settled == r.id { self?.settled = nil } }
        }
        guard !Probe.on, let engine else { land(rule); return }
        engine.client.call(["cmd": "rule-save", "rule": rule.dict], timeout: 60) { [weak self] reply in
            guard let self else { return }
            // rule-save answers with the rule, or {"error": why}
            if let saved = Rule(reply) { land(saved); self.loadPrefs() }
            else if let k = self.talk.firstIndex(where: { $0.id == id }) {
                let why = ((reply as? [String: Any])?["error"] as? String ?? "").lowercased()
                self.talk[k].state = .failed(why.isEmpty ? "it was not saved. try again." : "it was not saved: " + why)
            }
        }
    }

    func refuse(_ id: Int) {
        guard let i = talk.firstIndex(where: { $0.id == id }) else { return }
        talk[i].state = .dropped
        talk[i].armed = false
    }

    func set(_ rule: Rule, on: Bool) {
        guard let i = rules.firstIndex(where: { $0.id == rule.id }) else { return }
        rules[i].on = on
        guard !Probe.on, let engine else { return }
        engine.client.call(["cmd": "rule-set", "rule_id": rule.id, "on": on], timeout: 30) { [weak self] reply in
            guard let self, let r = Rule(reply), let k = self.rules.firstIndex(where: { $0.id == r.id }) else { return }
            self.rules[k] = r
            self.loadPrefs()
        }
    }

    func remove(_ rule: Rule) {
        rules.removeAll { $0.id == rule.id }
        lit.remove(rule.id)
        guard !Probe.on, let engine else { return }
        engine.client.call(["cmd": "rule-remove", "rule_id": rule.id], timeout: 30) { [weak self] _ in self?.loadPrefs() }
    }

    func reset() { available = nil; rules = []; talk = []; lit = []; draft = ""; settled = nil; prefs = Prefs() }

    /// The sentences the quiet actions write, for a conversation and for a person.
    static func sentence(_ verb: Verb, thread: String) -> String {
        switch verb {
        case .more: return "count my conversation \u{201C}\(thread)\u{201D} more"
        case .less: return "count my conversation \u{201C}\(thread)\u{201D} less"
        case .out: return "leave out my conversation \u{201C}\(thread)\u{201D}"
        }
    }
    static func sentence(_ verb: Verb, person: String) -> String {
        switch verb {
        case .more: return "count what \(person) and i wrote to each other more"
        case .less: return "count what \(person) and i wrote to each other less"
        case .out: return "leave out everything from \(person)"
        }
    }
    enum Verb: CaseIterable {
        case more, less, out
        var words: String { ["count this more", "count this less", "leave this out"][Verb.allCases.firstIndex(of: self)!] }
    }
}

extension AppModel {
    /// A quiet action anywhere: the page, with the sentence already said. Two clicks make a rule: this one, and "do this".
    func teach(_ sentence: String) {
        guard rules.shown, saved.onboarded else { return }
        dismissOverlays()
        tab = .teach
        rules.lit = []
        rules.propose(sentence)
    }

    /// From under an answer: the page, with the rules that shaped it lit.
    func openTeach(lit ids: [String]) {
        guard rules.shown, saved.onboarded else { return }
        dismissOverlays()
        rules.lit = Set(ids)
        tab = .teach
    }
}

/// Three quiet words for a thing that can be weighed: they write the sentence, and the page reads it back.
struct TeachWords: View {
    @Environment(AppModel.self) private var model
    let sentence: (RulesModel.Verb) -> String
    var body: some View {
        if model.rules.shown {
            HStack(spacing: Space.m) {
                ForEach(RulesModel.Verb.allCases, id: \.self) { v in
                    Button(v.words) { model.teach(sentence(v)) }.buttonStyle(QuietButton(size: Face.micro))
                        .help("opens teach with this said: \u{201C}\(sentence(v))\u{201D}. nothing changes until you say do this.")
                }
            }
            .probe("teach.words", .button, scrolls: true)
        }
    }
}

/// The same three, in the menu of a thing that has one: a line of the desk, a row of the sources panel.
struct TeachMenu: ViewModifier {
    @Environment(AppModel.self) private var model
    let thread: String
    func body(content: Content) -> some View {
        content.contextMenu {
            if model.rules.shown, !thread.isEmpty {
                ForEach(RulesModel.Verb.allCases, id: \.self) { v in
                    Button(v.words) { model.teach(RulesModel.sentence(v, thread: thread)) }
                }
            }
        }
    }
}

extension View {
    func teachMenu(thread: String) -> some View { modifier(TeachMenu(thread: thread)) }
}

// MARK: the page

struct TeachView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduce
    @FocusState private var typing: Bool
    static let column: CGFloat = 620
    static let examples = ["count my notes more than my chats", "leave out the group called …", "always answer in lowercase"]

    var body: some View {
        @Bindable var rules = model.rules
        let on = rules.rules.filter(\.on).count
        VStack(spacing: 0) {
            ScrollViewReader { proxy in
                ScrollView {
                    ScrollTop()
                    VStack(alignment: .leading, spacing: 0) {
                        HStack(alignment: .firstTextBaseline, spacing: Space.m) {
                            Text("teach").font(Face.said(26)).tracking(-0.4).foregroundStyle(Ink.ink)
                                .accessibilityAddTraits(.isHeader)
                                .probe("teach.head", .line, scrolls: true)
                            if !rules.rules.isEmpty {
                                Text("\(rules.rules.count) rule\(rules.rules.count == 1 ? "" : "s") · \(on) on").font(Face.meta).foregroundStyle(Ink.faint).lineLimit(1)
                            }
                        }
                        Text("say how context should treat what it holds: what counts more, what to leave out, how to answer. it says back what would change, and nothing does until you say so.")
                            .font(.system(size: Face.label)).foregroundStyle(Ink.soft).lineSpacing(3)
                            .fixedSize(horizontal: false, vertical: true)
                            .padding(.top, Space.s)
                            .probe("teach.what", .text, scrolls: true)
                        if rules.rules.isEmpty, rules.talk.isEmpty {
                            // nothing taught yet: three sentences to press, which say what a rule can be
                            Text("for example").font(Face.meta).foregroundStyle(Ink.faint).padding(.top, Space.xl)
                            Flow(spacing: Space.s, lineSpacing: Space.s) {
                                ForEach(Array(TeachView.examples.enumerated()), id: \.offset) { i, e in
                                    Button(e) { rules.draft = e.replacingOccurrences(of: " …", with: " "); rules.focus += 1 }
                                        .buttonStyle(Starter()).reveal(i)
                                        .probe("teach.example", .block, group: "teach.examples", scrolls: true)
                                }
                            }
                            .padding(.top, Space.s)
                        }
                        VStack(alignment: .leading, spacing: 0) {
                            ForEach(rules.rules) { r in
                                RuleRow(rule: r, lit: rules.lit.contains(r.id), settling: rules.settled == r.id)
                                    .transition(reduce || Probe.still ? .identity : .asymmetric(insertion: .opacity.combined(with: .offset(y: 8)), removal: .opacity))
                            }
                            if !rules.rules.isEmpty { Rectangle().fill(Ink.line).frame(height: 1) }
                        }
                        .padding(.top, rules.rules.isEmpty ? 0 : Space.xl)
                        .animation(Motion.settle(reduce || Probe.still, 0), value: rules.rules.map(\.id))
                        ForEach(rules.talk.filter { $0.state != .dropped }) { t in
                            TeachExchange(turn: t).padding(.top, Space.xl).id("t\(t.id)")
                        }
                        Color.clear.frame(height: 1).id("end")
                    }
                    .frame(maxWidth: TeachView.column, alignment: .leading)
                    .frame(maxWidth: .infinity)
                    .padding(.horizontal, Grid.spinePad).padding(.top, Space.l).padding(.bottom, Space.xl)
                }
                .onChange(of: rules.talk.count) { _, _ in DispatchQueue.main.async { withAnimation(reduce ? nil : Motion.snap(false, 0.4)) { proxy.scrollTo("end", anchor: .bottom) } } }
            }
            // the same input as a conversation's: a raised field, return sends
            HStack(alignment: .center, spacing: Space.s) {
                TextField("", text: $rules.draft, prompt: Text(rules.talk.last?.state == .question ? "answer it" : "tell context how to treat your data").foregroundStyle(Ink.faint), axis: .vertical)
                    .textFieldStyle(.plain).font(.system(size: Face.body)).foregroundStyle(Ink.ink).tint(Ink.ember).lineLimit(1...5)
                    .focused($typing)
                    .onSubmit { rules.propose(rules.draft) }
                    .accessibilityLabel("tell context how to treat your data")
                    .onChange(of: typing) { _, on in model.sideTyping = on }
                let empty = rules.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                Button { rules.propose(rules.draft) } label: {
                    Image(systemName: "arrow.up").font(.system(size: 12, weight: .bold)).foregroundStyle(Ink.paper)
                        .frame(width: 28, height: 28).background(Ink.ink.opacity(empty ? 0.28 : 1), in: Circle()).contentShape(Circle())
                }
                .buttonStyle(.plain).disabled(empty).accessibilityLabel("say it").help("return").ring(15)
            }
            .padding(.leading, 15).padding(.trailing, 12).padding(.vertical, 11)
            .background(Ink.raised, in: RoundedRectangle(cornerRadius: Radius.field, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: Radius.field, style: .continuous).strokeBorder(Ink.ink.opacity(typing ? 0.22 : 0.11), lineWidth: 1))
            .shadow(color: .black.opacity(Probe.on ? 0 : 0.05), radius: 12, y: 4)
            .probe("teach.input", .block)
            .frame(maxWidth: TeachView.column + 28)
            .padding(.horizontal, Grid.spinePad - 14).padding(.top, 8).padding(.bottom, 16)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .onAppear { if !Probe.on { typing = true; model.rules.load(model.engine) } }
        .onChange(of: rules.focus) { _, _ in typing = true }
    }
}

/// One rule: their words, what it does under them in one quiet line, a switch, and the way to remove it.
/// Switched off it dims and its line is struck lightly. One that shaped the answer the owner came from is lit.
struct RuleRow: View {
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduce
    let rule: Rule
    let lit: Bool
    let settling: Bool
    @State private var hover = false

    var body: some View {
        HStack(alignment: .center, spacing: Space.m) {
            VStack(alignment: .leading, spacing: 3) {
                Text(rule.said).font(.system(size: Face.body)).foregroundStyle(Ink.ink)
                    .strikethrough(!rule.on, color: Ink.faint)
                    .fixedSize(horizontal: false, vertical: true)
                    .probe("rule.said", .text, scrolls: true)
                Text(rule.on ? rule.line : "off · " + rule.line).font(Face.meta).foregroundStyle(Ink.soft)
                    .fixedSize(horizontal: false, vertical: true)
                    .probe("rule.line", .text, scrolls: true)
            }
            .opacity(rule.on ? 1 : 0.55)
            .frame(maxWidth: .infinity, alignment: .leading)
            Button("remove") { model.rules.remove(rule) }.buttonStyle(QuietButton(size: Face.small))
                .opacity(hover || Probe.on ? 1 : 0)
                .accessibilityLabel("remove the rule: \(rule.said)")
                .help(rule.kind == "forget" ? "removes the rule. what it forgot comes back if 30 days have not passed." : "removes the rule. nothing in the archive is touched.")
            SetSwitch(label: rule.said, on: rule.on) { model.rules.set(rule, on: $0) }
        }
        .padding(.vertical, Space.m).padding(.horizontal, Space.m)
        .background(lit || settling ? Ink.wash : .clear)
        .overlay(alignment: .leading) { Rectangle().fill(Ink.ember).frame(width: 1.5).opacity(lit ? 1 : 0) }
        .overlay(alignment: .top) { Rectangle().fill(Ink.line).frame(height: 1) }
        .padding(.horizontal, -Space.m)
        .onHover { hover = $0 }
        .animation(Motion.lit(reduce || Probe.still), value: rule.on)
        .animation(reduce || Probe.still ? nil : .easeOut(duration: 0.6), value: settling)
        .probe("rule.row", .block, group: "rule.rows", scrolls: true)
    }
}

/// Their sentence, rising as a question does, and under it the engine's reading as a card.
struct TeachExchange: View {
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduce
    let turn: Teaching
    @State private var open = Probe.still

    var body: some View {
        let still = reduce || Probe.still
        VStack(alignment: .leading, spacing: Space.m) {
            HStack(spacing: 0) {
                Spacer(minLength: 64)
                Text(turn.said).font(.system(size: Face.body)).lineSpacing(3).foregroundStyle(Ink.ink)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.horizontal, 15).padding(.vertical, 10)
                    .background(Ink.wash, in: RoundedRectangle(cornerRadius: Radius.field, style: .continuous))
                    .probe("teach.said", .text, scrolls: true)
                    .modifier(Lift(on: turn.state == .reading))
            }
            switch turn.state {
            case .reading:
                HStack(spacing: 9) { Spinner(size: 11); Text("reading what you said").font(.system(size: Face.label)).foregroundStyle(Ink.soft) }
                    .probe("teach.reading", .line, scrolls: true)
            case .saved:
                Text("done. it is in your rules.").font(Face.meta).foregroundStyle(Ink.soft)
                    .probe("teach.done", .line, scrolls: true)
            case .failed(let why):
                Text(why).font(.system(size: Face.label)).foregroundStyle(Ink.soft).fixedSize(horizontal: false, vertical: true)
                    .probe("teach.failed", .text, scrolls: true)
            case .question:
                // a question back is a question, set as one: no buttons, and the input waits for the answer
                VStack(alignment: .leading, spacing: Space.xs) {
                    Text("context asks").font(Face.meta).foregroundStyle(Ink.faint)
                    Text(turn.proposal?.ask ?? "").font(Face.said(Face.read)).lineSpacing(5).foregroundStyle(Ink.ink)
                        .fixedSize(horizontal: false, vertical: true)
                        .probe("teach.ask", .text, scrolls: true)
                }
            case .proposed, .dropped:
                if let p = turn.proposal { card(p).scaleEffect(open ? 1 : 0.97, anchor: .topLeading).opacity(open ? 1 : 0) }
            }
        }
        .onAppear { if !still { withAnimation(Motion.unfold(false)) { open = true } } else { open = true } }
        .onChange(of: turn.state) { _, _ in if !still { open = false; withAnimation(Motion.unfold(false)) { open = true } } }
    }

    private func card(_ p: Proposal) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(p.destructive ? "this would forget" : "context understood").font(Face.meta).foregroundStyle(Ink.faint)
            Text(p.says).font(Face.said(Face.read)).lineSpacing(5).foregroundStyle(Ink.ink)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.top, Space.xs)
                .probe("teach.says", .text, scrolls: true)
            if !p.touches.isEmpty {
                Text(p.touches).font(Face.meta).monospacedDigit().foregroundStyle(Ink.soft)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.top, Space.s)
                    .probe("teach.touches", .text, scrolls: true)
            }
            if p.destructive {
                // calm, and whole: what goes, that it is kept, and that it comes back. the second press is the only guard
                Text("what it covers is taken out of the archive and out of every answer. it is kept apart for 30 days: remove the rule in that time and it all comes back. after that it is gone.")
                    .font(.system(size: Face.small)).foregroundStyle(Ink.soft).lineSpacing(2.5)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.top, Space.m)
                    .probe("teach.forget", .text, scrolls: true)
            }
            HStack(spacing: Space.l) {
                Button(p.destructive ? (turn.armed ? "press again to forget it" : "forget this") : "do this") { withAnimation(Motion.settle(reduce, 0)) { model.rules.accept(turn.id) } }
                    .buttonStyle(PingButton())
                    .accessibilityLabel(p.destructive ? (turn.armed ? "press again to forget it" : "forget this. a second press is asked for") : "do this")
                    .probe("teach.do", .button, scrolls: true)
                Button("not this") { model.rules.refuse(turn.id) }.buttonStyle(QuietButton(size: Face.label))
                    .probe("teach.no", .button, scrolls: true)
                Spacer(minLength: 0)
            }
            .padding(.top, Space.l)
        }
        .padding(Space.l)
        .frame(maxWidth: 520, alignment: .leading)
        .background(Ink.raised, in: RoundedRectangle(cornerRadius: Radius.card, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: Radius.card, style: .continuous).strokeBorder(p.destructive ? Ink.ink.opacity(0.45) : Ink.line, lineWidth: 1))
        .probe("teach.card", .block, scrolls: true)
    }
}

// MARK: in the gate

extension LayoutTest {
    static let ruleRows: [[String: Any]] = [
        ["id": "r1", "said": "Value the seed swap over other chats", "kind": "weigh", "target": "thread:the seed swap", "strength": 2.0, "made": "2026-11-19T10:00:00Z", "on": true, "affects": ["rows": 3_000, "threads": 1]],
        ["id": "r2", "said": "leave out the group called the allotment committee and friends of the lower field (2026), all of it, including what i wrote there myself", "kind": "leave_out", "target": "thread", "made": "2026-11-13T10:00:00Z", "on": false, "affects": ["rows": 12_000, "threads": 1]],
        ["id": "r3", "said": "always answer in lowercase", "kind": "treat", "target": "", "made": "2026-11-21T09:00:00Z", "on": true, "affects": ["rows": 0, "threads": 0]],
    ]

    static func teachScreens(_ m: AppModel, main: @escaping (Tab) -> Void) -> [(String, () -> Void)] {
        func teach(_ rules: [[String: Any]] = [], _ more: () -> Void = {}) {
            main(.teach)
            m.rules.available = true
            m.rules.rules = rules.compactMap { Rule($0) }
            more()
        }
        func said(_ text: String, _ reply: [String: Any]?, armed: Bool = false) {
            var t = Teaching(id: 1, said: text)
            if let reply, let p = Proposal(reply) { t.proposal = p; t.state = !p.ask.isEmpty && p.rule == nil ? .question : .proposed; t.armed = armed }
            m.rules.talk = [t]
        }
        return [
            ("teach-empty", { teach() }),
            ("teach-three", { teach(ruleRows) { m.rules.lit = ["r1"] } }),
            ("teach-proposal", { teach(Array(ruleRows.prefix(1))) {
                said("count my notes more than my chats", ["rule": ["id": "", "said": "count my notes more than my chats", "kind": "weigh", "target": "src:apple_notes", "strength": 1.5, "on": true, "affects": ["rows": 300_000, "threads": 0]],
                                                           "says": "your notes will count about one and a half times as much as a chat message when context picks what to read for an answer.", "ask": "",
                                                           "affects": ["rows": 300_000, "threads": 0, "from": "2012-06-01", "to": "2026-11-09"], "destructive": false])
            } }),
            ("teach-question", { teach() {
                said("leave out the group", ["rule": NSNull(), "says": "", "ask": "which group? there are three with a name like that: the allotment committee, the flat, and seed swap.", "affects": [String: Any](), "destructive": false])
            } }),
            ("teach-reading", { teach(ruleRows) { said("count what ines and i wrote to each other more", nil) } }),
            ("teach-forget", { teach(Array(ruleRows.prefix(1))) {
                said("forget everything from the group called seed swap", ["rule": ["id": "", "said": "forget everything from the group called seed swap", "kind": "forget", "target": "thread:seed swap", "on": true, "affects": ["rows": 1_500, "threads": 1]],
                                                                           "says": "every message in the group seed swap, yours and other people's, would be removed from this mac's archive.", "ask": "",
                                                                           "affects": ["rows": 1_500, "threads": 1, "from": "2022-03-05", "to": "2026-10-30"], "destructive": true], armed: true)
            } }),
            // an engine without the commands: no entry in the sidebar, no quiet words on a person or a note
            ("teach-hidden", { main(.home); m.rules.available = false }),
            // an answer two rules shaped, in a window wide enough for notes, with the rules on offer
            ("teach-shaped", {
                main(.home)
                m.saved.sidebar = false
                m.rules.available = true
                m.rules.rules = ruleRows.compactMap { Rule($0) }
                var d = lease
                d["rules"] = ["r1", "r3"]
                m.ask.turns = [Turn(id: 0, q: question, answer: Answer(d, tag: "t0"))]
                m.ask.asking = false
                m.ask.pinned = Pick(turn: 0, n: 2)
            }),
        ]
    }

    static func teachCheck(_ screen: String, _ at: String, _ size: CGSize, _ found: [ProbeInfo]) -> [String] {
        var out: [String] = []
        func has(_ n: String) -> Bool { found.contains { $0.name == n } }
        func count(_ n: String) -> Int { found.filter { $0.name == n }.count }
        let main = size.width - (found.first { $0.name == "side.ground" }?.frame.maxX ?? 0)
        if screen.hasPrefix("teach-"), screen != "teach-hidden", screen != "teach-shaped" {
            if !has("teach.head") || !has("teach.input") { out.append("\(at): the page has no name or no input") }
            if found.contains(where: { $0.name == "side.ground" }), !has("side.teach") { out.append("\(at): the sidebar has no way to this page") }
            if let input = found.first(where: { $0.name == "teach.input" }), input.frame.maxY > size.height - 8 || input.frame.maxY < size.height - 40 { out.append("\(at): the input is not docked at the foot") }
            let want = ["teach-empty": 0, "teach-three": 3, "teach-proposal": 1, "teach-question": 0, "teach-forget": 1, "teach-reading": 3][screen] ?? 0
            if count("rule.row") != want { out.append("\(at): \(count("rule.row")) rules are listed, not \(want)") }
            if (screen == "teach-empty") != (count("teach.example") == 3) { out.append("\(at): the three examples are \(count("teach.example") == 3 ? "drawn though there is something to show" : "missing from the empty page")") }
            if screen == "teach-proposal", !has("teach.card") || !has("teach.says") || !has("teach.touches") || count("teach.do") != 1 || count("teach.no") != 1 { out.append("\(at): the reading is not a card with what it understood, what it touches and two buttons") }
            if screen == "teach-question", !has("teach.ask") || has("teach.do") { out.append("\(at): a question back is not shown as a question alone") }
            if screen == "teach-forget", !has("teach.forget") || count("teach.do") != 1 { out.append("\(at): a rule that forgets does not say what is kept and for how long") }
            if screen == "teach-reading", !has("teach.reading") { out.append("\(at): nothing says the sentence is being read") }
        }
        if screen == "teach-hidden", has("side.teach") || has("teach.words") || has("chat.rules") { out.append("\(at): teach is offered though the engine does not know the commands") }
        if screen == "teach-shaped" {
            if !has("chat.rules") { out.append("\(at): nothing says two rules shaped this answer") }
            if main >= PageMeasure.least, !has("teach.words") { out.append("\(at): the chosen note does not offer to count it more, less or leave it out") }
        }
        return out
    }
}
