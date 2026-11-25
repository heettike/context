import AppKit
import IOKit.ps
import Observation

/// One short thing worth saying now, tied to something in the past.
struct Nudge: Identifiable, Equatable {
    let id: String
    let kind: String      // promise, drift, before, again, loop, focus, model
    let text: String
    var detail = ""
    var query = ""        // what "show me" searches for
    var src = ""
    var loop: Loop?
}

/// Connects now (Activity) to past (the archive, the open loops, the stated focus) and says so, briefly.
/// The rules here are local and plain. `askEngine` is the one hook for a model-written nudge.
@Observable final class Coach {
    var nudges: [Nudge] = []
    var index = 0

    @ObservationIgnored unowned let model: AppModel
    @ObservationIgnored private var before: Nudge?
    @ObservationIgnored private var lastTopic = ""
    @ObservationIgnored private var fromModel: [Nudge] = []
    @ObservationIgnored private var lastAsked = Date.distantPast
    @ObservationIgnored private var lastCategory = ""
    @ObservationIgnored private var asking = false
    @ObservationIgnored private var timer: Timer?

    init(model: AppModel) { self.model = model }

    var current: Nudge? { nudges.isEmpty ? nil : nudges[min(index, nudges.count - 1)] }

    func start() {
        guard timer == nil else { return }
        evaluate()
        timer = Timer.scheduledTimer(withTimeInterval: 30, repeats: true) { [weak self] _ in self?.evaluate() }
    }

    func move(_ by: Int) {
        guard !nudges.isEmpty else { return }
        index = max(0, min(nudges.count - 1, index + by))
    }

    // MARK: words

    static let stop: Set<String> = ["the", "and", "for", "with", "that", "this", "from", "into", "have", "has", "not", "are", "was",
        "you", "your", "our", "out", "get", "got", "make", "more", "all", "any", "new", "one", "two", "week", "ship", "finish", "done","about", "which", "would", "there", "their", "could", "should", "please", "these", "those",
        "because", "after", "before", "where", "while", "using", "going", "being", "other", "still", "thing", "things", "really",
        "right", "think", "build", "makes", "first", "every", "files", "https", "users", "window", "google", "chrome", "safari",
        "claude", "cursor", "codex", "untitled", "something", "anything", "everything", "without", "between", "through",
        "again", "today", "tomorrow", "yesterday", "check", "update", "change", "create", "write", "works", "working", "needs"]

    static func words(_ s: String, min: Int) -> [String] {
        var seen = Set<String>(), out: [String] = []
        for w in s.lowercased().split(whereSeparator: { !$0.isLetter && !$0.isNumber }).map(String.init)
        where w.count >= min && !stop.contains(w) && !w.allSatisfy(\.isNumber) && seen.insert(w).inserted {
            out.append(w)
        }
        return out
    }

    var focusWords: [String] { Coach.words(model.saved.focus, min: 3) }

    // MARK: rules

    func evaluate() {
        guard model.saved.onboarded else { nudges = []; return }
        let act = model.activity
        let focus = model.saved.focus.trimmingCharacters(in: .whitespaces)
        var out: [Nudge] = []

        // 1. a promise, while you are in that very chat
        let app = act.app.lowercased(), title = act.title.lowercased()
        let chat = ["whatsapp": "W", "messages": "I", "telegram": "T", "mail": "E", "slack": "S"].first { app.contains($0.key) }
        let agents = ["terminal", "iterm", "ghostty", "warp", "cursor", "claude", "codex", "code"].contains { app.contains($0) }
        let open = model.loops.open
        var used = Set<String>()
        if let l = open.first(where: { $0.kind != "agent" && $0.thread.count >= 3 && title.contains($0.thread.lowercased()) }) {
            out.append(Nudge(id: "loop:" + l.q, kind: "promise", text: l.q,
                             detail: "you are in this chat now  ·  \(l.kindWords)  ·  \(Words.ago(l.date))", query: l.thread, loop: l))
            used.insert(l.q)
        } else if let chat, let l = open.first(where: { $0.kind != "agent" && ($0.ids.first ?? "").hasPrefix(chat.value) }) {
            out.append(Nudge(id: "loop:" + l.q, kind: "promise", text: l.q,
                             detail: "while you are in \(chat.key)  ·  \(l.thread)  ·  \(Words.ago(l.date))", query: l.thread, loop: l))
            used.insert(l.q)
        } else if agents, let l = open.first(where: { $0.kind == "agent" }) {
            out.append(Nudge(id: "loop:" + l.q, kind: "promise", text: l.q,
                             detail: "an agent session stopped on this  ·  \(l.thread)  ·  \(Words.ago(l.date))", query: l.thread, loop: l))
            used.insert(l.q)
        }

        // an hour that does not match the stated week is not said out loud any more. it is only one of the two
        // moments at which the model is asked whether anything is worth saying.
        let fw = focusWords
        let hour = act.recent(60)
        let active = hour.reduce(0) { $0 + $1.secs }
        let offCourse = !fw.isEmpty && active >= 25 * 60
            && hour.filter { Activity.matches($0, fw) }.reduce(0) { $0 + $1.secs } / active < 0.25

        // 3. you have done this before
        refreshBefore()
        if let b = before { out.append(b) }

        // the model's sentence, when one came back, stands in for the local line about the same thing
        let drifting = offCourse
        for m in fromModel {
            if let i = out.firstIndex(where: { $0.kind == m.kind && $0.loop == nil }) { out[i] = m } else { out.insert(m, at: min(1, out.count)) }
        }

        // 5. otherwise, the top thing left hanging
        if let l = open.first(where: { !used.contains($0.q) }) {
            out.append(Nudge(id: "loop:" + l.q, kind: "loop", text: l.q,
                             detail: "\(l.kindWords)  ·  \(l.thread)  ·  \(Words.ago(l.date))", query: l.thread, loop: l))
        }

        let now = Date().timeIntervalSince1970
        let keep = out.filter { (model.saved.hidden[$0.id] ?? 0) < now }
        if keep != nudges {
            let was = current?.id
            nudges = keep
            index = keep.firstIndex { $0.id == was } ?? 0
        }
        askEngine(drifting: drifting)
    }

    /// Looks in old sessions, prompts and notes for the words in front of you now.
    private func refreshBefore() {
        let act = model.activity
        let home = model.engine.home
        let title = act.trusted ? act.title : ""
        DispatchQueue.global(qos: .utility).async {
            var topic = title
            var keys = Coach.words(topic, min: 5)
            if keys.count < 2, let p = Coach.latestPrompt(home: home) { topic = p; keys = Coach.words(String(p.prefix(300)), min: 5) }
            keys = Array(keys.sorted { $0.count > $1.count }.prefix(3))
            guard keys.count >= 2 else { DispatchQueue.main.async { self.before = nil }; return }
            let sig = keys.joined(separator: " ")
            var same = false
            DispatchQueue.main.sync { same = sig == self.lastTopic; self.lastTopic = sig }
            if same { return }
            let cutoff = Words.isoDay(Date().addingTimeInterval(-3 * 86400))
            let needles = keys.map { Array($0.utf8) }
            var best: Hit?
            for (name, kind) in [("sessions.jsonl", "session"), ("prompts.jsonl", "prompt"), ("docs.jsonl", "doc")] {
                let path = home.appendingPathComponent(name).path
                let fd = open(path, O_RDONLY)
                guard fd >= 0 else { continue }
                defer { close(fd) }
                for c in Jsonl.candidates(path: path, needles: needles, stop: nil).suffix(200) {
                    guard let d = Jsonl.read(fd: fd, c), let h = Jsonl.hit(d, kind: kind, offset: c.0),
                          !h.ts.isEmpty, String(h.ts.prefix(10)) < cutoff else { continue }
                    let hay = (h.thread + " " + h.text).lowercased()
                    guard keys.allSatisfy({ hay.contains($0) }) else { continue }
                    if best == nil || h.ts > best!.ts { best = h }
                }
            }
            let nudge = best.map { h in
                Nudge(id: "before:" + sig, kind: "before",
                      text: "you have been here before: \(h.thread.isEmpty ? Catalog.info(h.src).name : h.thread.lowercased()), \(Words.day(h.ts)).",
                      detail: "same words then as now: \(keys.joined(separator: ", ")). open it before you redo it.",
                      query: sig, src: h.src)
            }
            DispatchQueue.main.async { self.before = nudge; self.evaluate() }
        }
    }

    static func latestPrompt(home: URL) -> String? {
        let path = home.appendingPathComponent("prompts.jsonl").path
        var top = "", at = (0, 0)
        Jsonl.lines(path: path, from: 0, to: .max, stop: nil) { line, off in
            if let d = Jsonl.date(in: line), d >= top { top = d; at = (off, line.count) }
        }
        guard !top.isEmpty, top >= Words.isoDay(Date().addingTimeInterval(-2 * 86400)) else { return nil }
        let fd = open(path, O_RDONLY)
        guard fd >= 0 else { return nil }
        defer { close(fd) }
        return Jsonl.read(fd: fd, at)?["text"] as? String
    }

    // MARK: answering a nudge

    enum Answer: String { case ok, no, later }

    func answer(_ a: Answer, _ nudge: Nudge? = nil) {
        guard let n = nudge ?? current else { return }
        let now = Date()
        if let l = n.loop, a != .later {
            model.loops.score(l, ok: a == .ok)
        }
        let until: Date
        switch a {
        case .later:
            until = (Calendar.current.date(byAdding: .day, value: 1, to: Calendar.current.startOfDay(for: now)) ?? now).addingTimeInterval(6 * 3600)
        default:
            until = now.addingTimeInterval(30 * 86400)
        }
        model.saved.hidden[n.id] = until.timeIntervalSince1970
        model.saved.hidden = model.saved.hidden.filter { $0.value > now.timeIntervalSince1970 }
        model.persist()
        let row: [String: Any] = ["ts": Int(now.timeIntervalSince1970), "id": n.id, "kind": n.kind, "text": n.text, "answer": a.rawValue]
        if let data = try? JSONSerialization.data(withJSONObject: row, options: [.sortedKeys]) {
            if !Engine.debug { Files.append(data, to: model.engine.file("nudges.jsonl")) }
        }
        fromModel.removeAll { $0.id == n.id }
        if n.kind == "before" { before = nil }
        evaluate()
    }

    // MARK: the model's line

    static func category(_ app: String) -> String {
        let a = app.lowercased()
        if ["whatsapp", "messages", "telegram", "slack", "mail", "discord", "signal"].contains(where: a.contains) { return "talk" }
        if ["terminal", "iterm", "ghostty", "warp", "cursor", "xcode", "code", "claude", "codex", "zed"].contains(where: a.contains) { return "build" }
        if ["arc", "brave", "chrome", "dia", "edge", "firefox", "safari"].contains(where: a.contains) { return "browse" }
        return a.isEmpty ? "" : "other"
    }

    /// On battery with less than a fifth left: do not spend it on a model call.
    static var lowBattery: Bool {
        guard let blob = IOPSCopyPowerSourcesInfo()?.takeRetainedValue(),
              let list = IOPSCopyPowerSourcesList(blob)?.takeRetainedValue() as? [CFTypeRef] else { return false }
        for src in list {
            guard let d = IOPSGetPowerSourceDescription(blob, src)?.takeUnretainedValue() as? [String: Any] else { continue }
            let onBattery = (d[kIOPSPowerSourceStateKey] as? String) == kIOPSBatteryPowerValue
            if onBattery, let now = d[kIOPSCurrentCapacityKey] as? Int, let max = d[kIOPSMaxCapacityKey] as? Int, max > 0,
               Double(now) / Double(max) < 0.2 { return true }
        }
        return false
    }

    /// Asks the model for one sentence: `python3 -m ctx coach --now <json>`, which runs on the user's own plan
    /// and takes 15 to 40 seconds. Off until the owner switches it on in settings (it sends the app in front and its window
    /// title to the model). Then sparingly: at most once in 20 minutes, only when the local drift rule has just
    /// fired or the app in front changed kind, never two at once, never on a nearly empty battery, and never
    /// when no plan is signed in. Its line takes the place of the local one of the same kind.
    private func askEngine(drifting: Bool) {
        let act = model.activity
        let cat = Coach.category(act.app)
        let moved = !cat.isEmpty && !lastCategory.isEmpty && cat != lastCategory
        if !cat.isEmpty { lastCategory = cat }
        guard model.saved.nudgeModel, drifting || moved, !asking, !act.frozen, model.plan?.ready == true,
              Date().timeIntervalSince(lastAsked) >= 20 * 60, !Coach.lowBattery else { return }
        lastAsked = Date()
        asking = true
        let minutes = Int((act.spans.last?.secs ?? 0) / 60)
        let now: [String: Any] = [
            "app": act.app, "title": act.title, "minutes": minutes, "focus": model.saved.focus,
            "today": act.rows(focus: focusWords).prefix(12).map { ["app": $0.app, "title": $0.title, "minutes": Int($0.secs / 60)] },
        ]
        guard let json = try? JSONSerialization.data(withJSONObject: now), let arg = String(data: json, encoding: .utf8) else { asking = false; return }
        model.engine.json(["coach", "--now", arg], timeout: 120) { [weak self] obj in
            guard let self else { return }
            self.asking = false
            self.fromModel = Coach.nudge(from: obj).map { [$0] } ?? []
            self.evaluate()
        }
    }

    /// {"say", "why", "kind": drift|owed|repeat|pattern|none, "confidence": 1-5}. An empty `say` is nothing to say.
    static func nudge(from obj: [String: Any]?) -> Nudge? {
        guard let obj, let say = (obj["say"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines), !say.isEmpty,
              let kind = obj["kind"] as? String, kind != "none", (obj["confidence"] as? Int ?? 3) >= 2 else { return nil }
        let local = ["drift": "drift", "owed": "promise", "repeat": "before", "pattern": "again"][kind] ?? "model"
        return Nudge(id: "model:" + say, kind: local, text: say.lowercased(), detail: (obj["why"] as? String ?? "").lowercased())
    }
}

enum Files {
    static func append(_ data: Data, to url: URL) {
        if !FileManager.default.fileExists(atPath: url.path) { FileManager.default.createFile(atPath: url.path, contents: nil) }
        if let h = try? FileHandle(forWritingTo: url) {
            h.seekToEndOfFile()
            h.write(data + Data([0x0A]))
            try? h.close()
        }
    }
}
