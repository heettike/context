import Foundation

/// What one engine command came back with: its JSON object, or one plain sentence saying why there is none.
enum EngineReply {
    case object([String: Any])
    case failed(String)
}

/// One run of `python3 -m ctx <args>` for the chat. It always ends, exactly once, on the main thread:
/// with the object the engine printed, or with a sentence. It never waits on a pipe that will not close,
/// so a hung model call, a traceback, plain text or no output at all cannot leave a question waiting.
final class EngineCall: @unchecked Sendable {
    private let p: Process
    private let out = Pipe(), err = Pipe()
    private let lock = NSLock()
    private var outData = Data(), errData = Data()
    private var settled = false
    private let timeout: TimeInterval
    private let done: (EngineReply) -> Void

    static let missing = "the reading half of context is missing, so nothing was read. keep the app inside the folder it came in, then try again."

    @discardableResult
    static func start(repo: URL?, args: [String], timeout: TimeInterval, done: @escaping (EngineReply) -> Void) -> EngineCall? {
        guard let repo else {
            DispatchQueue.main.async { done(.failed(missing)) }
            return nil
        }
        let c = EngineCall(Engine.python(args, repo: repo), timeout, done)
        c.launch()
        return c
    }

    private init(_ p: Process, _ timeout: TimeInterval, _ done: @escaping (EngineReply) -> Void) {
        self.p = p
        self.timeout = timeout
        self.done = done
    }

    private func launch() {
        p.standardInput = FileHandle.nullDevice        // nothing it starts can sit waiting for a key
        p.standardOutput = out
        p.standardError = err
        out.fileHandleForReading.readabilityHandler = { h in
            let d = h.availableData
            if d.isEmpty { h.readabilityHandler = nil; return }
            self.lock.lock(); if self.outData.count < 8 << 20 { self.outData.append(d) }; self.lock.unlock()
        }
        err.fileHandleForReading.readabilityHandler = { h in       // read, so a chatty engine never blocks on a full pipe
            let d = h.availableData
            if d.isEmpty { h.readabilityHandler = nil; return }
            self.lock.lock(); if self.errData.count < 16_000 { self.errData.append(d) }; self.lock.unlock()
        }
        p.terminationHandler = { _ in
            // a moment for the last of the output to arrive, then end whether or not the pipe has closed
            DispatchQueue.global(qos: .userInitiated).asyncAfter(deadline: .now() + 0.1) { self.finish(timedOut: false) }
        }
        do {
            try p.run()
        } catch {
            settle(.failed("python3 did not start on this mac, so nothing was read. try again."))
            return
        }
        DispatchQueue.global(qos: .userInitiated).asyncAfter(deadline: .now() + timeout) {
            guard !self.isSettled else { return }
            self.p.terminate()
            self.finish(timedOut: true)
            DispatchQueue.global().asyncAfter(deadline: .now() + 2) { if self.p.isRunning { kill(self.p.processIdentifier, SIGKILL) } }
        }
    }

    private var isSettled: Bool { lock.lock(); defer { lock.unlock() }; return settled }

    /// Stops it. Nothing is reported after this.
    func cancel() {
        lock.lock(); let was = settled; settled = true; lock.unlock()
        guard !was else { return }
        out.fileHandleForReading.readabilityHandler = nil
        err.fileHandleForReading.readabilityHandler = nil
        if p.isRunning { p.terminate() }
    }

    private func settle(_ reply: EngineReply) {
        lock.lock(); let was = settled; settled = true; lock.unlock()
        guard !was else { return }
        out.fileHandleForReading.readabilityHandler = nil
        err.fileHandleForReading.readabilityHandler = nil
        DispatchQueue.main.async { self.done(reply) }
    }

    private func finish(timedOut: Bool) {
        guard !isSettled else { return }
        out.fileHandleForReading.readabilityHandler = nil
        err.fileHandleForReading.readabilityHandler = nil
        let restOut = EngineCall.drain(out.fileHandleForReading), restErr = EngineCall.drain(err.fileHandleForReading)
        lock.lock()
        outData.append(restOut)
        errData.append(restErr)
        let o = outData, e = String(decoding: errData, as: UTF8.self).lowercased()
        lock.unlock()
        if let obj = EngineCall.parse(o) { settle(.object(obj)); return }
        let code: Int32 = p.isRunning ? -1 : p.terminationStatus
        settle(.failed(EngineCall.sentence(timedOut: timedOut, seconds: Int(timeout), code: code, stderr: e, hadOutput: !o.isEmpty)))
    }

    /// Whatever is left in a pipe, without waiting for more.
    static func drain(_ h: FileHandle) -> Data {
        let fd = h.fileDescriptor
        _ = fcntl(fd, F_SETFL, fcntl(fd, F_GETFL) | O_NONBLOCK)
        var all = Data()
        var buf = [UInt8](repeating: 0, count: 1 << 16)
        while true {
            let n = read(fd, &buf, buf.count)
            if n <= 0 { break }
            all.append(buf, count: n)
        }
        return all
    }

    /// The JSON object in the output: all of it, or the last line that is one, or the outermost braces.
    /// Warnings before it, a note after it and indented output all still parse.
    static func parse(_ data: Data) -> [String: Any]? {
        func object(_ d: Data) -> [String: Any]? { (try? JSONSerialization.jsonObject(with: d)) as? [String: Any] }
        if data.isEmpty { return nil }
        if let o = object(data) { return o }
        let text = String(decoding: data, as: UTF8.self)
        for line in text.split(whereSeparator: \.isNewline).reversed() {
            let t = line.trimmingCharacters(in: .whitespaces)
            if t.hasPrefix("{"), let o = object(Data(t.utf8)) { return o }
        }
        if let a = text.firstIndex(of: "{"), let b = text.lastIndex(of: "}"), a < b, let o = object(Data(text[a...b].utf8)) { return o }
        return nil
    }

    static func sentence(timedOut: Bool, seconds: Int, code: Int32, stderr: String, hadOutput: Bool) -> String {
        if timedOut { return "that took more than \(seconds) seconds, so context stopped reading. try again." }
        if code == 127 || (stderr.contains("python3") && stderr.contains("no such file")) {
            return "python3 was not found on this mac, so nothing was read. install it, then try again."
        }
        if stderr.contains("no module named") { return missing }
        if hadOutput { return "the reply could not be read. try again." }
        return "the reading half stopped before it answered. try again."
    }
}

// MARK: an answer, taken apart for the page

/// A piece of an answer: words, or a pointer to one of the rows it rests on (1-based).
enum Piece: Equatable {
    case text(String)
    case cite(Int)
}

/// One paragraph or list line of an answer.
struct Block: Identifiable, Equatable {
    let id: Int
    var lead = false        // the first sentence, when it is short enough to stand alone
    var bullet = false
    var pieces: [Piece]

    /// The words, each with the markers that follow it, ready to be set like a line of type.
    var words: [(word: String, cites: [Int])] {
        var out: [(word: String, cites: [Int])] = []
        for p in pieces {
            switch p {
            case .text(var t):
                // "them [1]." reads "them.¹": punctuation straight after a marker belongs to the word before it
                if let last = out.last, !last.cites.isEmpty {
                    let lead = t.prefix { ".,;:!?)]\u{2019}\u{201D}\"'".contains($0) }
                    if !lead.isEmpty { out[out.count - 1].word += lead; t = String(t.dropFirst(lead.count)) }
                }
                out += t.split(whereSeparator: \.isWhitespace).map { (String($0), []) }
            case .cite(let n): if out.isEmpty { out.append(("", [n])) } else { out[out.count - 1].cites.append(n) }
            }
        }
        return out
    }

    var hasCites: Bool { pieces.contains { if case .cite = $0 { return true } else { return false } } }
    var hasLinks: Bool { plain.contains("http://") || plain.contains("https://") }
    var plain: String { pieces.compactMap { if case .text(let t) = $0 { return t } else { return nil } }.joined() }
}

extension Answer {
    private static let address = try! NSRegularExpression(pattern: #"https?://[^\s<>\"']+"#, options: [.caseInsensitive])

    /// Lower case, as the app speaks, but an address keeps its capitals: a video id in the wrong case is another video.
    static func lower(_ s: String) -> String {
        var out = "", at = s.startIndex
        for m in address.matches(in: s, range: NSRange(s.startIndex..., in: s)) {
            guard let r = Range(m.range, in: s) else { continue }
            out += s[at..<r.lowerBound].lowercased() + s[r]
            at = r.upperBound
        }
        return out + s[at...].lowercased()
    }

    /// What the pointer over "quick" says: it follows the switch for the longer look (settings, what context does on its own).
    static func quickHelp(lookDeeper: Bool) -> String {
        lookDeeper ? "quick: answers from the first search, and looks deeper by itself when the answer is weak."
                   : "quick: answers from the first search. it does not look deeper by itself: that is switched off in settings."
    }

    /// An http or https address, or nil. Nothing else is ever opened.
    static func web(_ s: String) -> URL? {
        guard let u = URL(string: s), let scheme = u.scheme?.lowercased(), scheme == "http" || scheme == "https", u.host != nil else { return nil }
        return u
    }

    /// A word of an answer that is an address: the address, and any full stop or bracket stuck to its end.
    static func link(in word: String) -> (url: URL, tail: String)? {
        let w = word.hasPrefix("(") ? String(word.dropFirst()) : word
        guard w.lowercased().hasPrefix("http://") || w.lowercased().hasPrefix("https://") else { return nil }
        var core = w, tail = ""
        while let last = core.last, ".,;:!?)]\"'".contains(last) { tail = String(last) + tail; core.removeLast() }
        guard let u = web(core) else { return nil }
        return (u, tail)
    }

    /// An address cut in the middle so both ends can be read: "youtube.com/watch…v=abc123".
    static func short(_ url: String, max: Int = 44) -> String {
        var s = url
        for p in ["https://", "http://", "www."] where s.lowercased().hasPrefix(p) { s = String(s.dropFirst(p.count)) }
        if s.hasSuffix("/") { s.removeLast() }
        guard s.count > max else { return s }
        let head = (max - 1) * 3 / 5, tail = max - 1 - head
        return s.prefix(head) + "…" + s.suffix(tail)
    }

    private static let marker = try! NSRegularExpression(pattern: #"\s*\[(\d{1,2})\]"#)

    /// The text without its `[n]` markers.
    static func strip(_ s: String) -> String {
        marker.stringByReplacingMatches(in: s, range: NSRange(s.startIndex..., in: s), withTemplate: "")
    }

    /// An answer that is only a sentence saying what went wrong.
    static func failure(_ sentence: String) -> Answer {
        Answer(["error": sentence], tag: "x") ?? Answer(["error": "something went wrong. try again."], tag: "x")!
    }

    /// Every reply becomes something to show: the answer, or a plain sentence. Nothing is dropped.
    static func from(_ reply: EngineReply, tag: String) -> Answer {
        switch reply {
        case .failed(let why): return failure(why)
        case .object(let d):
            guard let a = Answer(d, tag: tag) else { return failure("it came back with nothing to say. try again.") }
            return a.text.isEmpty ? failure(plain(a.error)) : a
        }
    }

    /// A lens reply as a turn: its summary is the answer, the rows its items rest on are the sources.
    static func from(lens reply: EngineReply, title: String, tag: String) -> (Answer, [LensItem]) {
        switch reply {
        case .failed(let why): return (failure(why), [])
        case .object(let d):
            guard let r = LensResult(d, title: title, tag: tag) else { return (failure("it came back with nothing to say. try again."), []) }
            if !r.error.isEmpty, r.items.isEmpty, r.summary.isEmpty { return (failure(plain(r.error)), []) }
            let n = r.items.count
            let said = r.summary.isEmpty ? (n == 0 ? "nothing found this time." : "\(n) found.") : r.summary
            guard var a = Answer(["answer": said, "searched": r.searched], tag: tag) else { return (failure("it came back with nothing to say. try again."), []) }
            a.cites = r.items.compactMap(\.cite)
            return (a, r.items)
        }
    }

    /// The engine's own error, unless it is an exception's text, which means nothing to the person reading.
    static func plain(_ error: String) -> String {
        let e = error.trimmingCharacters(in: .whitespacesAndNewlines)
        let technical = ["traceback", "errno", "exception", "expecting value", "line 1 column", "keyerror", "typeerror", "nonetype", "{", "\\"]
        if e.isEmpty || technical.contains(where: e.contains) { return "the model's reply could not be read. try again." }
        return e.hasSuffix(".") || e.hasSuffix("?") || e.hasSuffix("!") ? e : e + "."
    }

    /// Splits text and markers. A marker that points past the list of rows is dropped.
    static func pieces(_ s: String, cites: Int) -> [Piece] {
        var out: [Piece] = []
        var at = s.startIndex
        for m in marker.matches(in: s, range: NSRange(s.startIndex..., in: s)) {
            guard let whole = Range(m.range, in: s), let num = Range(m.range(at: 1), in: s) else { continue }
            if whole.lowerBound > at { out.append(.text(String(s[at..<whole.lowerBound]))) }
            if let n = Int(s[num]), n >= 1, n <= cites { out.append(.cite(n)) }
            at = whole.upperBound
            if at < s.endIndex, !s[at].isWhitespace, !s[at].isPunctuation, s[at] != "[" { out.append(.text(" ")) }
        }
        if at < s.endIndex { out.append(.text(String(s[at...]))) }
        return out
    }

    /// Sentences, each keeping the markers that follow its full stop. "17.2" and "v1.4" are not ends.
    static func sentences(_ line: String) -> [String] {
        let c = Array(line)
        var out: [String] = [], cur = ""
        var i = 0
        func flush() {
            let t = cur.trimmingCharacters(in: .whitespaces)
            if !t.isEmpty { out.append(t) }
            cur = ""
        }
        while i < c.count {
            let ch = c[i]
            cur.append(ch)
            i += 1
            guard ch == "." || ch == "?" || ch == "!" else { continue }
            if let w = cur.split(separator: " ").last, w.lowercased().contains("://"), i < c.count, c[i] != " " { continue }    // inside an address
            var j = i
            while true {                                  // markers straight after the stop belong to this sentence
                var k = j
                while k < c.count, c[k] == " " { k += 1 }
                guard k < c.count, c[k] == "[", let close = c[k...].firstIndex(of: "]"), close > k + 1, close - k <= 3,
                      c[(k + 1)..<close].allSatisfy(\.isNumber) else { break }
                cur.append(contentsOf: c[j...close])
                j = close + 1
            }
            if j > i || j == c.count || c[j] == " " { i = j; flush() }
        }
        flush()
        return out
    }

    /// The answer as short blocks: the first sentence alone, then two sentences at a time; list lines stay lines.
    var blocks: [Block] {
        var out: [Block] = []
        var prose: [String] = []
        func add(_ s: String, lead: Bool = false, bullet: Bool = false) {
            let p = Answer.pieces(s, cites: cites.count)
            if !p.isEmpty { out.append(Block(id: out.count, lead: lead, bullet: bullet, pieces: p)) }
        }
        func flush() {
            guard !prose.isEmpty else { return }
            var rest = prose[...]
            if out.isEmpty, let first = rest.first, prose.count > 1, Answer.strip(first).count <= 150 {
                add(first, lead: true)
                rest = rest.dropFirst()
            }
            var i = rest.startIndex
            while i < rest.endIndex {
                add(rest[i..<min(i + 2, rest.endIndex)].joined(separator: " "))
                i += 2
            }
            prose = []
        }
        for raw in text.split(whereSeparator: \.isNewline) {
            let line = raw.trimmingCharacters(in: .whitespaces)
            if line.isEmpty { continue }
            if let mark = ["- ", "• ", "* ", "– "].first(where: line.hasPrefix) {
                flush()
                add(String(line.dropFirst(mark.count)), bullet: true)
            } else {
                prose += Answer.sentences(line)
            }
        }
        flush()
        return out
    }
}
