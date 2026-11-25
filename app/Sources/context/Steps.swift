import SwiftUI

/// One thing the model did on the way to an answer: a search, a thread read, a look at a person.
/// The engine says it twice: when the call starts, and again with what it found.
struct WorkStep: Identifiable, Equatable {
    let n: Int
    var tool: String
    var args: [String: String] = [:]
    var found: Int?
    var thread = ""
    var src = ""
    var label = ""              // the engine's own words for this step, when it sends them
    var id: Int { n }

    init?(_ d: [String: Any]?) {
        guard let d, let tool = d["tool"] as? String else { return nil }
        n = d["n"] as? Int ?? 0
        self.tool = tool
        for (k, v) in d["args"] as? [String: Any] ?? [:] {
            if let s = v as? String { args[k] = s } else if let a = v as? [Any] { args[k] = a.map { "\($0)" }.joined(separator: ", ") } else if let i = v as? NSNumber { args[k] = "\(i)" }
        }
        found = d["found"] as? Int
        thread = d["thread"] as? String ?? ""
        src = d["src"] as? String ?? ""
        label = (d["label"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var dict: [String: Any] {
        var d: [String: Any] = ["n": n, "tool": tool, "args": args, "thread": thread, "src": src, "label": label]
        if let found { d["found"] = found }
        return d
    }

    /// What the step was given under one of these names, as words to show. A row's id is not words: it is left out.
    private func arg(_ keys: String...) -> String { keys.compactMap { args[$0] }.first { !$0.isEmpty && !WorkStep.idLike($0) } ?? "" }

    /// "LI11211", "W48213", "a3f9c2d17e": one unbroken token of five or more characters with a digit in it, or nothing
    /// but digits and hex. That is the archive's name for a row, not something to read.
    static func idLike(_ s: String) -> Bool {
        let t = s.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty, !t.contains(where: \.isWhitespace) else { return false }
        // a year, a day, a time are figures to read
        if t.allSatisfy({ $0.isNumber || $0 == "-" || $0 == ":" || $0 == "/" }), t.count <= 4 || t.contains("-") || t.contains(":") || t.contains("/") { return false }
        let core = t.filter { $0.isLetter || $0.isNumber }
        let digits = core.contains(where: \.isNumber), letters = core.contains(where: \.isLetter)
        if core.count >= 5, digits, letters { return true }
        if core.count >= 6, digits, !letters { return true }
        return core.count < 5 && digits && letters && t == t.uppercased()
    }

    /// The same for a whole line: no word of it may be a row's id.
    static func hasID(_ line: String) -> Bool {
        line.split(whereSeparator: { $0.isWhitespace || "\u{201C}\u{201D}\"',;:()".contains($0) }).contains { idLike(String($0)) }
    }

    /// "a linkedin message", "a whatsapp thread": what is being read, said by its source when it has no name to show.
    private func a(_ thing: String) -> String {
        guard let s = sources.first else { return thing == "message" ? "a message" : "a \(thing)" }
        return "a \(Catalog.info(s).name) \(thing)"
    }

    /// The engine's words when it sent them and they are words; otherwise ours.
    var line: String {
        if !label.isEmpty, !WorkStep.hasID(label) { return label.prefix(1).lowercased() + label.dropFirst() }
        // what the owner asked for is their own words, figures and all; anything else that still holds an id is said plainly
        if ["search", "saved", "links", "timeline"].contains(tool) || !WorkStep.hasID(made) { return made }
        return (WorkStep.verbs[tool] ?? "reading") + " " + a("message")
    }

    private static let verbs = ["search": "searching", "read_thread": "reading", "person": "looking up", "doc": "reading", "saved": "going through", "links": "collecting"]

    /// The checks: no step line shows a row's id, whatever the engine sent.
    static func faults() -> [String] {
        var out: [String] = []
        let cases: [([String: Any], String)] = [
            (["tool": "doc", "args": ["id": "LI11211"], "src": "linkedin", "found": 1], "reading a linkedin message"),
            (["tool": "read", "args": ["id": "LI11211"], "src": "linkedin"], ""),
            (["tool": "read_thread", "args": ["id": "T48213"], "src": "whatsapp"], "reading a whatsapp thread"),
            (["tool": "read_thread", "args": ["id": "T1"]], "reading a thread"),
            (["tool": "doc", "args": ["id": "LI11211"], "label": "reading a message from Maya on linkedin"], "reading a message from Maya on linkedin"),
            (["tool": "doc", "args": ["id": "LI11211"], "label": "reading LI11211", "src": "linkedin"], "reading a linkedin message"),
            (["tool": "search", "args": ["q": "lease renewal 2024", "sources": ["whatsapp"]]], "searching whatsapp for \u{201C}lease renewal 2024\u{201D}"),
            (["tool": "timeline", "args": ["from": "2026-09-01", "to": "2026-11-14"]], "checking 2026-09-01 to 2026-11-14"),
            (["tool": "person", "args": ["name": "Ines"]], "looking up Ines"),
        ]
        for (d, want) in cases {
            guard let s = WorkStep(d) else { out.append("steps: a step did not parse"); continue }
            if WorkStep.hasID(s.line) && d["tool"] as? String != "timeline" { out.append("steps: a row's id shows in \u{201C}\(s.line)\u{201D}") }
            if !want.isEmpty, s.line != want { out.append("steps: \u{201C}\(s.line)\u{201D} should read \u{201C}\(want)\u{201D}") }
        }
        return out
    }

    private static func cut(_ s: String, _ max: Int = 48) -> String { s.count > max ? String(s.prefix(max - 1)) + "…" : s }

    /// The sources this step looked in, by catalog id, when it says.
    var sources: [String] {
        let raw = src.isEmpty ? arg("sources", "source", "src") : src
        return raw.split { $0 == "," || $0 == " " }.map(String.init).filter { !$0.isEmpty }
    }

    /// What it is doing, in our words: "searching whatsapp and telegram for the lease".
    private var made: String {
        let names = sources.prefix(3).map { Catalog.info($0).name }
        let places = names.isEmpty ? "" : " " + (names.count > 2 ? names.dropLast().joined(separator: ", ") + " and " + names.last! : names.joined(separator: " and "))
        let q = WorkStep.cut(arg("q", "query", "text", "words"))
        switch tool {
        case "first_look": return "a first look through everything"
        case "search": return "searching" + places + (q.isEmpty ? "" : " for \u{201C}\(q)\u{201D}")
        case "read_thread":
            let who = thread.isEmpty || WorkStep.idLike(thread) ? arg("thread", "name") : thread
            return who.isEmpty ? "reading " + a("thread") : "reading your thread with \(WorkStep.cut(who, 40))"
        case "person": return "looking up " + (arg("name", "who", "q").isEmpty ? "a person" : WorkStep.cut(arg("name", "who", "q"), 40))
        case "timeline":
            let a = arg("from", "after", "start"), b = arg("to", "before", "end")
            return a.isEmpty && b.isEmpty ? "checking the dates" : "checking \(a.isEmpty ? "the start" : String(a.prefix(10))) to \(b.isEmpty ? "now" : String(b.prefix(10)))"
        case "card": return "opening this morning's card"
        case "saved": return "going through what you saved" + (q.isEmpty ? "" : " for \u{201C}\(q)\u{201D}")
        case "links": return "collecting the links" + (q.isEmpty ? "" : " about \u{201C}\(q)\u{201D}")
        case "doc": return "reading " + (arg("title", "name").isEmpty ? (sources.isEmpty ? "a document" : a("message")) : WorkStep.cut(arg("title", "name"), 44))
        case "read", "row", "message", "read_row", "read_message": return "reading " + a("message")
        case "profile": return "reading what context knows about you"
        case "stats": return "counting"
        case "sources": return "checking which sources hold it"
        default: return tool.replacingOccurrences(of: "_", with: " ")
        }
    }

    /// One symbol per kind of step, for when it names no source.
    var symbol: String {
        switch tool {
        case "search", "first_look": return "magnifyingglass"
        case "read_thread": return "bubble.left.and.bubble.right"
        case "person": return "person"
        case "timeline": return "calendar"
        case "card": return "sun.max"
        case "saved": return "bookmark"
        case "links": return "link"
        case "doc": return "doc.text"
        case "profile": return "person.text.rectangle"
        case "stats": return "number"
        case "sources": return "tray.full"
        default: return "circle.dotted"
        }
    }
}

/// What an answer cost, as the engine counts it.
struct Usage: Equatable {
    var calls = 0, tools = 0, tokensIn = 0, tokensOut = 0
    init() {}
    init(_ d: [String: Any]?) {
        calls = d?["calls"] as? Int ?? 0
        tools = d?["tools"] as? Int ?? 0
        tokensIn = d?["in"] as? Int ?? 0
        tokensOut = d?["out"] as? Int ?? 0
    }
    var dict: [String: Any] { ["calls": calls, "tools": tools, "in": tokensIn, "out": tokensOut] }
    var isEmpty: Bool { calls == 0 && tools == 0 && tokensIn == 0 && tokensOut == 0 }

    static func short(_ n: Int) -> String { n >= 1000 ? "\(Int((Double(n) / 1000).rounded()))k" : "\(n)" }
}

/// Above an answer: what the model is doing while it works, then "worked for 9 s · 5 steps", which unfolds to the steps.
struct StepsLine: View {
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduce
    let turn: Turn

    var body: some View {
        let running = turn.answer == nil
        let steps = running ? (turn.live?.steps ?? []) : (turn.answer?.steps ?? [])
        let open = model.ask.openHow.contains(turn.id)
        VStack(alignment: .leading, spacing: 0) {
            if running {
                TimelineView(.periodic(from: turn.at, by: 1)) { t in
                    let s = max(0, Int(t.date.timeIntervalSince(turn.at)))
                    let now = steps.last
                    let line = turn.live?.line ?? (s < 45 ? "reading your history. about a quarter of a minute." : "still reading. a long one can take a minute or two.")
                    // the working line: what it is doing in words, on one or two lines that change whole (the old one
                    // goes before the new one comes), and under it the figures, which run in place. a hairline sweeps
                    // under both while it works: the same sign a source being read carries on the wall
                    let said = now.map(\.line) ?? line
                    VStack(alignment: .leading, spacing: Space.s) {
                        HStack(alignment: .top, spacing: 9) {
                            icon(now, live: true)
                            VStack(alignment: .leading, spacing: 3) {
                                Flap(text: said, font: .system(size: Face.label), color: Ink.ink, lines: 2)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                    .background(alignment: .topLeading) {
                                        Text(said).font(.system(size: Face.label)).lineLimit(2).frame(maxWidth: .infinity, alignment: .leading)
                                            .probe("chat.status", .text, scrolls: true).hidden()
                                    }
                                HStack(spacing: 0) {
                                    Text("\(s) s").contentTransition(.numericText())
                                    if steps.count > 1 { Text("  ·  step \(steps.count)") }
                                    if let f = now?.found { Text("  ·  \(Words.count(f)) found").contentTransition(.numericText()) }
                                }
                                .font(.system(size: Face.small)).monospacedDigit().foregroundStyle(Ink.faint).lineLimit(1).fixedSize()
                                .probe("chat.status.meta", .line, scrolls: true)
                            }
                        }
                        Sweep().frame(width: 96, height: 1.5).padding(.leading, 27)
                            .accessibilityHidden(true)
                    }
                    .animation(reduce ? nil : Motion.hover, value: steps.count)
                }
            } else if let a = turn.answer, !steps.isEmpty || a.secs >= 1 {
                Button {
                    guard !steps.isEmpty else { return }
                    withAnimation(Motion.tray(reduce)) { if open { model.ask.openHow.remove(turn.id) } else { model.ask.openHow.insert(turn.id) } }
                } label: {
                    HStack(spacing: 6) {
                        Text(StepsLine.summary(secs: a.secs, steps: steps.count))
                        if !steps.isEmpty {
                            Image(systemName: "chevron.down").font(.system(size: 8, weight: .bold)).rotationEffect(.degrees(open ? 180 : 0))
                        }
                    }
                    .frame(height: 22)
                }
                .buttonStyle(QuietButton(size: 12))
                .probe("chat.steps", .button, scrolls: true)
                if open {
                    VStack(alignment: .leading, spacing: 0) {
                        ForEach(steps) { step in
                            HStack(alignment: .center, spacing: 9) {
                                icon(step, live: false)
                                Text(step.line).font(.system(size: 13)).foregroundStyle(Ink.soft)
                                    .fixedSize(horizontal: false, vertical: true)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                    .probe("chat.step", .text, group: "chat.steps\(turn.id)", scrolls: true)
                                if let f = step.found {
                                    Text("\(Words.count(f)) found").font(.system(size: 12, weight: .medium)).monospacedDigit().foregroundStyle(Ink.faint).lineLimit(1).fixedSize()
                                }
                            }
                            .padding(.vertical, 5)
                        }
                        if !a.usage.isEmpty {
                            Text(StepsLine.cost(a.usage, steps: steps))
                                .font(.system(size: 12, weight: .medium)).monospacedDigit().foregroundStyle(Ink.faint)
                                .padding(.top, 5).padding(.leading, 27)
                                .probe("chat.usage", .line, scrolls: true)
                        }
                    }
                    .padding(.top, 4).padding(.leading, 2)
                    .transition(.opacity)
                }
            }
        }
    }

    @ViewBuilder private func icon(_ step: WorkStep?, live: Bool) -> some View {
        Group {
            if let src = step?.sources.first, !src.isEmpty {
                SourceIcon(id: src, size: 15)
            } else if let step {
                Image(systemName: step.symbol).font(.system(size: 11, weight: .medium)).foregroundStyle(Ink.soft)
            } else {
                Spinner(size: 11)
            }
        }
        .frame(width: 18, height: 18)
    }

    /// "worked for 9 s · 5 steps"
    static func summary(secs: Double, steps: Int) -> String {
        let s = Int(secs.rounded())
        let time = s < 1 ? "" : (s < 90 ? "worked for \(s) s" : "worked for \(s / 60) min \(s % 60) s")
        let n = steps == 0 ? "" : "\(steps) step\(steps == 1 ? "" : "s")"
        return [time, n].filter { !$0.isEmpty }.joined(separator: "  ·  ")
    }

    /// "2 searches · 1 thread read · 27k tokens read"
    static func cost(_ u: Usage, steps: [WorkStep]) -> String {
        let searches = steps.filter { $0.tool == "search" }.count, threads = steps.filter { $0.tool == "read_thread" }.count
        var parts: [String] = []
        if searches > 0 { parts.append("\(searches) search\(searches == 1 ? "" : "es")") }
        if threads > 0 { parts.append("\(threads) thread\(threads == 1 ? "" : "s") read") }
        if u.tokensIn > 0 { parts.append("\(Usage.short(u.tokensIn)) tokens read") }
        if u.tokensOut > 0 { parts.append("\(Usage.short(u.tokensOut)) written") }
        return parts.joined(separator: "  ·  ")
    }
}
