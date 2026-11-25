import Foundation

/// The engine kept warm: `python3 -u -m ctx serve`, one process for the life of the app, spoken to in JSON lines.
/// Started on first use, started again if it dies, closed when the app quits. Each request has an id; every line that
/// comes back carries it.
final class Warm {
    private struct Waiting { let event: ([String: Any]) -> Void; let end: () -> Void; let open: Bool }
    private let repo: URL
    private var process: Process?
    private var input: FileHandle?
    private var waiting: [Int: Waiting] = [:]
    private var nextID = 0
    private var buffer = Data()
    private let lock = NSLock()

    init(repo: URL) { self.repo = repo }

    private func start() -> Bool {
        if process?.isRunning == true { return true }
        let p = Engine.python(["serve"], repo: repo)
        let inPipe = Pipe(), out = Pipe()
        p.standardInput = inPipe
        p.standardOutput = out
        p.standardError = FileHandle.nullDevice
        out.fileHandleForReading.readabilityHandler = { [weak self] h in
            let d = h.availableData
            guard let self, !d.isEmpty else { return }
            self.lock.lock()
            self.buffer.append(d)
            var lines: [Data] = []
            while let nl = self.buffer.firstIndex(of: 0x0A) {
                lines.append(self.buffer[self.buffer.startIndex..<nl])
                self.buffer.removeSubrange(self.buffer.startIndex...nl)
            }
            self.lock.unlock()
            let objects = lines.compactMap { (try? JSONSerialization.jsonObject(with: $0)) as? [String: Any] }
            DispatchQueue.main.async { objects.forEach(self.take) }
        }
        p.terminationHandler = { [weak self] _ in
            out.fileHandleForReading.readabilityHandler = nil
            DispatchQueue.main.async {
                guard let self, self.process === p else { return }
                // it died: everything in flight ends now, and the next request starts a new one
                self.process = nil
                self.input = nil
                let all = self.waiting
                self.waiting = [:]
                all.values.forEach { $0.end() }
            }
        }
        do { try p.run() } catch { return false }
        process = p
        input = inPipe.fileHandleForWriting
        return true
    }

    private func take(_ d: [String: Any]) {
        guard let id = d["id"] as? Int, let w = waiting[id] else { return }
        w.event(d)
        // a plain request ends with its result; a stream is ended by whoever reads it, since more may follow a first "done"
        // the engine's own last line for a request is {"end": true}: after it nothing more comes for that id
        let over = d["end"] != nil || d["result"] != nil || d["error"] != nil || d["cancelled"] != nil || (!w.open && d["done"] != nil)
        if over { waiting[id] = nil; w.end() }
    }

    /// Sends one request. `open`: the caller decides when it is over (finish). Returns its id, or nil if the engine would not start.
    @discardableResult
    func send(_ request: [String: Any], open: Bool = false, event: @escaping ([String: Any]) -> Void, end: @escaping () -> Void) -> Int? {
        guard start(), let input else { end(); return nil }
        nextID += 1
        var r = request
        r["id"] = nextID
        guard var line = try? JSONSerialization.data(withJSONObject: r) else { end(); return nil }
        line.append(0x0A)
        waiting[nextID] = Waiting(event: event, end: end, open: open)
        do { try input.write(contentsOf: line) } catch { waiting[nextID] = nil; end(); return nil }
        return nextID
    }

    func finish(_ id: Int) { if let w = waiting.removeValue(forKey: id) { w.end() } }

    func cancel(_ id: Int) {
        guard waiting[id] != nil, let input, var line = try? JSONSerialization.data(withJSONObject: ["id": -id, "cmd": "cancel", "target": id]) else { return }
        line.append(0x0A)
        try? input.write(contentsOf: line)
    }

    /// Closing its input ends the process.
    func stop() {
        try? input?.close()
        input = nil
        process = nil
    }

    /// The one-shot command lines the app used to run, as requests. nil: this one still starts its own python.
    static func request(_ a: [String]) -> [String: Any]? {
        func after(_ flag: String) -> String? { a.firstIndex(of: flag).flatMap { $0 + 1 < a.count ? a[$0 + 1] : nil } }
        switch a.first {
        case "settings":
            if let kv = after("--set") { return ["cmd": "settings", "set": kv] }
            return a.contains("--fast") ? ["cmd": "settings", "fast": true] : (a.count == 1 ? ["cmd": "settings"] : nil)
        case "facts": return a.count == 1 ? ["cmd": "facts"] : nil
        case "models": return a.contains("--bench") ? nil : ["cmd": "models", "refresh": a.contains("--refresh")]
        case "mcp": return a == ["mcp", "--status"] ? ["cmd": "mcp-status"] : nil
        case "thread":
            guard a.count > 1 else { return nil }
            let n = Int(after("--around") ?? "") ?? 15
            return ["cmd": "thread", "msg": a[1], "before": n, "after": n]
        case "today":
            if let id = after("--done") { return ["cmd": "today", "done": id] }
            if let id = after("--dismiss") { return ["cmd": "today", "dismiss": id] }
            return ["cmd": "today", "cached": a.contains("--cached")]
        case "rate":
            guard let q = after("--question"), let id = after("--id") else { return nil }
            return ["cmd": "rate", "question": q, "row": id, "ok": a.contains("--yes"), "kind": after("--kind") ?? "answer"]
        default: return nil
        }
    }
}

final class EngineClient {
    /// Something in flight that can be stopped.
    final class Handle {
        fileprivate var process: Process?
        fileprivate var id: Int?
        fileprivate weak var warm: Warm?
        func cancel() {
            if process?.isRunning == true { process?.terminate() }
            process = nil
            if let id { warm?.cancel(id); warm?.finish(id) }
            id = nil
        }
        /// For a stream the reader ends: nothing more is expected.
        func finish() { if let id { warm?.finish(id) }; id = nil }
    }

    private weak var engine: Engine?
    private var warm: Warm?
    init(_ engine: Engine) { self.engine = engine }

    /// The warm engine, unless this is a render or a test: those start nothing.
    private var live: Warm? {
        guard !Engine.debug, let repo = engine?.repo else { return nil }
        if warm == nil { warm = Warm(repo: repo) }
        return warm
    }

    func quit() { warm?.stop() }

    /// The warm engine for a call that has no one-shot form. nil in a render or a test.
    var warmEngine: Warm? { live }

    /// A one-shot command line answered by the warm engine instead, when it is one the warm engine knows.
    /// True when it took the call. The reply has the shape the one-shot printed: an object, or a list under "list".
    func tryWarm(_ args: [String], timeout: TimeInterval, done: @escaping ([String: Any]?) -> Void) -> Bool {
        guard let req = Warm.request(args), let w = live else { return false }
        var result: [String: Any]?
        var answered = false
        let id = w.send(req, event: { d in
            if let r = d["result"] as? [String: Any] { result = r } else if let l = d["result"] as? [Any] { result = ["list": l] }
        }, end: { if !answered { answered = true; done(result) } })
        if let id { DispatchQueue.main.asyncAfter(deadline: .now() + timeout) { [weak w] in w?.cancel(id); w?.finish(id) } }
        return true
    }

    /// One reply: the last JSON object the command prints, or nil.
    @discardableResult
    func request(_ args: [String], timeout: TimeInterval = 30, done: @escaping ([String: Any]?) -> Void) -> Handle {
        let h = Handle()
        guard let engine else { done(nil); return h }
        h.process = engine.json(args, timeout: timeout, done: done)
        return h
    }

    /// Many events, then the end: one JSON object per line as the engine prints them.
    func events(_ args: [String], event: @escaping ([String: Any]) -> Void, done: @escaping () -> Void) -> Handle? {
        guard let engine else { return nil }
        let h = Handle()
        h.process = engine.stream(args, line: { line in
            guard line.hasPrefix("{"), let d = (try? JSONSerialization.jsonObject(with: Data(line.utf8))) as? [String: Any] else { return }
            event(d)
        }, done: done)
        return h.process == nil ? nil : h
    }

    // MARK: the calls

    /// An answer, told as it happens: {"phase"}, {"delta"}, {"cite"}, then {"done": reply} or {"error"}.
    /// The stream stays open after the first "done": a deeper search may follow. The reader calls finish() on the handle.
    /// `scope` and `deep` go with the request to the warm engine: {"scope": {"sources":[…],"after":…,"before":…,"people":[…]}, "deep": true}.
    func answer(_ question: String, history: String, scope: Scope = Scope(), deep: Bool = false, dig: Bool = true, model: String = "", event: @escaping ([String: Any]) -> Void, done: @escaping () -> Void) -> Handle? {
        if let w = live {
            let past = (try? JSONSerialization.jsonObject(with: Data(history.utf8))) ?? []
            let h = Handle()
            h.warm = w
            var req: [String: Any] = ["cmd": "answer", "q": question, "history": past, "stream": true]
            // serve reads the scope as keys of the request itself; the object is sent too, for a reader that wants it whole
            if !scope.isAll { req["scope"] = scope.json; for (k, v) in scope.json where !(v is NSNull) { req[k] = v } }
            if deep { req["deep"] = true } else if !dig { req["deep"] = false }      // false: the engine never looks longer by itself
            if !model.isEmpty { req["model"] = model }
            h.id = w.send(req, open: true, event: event, end: done)
            return h.id == nil ? nil : h
        }
        return events(["answer", question, "--history", history, "--stream"], event: event, done: done)
    }

    /// One message in its conversation. No model.
    @discardableResult
    func thread(_ id: String, around: Int = 10, done: @escaping ([String: Any]?) -> Void) -> Handle {
        request(["thread", id, "--around", "\(around)", "--json"], timeout: 15, done: done)
    }

    /// The card for this morning, or none. `cached` never makes one: it only reads what the daily run left.
    @discardableResult
    func today(cached: Bool = true, done: @escaping ([String: Any]?) -> Void) -> Handle {
        request(["today", "--json"] + (cached ? ["--cached"] : []), timeout: cached ? 15 : 120, done: done)
    }

    func today(mark id: String, done isDone: Bool, then: @escaping ([String: Any]?) -> Void = { _ in }) {
        request(["today", isDone ? "--done" : "--dismiss", id], timeout: 15, done: then)
    }

    /// The owner said a row was right or wrong for a question. Kept on this mac; later searches use it.
    func rate(question: String, id: String, yes: Bool, kind: String) {
        request(["rate", "--question", question, "--id", id, yes ? "--yes" : "--no", "--kind", kind], timeout: 15) { _ in }
    }
}
