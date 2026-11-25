import AppKit
import Foundation
import Observation

struct Hit: Identifiable, Equatable {
    let id: String
    let src: String
    let kind: String      // message, doc, session, prompt
    let ts: String
    let thread: String
    let threadID: String
    let who: String
    let sender: String
    let text: String
    let url: String
    let offset: Int
    var snippet: String = ""
}

struct HitGroup: Identifiable, Equatable {
    let src: String
    let total: Int
    let more: Bool
    let hits: [Hit]
    var id: String { src }
}

final class Flag: @unchecked Sendable {
    private var on = false
    private let lock = NSLock()
    func set() { lock.lock(); on = true; lock.unlock() }
    var isSet: Bool { lock.lock(); defer { lock.unlock() }; return on }
}

/// Streaming reads over the jsonl files. Nothing here holds a whole file in memory, and nothing maps one:
/// the collector truncates these files in place, and a mapped page past the new end would crash the app.
enum Jsonl {
    static let files = [("messages.jsonl", "message"), ("docs.jsonl", "doc"), ("sessions.jsonl", "session"), ("prompts.jsonl", "prompt")]

    /// Calls `body(line, offset)` for each line that starts in [from, to).
    static func lines(path: String, from: Int, to: Int, stop: Flag?, body: (UnsafeBufferPointer<UInt8>, Int) -> Void) {
        let fd = open(path, O_RDONLY)
        guard fd >= 0 else { return }
        defer { close(fd) }
        var cap = 1 << 20
        var buf = UnsafeMutablePointer<UInt8>.allocate(capacity: cap)
        defer { buf.deallocate() }
        var filePos = max(0, from - 1)   // start one byte early so a line that begins exactly at `from` is ours
        var fill = 0
        var bufStart = filePos           // file offset of buf[0]
        var skipFirst = from > 0
        while true {
            if stop?.isSet == true { return }
            if fill == cap {             // one line longer than the buffer
                let bigger = UnsafeMutablePointer<UInt8>.allocate(capacity: cap * 2)
                bigger.update(from: buf, count: fill)
                buf.deallocate()
                buf = bigger
                cap *= 2
            }
            let got = pread(fd, buf + fill, cap - fill, off_t(filePos))
            if got <= 0 { return }
            filePos += got
            fill += got
            var start = 0
            while start < fill, let nl = memchr(buf + start, 0x0A, fill - start) {
                let end = buf.distance(to: nl.assumingMemoryBound(to: UInt8.self))
                if skipFirst {
                    skipFirst = false
                } else {
                    let off = bufStart + start
                    if off >= to { return }
                    body(UnsafeBufferPointer(start: buf + start, count: end - start), off)
                }
                start = end + 1
            }
            if start > 0 {
                memmove(buf, buf + start, fill - start)
                fill -= start
                bufStart += start
            }
        }
    }

    @inline(__always)
    static func contains(_ hay: UnsafeBufferPointer<UInt8>, _ needle: UnsafeBufferPointer<UInt8>) -> Bool {
        let n = needle.count, h = hay.count
        if n == 0 { return true }
        if h < n { return false }
        let first = needle[0]
        var i = 0
        let last = h - n
        while i <= last {
            var c = hay[i]
            if c &- 65 < 26 { c |= 0x20 }
            if c == first {
                var j = 1
                while j < n {
                    var d = hay[i + j]
                    if d &- 65 < 26 { d |= 0x20 }
                    if d != needle[j] { break }
                    j += 1
                }
                if j == n { return true }
            }
            i += 1
        }
        return false
    }

    /// Offsets and lengths of the lines that contain every needle (ASCII case-insensitive), in file order.
    static func candidates(path: String, needles: [[UInt8]], stop: Flag?) -> [(Int, Int)] {
        var st = stat()
        guard stat(path, &st) == 0, st.st_size > 0 else { return [] }
        let size = Int(st.st_size)
        let parts = max(1, min(ProcessInfo.processInfo.activeProcessorCount, size / (2 << 20)))
        let step = size / parts + 1
        var found = [[(Int, Int)]](repeating: [], count: parts)
        let lock = NSLock()
        DispatchQueue.concurrentPerform(iterations: parts) { k in
            var mine: [(Int, Int)] = []
            let ptrs = needles.map { n -> UnsafeMutableBufferPointer<UInt8> in
                let p = UnsafeMutableBufferPointer<UInt8>.allocate(capacity: n.count)
                _ = p.initialize(from: n)
                return p
            }
            defer { ptrs.forEach { $0.deallocate() } }
            lines(path: path, from: k * step, to: min(size, (k + 1) * step), stop: stop) { line, off in
                for p in ptrs where !contains(line, UnsafeBufferPointer(p)) { return }
                mine.append((off, line.count))
            }
            lock.lock(); found[k] = mine; lock.unlock()
        }
        return found.flatMap { $0 }
    }

    static func read(fd: Int32, _ at: (Int, Int)) -> [String: Any]? {
        var buf = [UInt8](repeating: 0, count: at.1)
        guard pread(fd, &buf, at.1, off_t(at.0)) == at.1 else { return nil }
        return (try? JSONSerialization.jsonObject(with: Data(buf))) as? [String: Any]
    }

    static func hit(_ d: [String: Any], kind: String, offset: Int) -> Hit? {
        guard let id = d["id"] as? String, let src = d["src"] as? String else { return nil }
        func s(_ k: String) -> String { d[k] as? String ?? "" }
        var thread = s("thread"), text = s("text"), ts = s("ts")
        switch kind {
        case "doc": thread = s("title")
        case "session":
            thread = s("title").isEmpty ? (s("project") as NSString).lastPathComponent : s("title")
            text = [s("first_user"), s("last_agent")].filter { !$0.isEmpty }.joined(separator: "\n\n")
            ts = s("last_agent_ts")
        default: break
        }
        return Hit(id: "\(kind):\(id)", src: src, kind: kind, ts: ts, thread: thread, threadID: s("thread_id"),
                   who: s("who"), sender: s("sender"), text: text, url: s("url"), offset: offset)
    }

    /// A short window of text around the first word that matched.
    static func snippet(_ text: String, words: [String]) -> String {
        let flat = text.replacingOccurrences(of: "\n", with: " ")
        var at = flat.startIndex
        for w in words {
            if let r = flat.range(of: w, options: .caseInsensitive) { at = r.lowerBound; break }
        }
        let lead = flat.distance(from: flat.startIndex, to: at)
        let start = flat.index(at, offsetBy: -min(lead, 48))
        let end = flat.index(start, offsetBy: 220, limitedBy: flat.endIndex) ?? flat.endIndex
        return (start > flat.startIndex ? "…" : "") + flat[start..<end].trimmingCharacters(in: .whitespaces)
    }

    static func search(home: URL, query: String, perGroup: Int = 30, stop: Flag) -> [HitGroup] {
        let words = AskModel.terms(query)
        guard !words.isEmpty else { return [] }
        let needles = words.map { Array($0.utf8) }
        var bySrc: [String: [Hit]] = [:]
        var capped: Set<String> = []
        for (name, kind) in files {
            if stop.isSet { return [] }
            let path = home.appendingPathComponent(name).path
            var cands = candidates(path: path, needles: needles, stop: stop)
            // A word like "text" sits in every line as a key. Check the newest few thousand in full and say so.
            let limit = 4000
            let over = cands.count > limit
            if over { cands = Array(cands.suffix(limit)) }
            let fd = open(path, O_RDONLY)
            guard fd >= 0 else { continue }
            defer { close(fd) }
            for c in cands {
                if stop.isSet { return [] }
                guard let d = read(fd: fd, c), var h = hit(d, kind: kind, offset: c.0) else { continue }
                // whole words only: "talk" is not in "talking", "link" is not in "linkedin"
                let hay = Set((h.thread + "\n" + h.sender + "\n" + h.text).lowercased().split { !($0.isLetter || $0.isNumber) })
                guard words.allSatisfy({ hay.contains(Substring($0)) }) else { continue }
                h.snippet = snippet(h.text.isEmpty ? h.thread : h.text, words: words)
                bySrc[h.src, default: []].append(h)
                if over { capped.insert(h.src) }
            }
        }
        return bySrc.map { src, hits in
            // what the owner wrote themselves comes first, then newest
            let sorted = hits.sorted { ($0.who == "me") != ($1.who == "me") ? $0.who == "me" : $0.ts > $1.ts }
            return HitGroup(src: src, total: hits.count, more: capped.contains(src), hits: Array(sorted.prefix(perGroup)))
        }.sorted { a, b in
            let am = a.hits.contains { $0.who == "me" }, bm = b.hits.contains { $0.who == "me" }
            return am != bm ? am : (a.hits.map(\.ts).max() ?? "") > (b.hits.map(\.ts).max() ?? "")
        }
    }

    /// The messages around a hit, in the same thread.
    static func thread(home: URL, hit: Hit, around: Int = 14) -> [Hit] {
        guard hit.kind == "message", !hit.threadID.isEmpty else { return [hit] }
        let esc = hit.threadID.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\"", with: "\\\"")
        let path = home.appendingPathComponent("messages.jsonl").path
        let cands = candidates(path: path, needles: [Array("\"thread_id\": \"\(esc.lowercased())\"".utf8)], stop: nil)
        guard let i = cands.firstIndex(where: { $0.0 == hit.offset }) else { return [hit] }
        let fd = open(path, O_RDONLY)
        guard fd >= 0 else { return [hit] }
        defer { close(fd) }
        return cands[max(0, i - around)...min(cands.count - 1, i + around)].compactMap { c in
            read(fd: fd, c).flatMap { self.hit($0, kind: "message", offset: c.0) }
        }.filter { $0.threadID == hit.threadID }
    }

    // MARK: dates

    private static let tsKey = Array("\"ts\": \"".utf8)
    private static let agentKey = Array("\"last_agent_ts\": \"".utf8)
    private static let srcKey = Array("\"src\": \"".utf8)

    static func value(after key: [UInt8], in line: UnsafeBufferPointer<UInt8>, max: Int) -> String? {
        guard let base = line.baseAddress, line.count > key.count,
              let p = key.withUnsafeBufferPointer({ memmem(base, line.count, $0.baseAddress, key.count) }) else { return nil }
        let start = base.distance(to: p.assumingMemoryBound(to: UInt8.self)) + key.count
        var end = start
        while end < line.count, end - start < max, line[end] != 0x22 { end += 1 }
        return end > start ? String(decoding: UnsafeBufferPointer(rebasing: line[start..<end]), as: UTF8.self) : nil
    }

    static func date(in line: UnsafeBufferPointer<UInt8>) -> String? {
        guard let d = value(after: tsKey, in: line, max: 10) ?? value(after: agentKey, in: line, max: 10),
              d.count == 10, d.first?.isNumber == true, d > "1990" else { return nil }
        return d
    }

    static func date(in slice: ArraySlice<UInt8>) -> String? {
        slice.withUnsafeBufferPointer { date(in: $0) }
    }

    /// First and last date of every source, read off the files.
    static func spans(home: URL) -> [String: DateSpan] {
        var out: [String: DateSpan] = [:]
        for name in ["messages.jsonl", "docs.jsonl", "sessions.jsonl"] {
            lines(path: home.appendingPathComponent(name).path, from: 0, to: .max, stop: nil) { line, _ in
                guard let src = value(after: srcKey, in: line, max: 40), let d = date(in: line) else { return }
                if out[src] == nil { out[src] = DateSpan(first: d, last: d) } else { out[src]?.take(d) }
            }
        }
        return out
    }
}

/// An address the answer hands over.
struct LinkRef: Identifiable, Equatable {
    let id: Int
    let url: String
    let what: String
    let ts: String
    let src: String
}

/// What the engine said when asked a question, and the rows it leaned on.
struct Answer: Equatable {
    var text: String
    var cites: [Hit]
    var searched: [String]
    var error: String
    var found = 0
    var secs = 0.0
    var links: [LinkRef] = []       // "find me the link" answers: the addresses themselves, most likely first
    var strength = ""               // strong, partial or weak: how far the rows settle the question. "" when the engine did not say
    var maybe: [Hit] = []           // rows related by meaning that the answer does not rest on
    var stopped = false             // the owner stopped it part way: what was written is kept
    var deep = false                // this is the answer a deeper search came back with
    var trail = ""                  // what the deeper search did, in a few words
    var steps: [WorkStep] = []          // what the model did on the way, in order
    var usage = Usage()
    var model = ""                  // the model that wrote it, when the engine says
    var fallback = ""               // why another model than the chosen one wrote it, when one did
    var rules: [String] = []        // the ids of their rules that shaped this answer, when any did
    var made: Made?                 // set when the answer is a thing made for them: it is shown as a document
    var draft = false               // the engine says this is something written for them to send, in their own voice

    init?(_ d: [String: Any]?, tag: String) {
        guard let d else { return nil }
        // the engine's words as it wrote them: an answer may hold names, code, addresses and tables, and none survive a change of case
        text = (d["answer"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        links = ((d["links"] as? [[String: Any]]) ?? []).enumerated().compactMap { i, l in
            guard let u = l["url"] as? String, Answer.web(u) != nil else { return nil }
            return LinkRef(id: i, url: u, what: l["what"] as? String ?? "", ts: l["ts"] as? String ?? "", src: l["src"] as? String ?? "")
        }
        error = (d["error"] as? String ?? "").lowercased()
        searched = (d["searched"] as? [String] ?? []).map { $0.lowercased() }
        found = d["found"] as? Int ?? 0
        secs = (d["secs"] as? NSNumber)?.doubleValue ?? 0
        cites = ((d["cites"] as? [[String: Any]]) ?? []).enumerated().compactMap { i, c in Answer.cite(c, i, prefix: tag) }
        strength = d["strength"] as? String ?? ""
        steps = ((d["steps"] as? [[String: Any]]) ?? []).compactMap { WorkStep($0) }
        usage = Usage(d["usage"] as? [String: Any])
        model = d["model"] as? String ?? ""
        fallback = (d["fallback"] as? String ?? "").lowercased()
        rules = d["rules"] as? [String] ?? []
        made = Made(d["made"])
        draft = d["draft"] as? Bool ?? (d["kind"] as? String == "draft")
        deep = d["deep"] as? Bool ?? false
        if deep {
            let dug = d["dug"] as? [Any] ?? []
            let threads = dug.compactMap { ($0 as? [String: Any])?["threads"] as? Int }.reduce(0, +)
            trail = "looked deeper: tried \(dug.count) way\(dug.count == 1 ? "" : "s")" + (threads > 0 ? ", read \(threads) thread\(threads == 1 ? "" : "s")" : "") + "."
        }
        maybe = ((d["maybe"] as? [[String: Any]]) ?? []).enumerated().compactMap { i, c in Answer.cite(c, i, prefix: tag + "m") }
        if text.isEmpty, error.isEmpty { return nil }
    }
}

/// An answer on its way: what the engine has said it is doing, and what has been written so far.
struct Live: Equatable {
    var phase = "plan"
    var rows = 0
    var sources: [String] = []
    var threads: [String] = []
    var text = ""
    var cites: [Hit] = []
    var steps: [WorkStep] = []

    mutating func take(_ ev: [String: Any], tag: String) {
        if let p = ev["phase"] as? String {
            phase = p
            rows = ev["rows"] as? Int ?? rows
            sources = ev["sources"] as? [String] ?? sources
            threads = (ev["threads"] as? [[String: Any]])?.compactMap { $0["thread"] as? String }.filter { !$0.isEmpty } ?? threads
        }
        if let d = ev["delta"] as? String { text += d }
        if ev["retract"] != nil { text = ""; cites = [] }
        // a step is said when it starts and again, under the same number, with what it found
        if let s = WorkStep(ev["step"] as? [String: Any]) {
            if let i = steps.firstIndex(where: { $0.n == s.n }) { steps[i] = s } else { steps.append(s) }
        }       // the model began its answer again: what was shown is put away
        if let c = ev["cite"] as? [String: Any], let h = Answer.cite(c, (c["n"] as? Int ?? cites.count + 1) - 1, prefix: tag) { cites.append(h) }
    }

    /// What it is doing, in the engine's own steps, in plain words.
    var line: String {
        guard phase == "read" else { return "planning where to look." }
        var s = "reading \(Words.count(rows)) thing\(rows == 1 ? "" : "s") from \(sources.count) source\(sources.count == 1 ? "" : "s")"
        if let t = threads.first { s += ", and your thread with \(t.lowercased())" + (threads.count > 1 ? " and \(threads.count - 1) more" : "") }
        return s + "."
    }

    /// What has been written so far, set as an answer.
    func partial(tag: String) -> Answer? {
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, var a = Answer(["answer": text], tag: tag) else { return nil }
        a.cites = cites
        return a
    }
}

extension Answer {
    /// A cited row, as the engine sends it: {"id","src","ts","thread","who","text"}.
    static func cite(_ c: [String: Any], _ i: Int, prefix: String = "cite") -> Hit? {
        let id = c["id"] as? String ?? "row\(i)"       // a row is never dropped: the markers in the answer count them in order
        let text = c["text"] as? String ?? ""
        return Hit(id: "\(prefix):\(i):\(id)", src: c["src"] as? String ?? "", kind: "cite", ts: c["ts"] as? String ?? "",
                   thread: c["thread"] as? String ?? "", threadID: "", who: c["who"] as? String ?? "", sender: c["sender"] as? String ?? c["from"] as? String ?? "",
                   text: text, url: c["url"] as? String ?? "", offset: -1,
                   snippet: String(text.split(whereSeparator: \.isWhitespace).joined(separator: " ").prefix(220)))
    }

    /// Short paragraphs for scanning: the first sentence or two stand alone, the rest go two sentences at a time.
    var paragraphs: [String] {
        var sentences: [String] = [], cur = ""
        for ch in Answer.strip(text) {
            cur.append(ch)
            if ch == "." || ch == "?" || ch == "!" || ch == "\n" {
                let t = cur.trimmingCharacters(in: .whitespacesAndNewlines)
                if t.count > 1 { sentences.append(t) }
                cur = ""
            }
        }
        let rest = cur.trimmingCharacters(in: .whitespacesAndNewlines)
        if !rest.isEmpty { sentences.append(rest) }
        guard sentences.count > 2 else { return [sentences.joined(separator: " ")].filter { !$0.isEmpty } }
        var out = [sentences[0]]
        var i = 1
        while i < sentences.count {
            out.append(sentences[i..<min(i + 2, sentences.count)].joined(separator: " "))
            i += 2
        }
        return out
    }
}

/// One exchange in the chat: what was asked, and what came back. No answer yet means it is still being read.
struct Turn: Identifiable, Equatable {
    let id: Int
    var q: String
    var answer: Answer?
    var at = Date()
    var lensID: String?             // set when the question is a ready-made one
    var items: [LensItem] = []      // what a lens found, to work down
    var rated: Bool?                // "good answer" or "not right", once the owner has said
    var dig: String?                // a deeper search is running under a weak answer: what it is doing now
    var first: Answer?              // the answer before the deeper one replaced it
    var showFirst = false           // the owner is looking at the first answer again
    var live: Live?                 // set while the answer is on its way
    var streamed = false            // the answer was written on screen as it came, so it does not arrive a second time

    init(id: Int, q: String, answer: Answer? = nil, lensID: String? = nil, items: [LensItem] = []) {
        self.id = id
        self.q = q
        self.answer = answer
        self.lensID = lensID
        self.items = items
    }
}

/// A ready-made question the engine knows how to run.
struct LensInfo: Identifiable, Equatable { let id: String; let title: String; let about: String }

struct LensItem: Identifiable, Equatable {
    let id: String
    var what: String
    var who: String
    var when: String
    var status: String      // open, done, unclear
    var cite: Hit?
}

struct LensResult: Equatable {
    var title: String
    var summary: String
    var items: [LensItem]
    var searched: [String]
    var error: String

    init?(_ d: [String: Any]?, title fallback: String, tag: String = "lens") {
        guard let d else { return nil }
        title = (d["title"] as? String ?? fallback).lowercased()
        summary = d["summary"] as? String ?? ""
        error = (d["error"] as? String ?? "").lowercased()
        searched = (d["searched"] as? [String] ?? []).map { $0.lowercased() }
        items = ((d["items"] as? [[String: Any]]) ?? []).enumerated().compactMap { i, r in
            guard let what = r["what"] as? String, !what.isEmpty else { return nil }
            let cite = (r["cite"] as? [String: Any]).flatMap { Answer.cite($0, i, prefix: tag) }
            return LensItem(id: cite?.id ?? "\(tag):item\(i)", what: what, who: r["who"] as? String ?? "",
                            when: r["when"] as? String ?? "", status: r["status"] as? String ?? "unclear", cite: cite)
        }
        if summary.isEmpty, items.isEmpty, error.isEmpty { return nil }
    }
}

/// The ask screen's state: the conversations, the one in the window, what is being read for each, and the exact-word search.
@Observable final class AskModel {
    let home: URL
    /// The exact-word field. Typing a question never looks anything up; only exact-word search, asked for by name, searches as you type.
    var query = "" { didSet { if query != oldValue { if exact { changed() } } } }
    var exact = false { didSet { if exact != oldValue { changed() } } }
    var groups: [HitGroup] = []
    var searching = false
    var selected: String?
    var opened: Hit?
    var context: [Hit] = []
    var tookMs = 0
    var asked = ""                // the question last sent
    var askedAt = Date()
    var lenses: [LensInfo] = []
    var starters: [String] = []     // questions the engine made from their profile, for the empty state
    var starterLenses: [LensInfo]?  // the lenses as the engine's starters name them; nil until it has answered

    /// One chip under the input on home.
    enum HomeChip: Equatable { case lens(LensInfo), made(String), plan
        var text: String {
            switch self {
            case .lens(let l): return l.title
            case .made(let q): return q
            case .plan: return "journal"
            }
        }
    }

    /// The chips on home, each once: the lenses as the engine's starters give them (the built-in list only when that
    /// call has not answered), then two questions drawn from their profile, then the journal. The same words never show twice,
    /// whichever list they came from.
    var homeChips: [HomeChip] {
        var out: [HomeChip] = [], said = Set<String>()
        func key(_ s: String) -> String { s.lowercased().trimmingCharacters(in: .whitespacesAndNewlines) }
        for l in starterLenses ?? lenses where said.insert(key(l.title)).inserted { out.append(.lens(l)) }
        var made = 0
        for q in starters where made < 2 && key(q) != "journal" && said.insert(key(q)).inserted { out.append(.made(q)); made += 1 }
        return out + [.plan]
    }

    /// Reads the engine's starters: [{"q", "lens": "<id>"} …, {"q", "about": …} …]. A row with a lens is that lens; the rest are their own.
    func take(starters rows: [Any]) {
        var ls: [LensInfo] = [], qs: [String] = []
        for r in rows {
            let d = r as? [String: Any]
            let q = ((r as? String) ?? d?["q"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            guard !q.isEmpty else { continue }
            if let id = d?["lens"] as? String, !id.isEmpty {
                ls.append(LensInfo(id: id, title: q.lowercased(), about: lenses.first { $0.id == id }?.about ?? ""))
            } else { qs.append(q) }
        }
        if !ls.isEmpty { starterLenses = ls }
        if !qs.isEmpty { starters = qs }
    }

    // the conversations
    var chats: [Chat] = []          // every saved conversation
    var currentID: String?          // the one in the window. nil: home, where the next question starts a new one
    var busy: Set<String> = []      // chats with an answer being read. one per chat, any number of chats at once
    var homeDraft = ""              // what is typed on home, before there is a chat to keep it
    var homeScope = Scope()
    var homeDeep = false
    var homeModel = ""
    var editing: Int?               // the turn whose question is back in the input to be changed and asked again
    var sourcesFor: Int?            // the turn whose sources are open in the panel on the right
    /// What is in flight for one chat.
    final class Run { var stream: EngineClient.Handle?; var call: EngineCall?; var token = 0 }
    @ObservationIgnored var runs: [String: Run] = [:]

    /// The conversation in the window, oldest first.
    var turns: [Turn] {
        get { current?.turns ?? [] }
        set {
            if let i = index(currentID) { chats[i].turns = newValue } else if !newValue.isEmpty {
                let id = make()
                if let i = index(id) { chats[i].turns = newValue; chats[i].title = AskModel.firstWords(newValue[0].q) }
            }
        }
    }
    /// The engine is reading for an answer in the conversation in the window.
    var asking: Bool {
        get { currentID.map(busy.contains) ?? false }
        set {
            guard let id = currentID ?? (newValue ? make() : nil) else { return }
            if newValue { busy.insert(id) } else { busy.remove(id) }
        }
    }
    var queue: [String] {
        get { current?.queue ?? [] }
        set { if let i = index(currentID) { chats[i].queue = newValue } }
    }
    /// The input. Each chat keeps its own, so a half-typed question is still there when the owner comes back.
    var draft: String {
        get { current?.draft ?? homeDraft }
        set { if let i = index(currentID) { if chats[i].draft != newValue { chats[i].draft = newValue } } else if homeDraft != newValue { homeDraft = newValue } }
    }
    var scope: Scope {
        get { current?.scope ?? homeScope }
        set { if let i = index(currentID) { chats[i].scope = newValue } else { homeScope = newValue } }
    }
    var deep: Bool {
        get { current?.deep ?? homeDeep }
        set { if let i = index(currentID) { chats[i].deep = newValue } else { homeDeep = newValue } }
    }
    var model: String {
        get { current?.model ?? homeModel }
        set { if let i = index(currentID) { chats[i].model = newValue } else { homeModel = newValue } }
    }
    /// The other conversations, oldest first.
    var shelved: [[Turn]] { chats.filter { $0.id != currentID && !$0.turns.isEmpty }.sorted { $0.updated < $1.updated }.map(\.turns) }

    var onScreen = false            // the chat view is what the owner is looking at
    @ObservationIgnored var follow = true       // the page keeps the last line of an answer being written in view; off once the owner scrolls up
    var goTo: Int?                  // a turn to scroll to when the chat comes up
    var openMaybe: Set<Int> = []    // turns whose "might be related" is unfolded
    var thread: ThreadPeek?         // a cited row, open in its conversation
    @ObservationIgnored var threadCall: EngineClient.Handle?
    @ObservationIgnored var hovered: (hit: Hit, turn: Int)?     // the citation under the pointer
    var judged: [String: Bool] = [:]  // "might be related" rows the owner has said yes or no to
    /// False only when CONTEXT_STREAM=0: the answer then comes whole, the old way.
    static let streams = ProcessInfo.processInfo.environment["CONTEXT_STREAM"] != "0"
    @ObservationIgnored private var nextID = -1
    var chatShown: Bool { chatting }
    @ObservationIgnored private weak var lastEngine: Engine?
    var notice = ""                 // one line under the input when a send could not start
    var openSources: Set<Int> = []  // turns whose sources are unfolded
    var openHow: Set<Int> = []      // turns whose "how it searched" is unfolded
    var openCite: String?           // the source row showing its full text
    var flash: String?              // the source row a citation just pointed at
    var peek: String?               // the citation under the pointer
    /// One piece of evidence, chosen: its dot on the ribbon, its sentence in the answer and its note in the margin
    /// are the same selection. The pointer over any of the three chooses it; a click keeps it chosen.
    var hoverPick: Pick?
    var pinned: Pick?
    var chosen: Pick? { hoverPick ?? pinned }
    var evidenceShown: Set<Int> = []    // answers whose evidence the owner asked to see, when citations are off or quiet
    var threadInMargin = false      // the open message was unfolded from a margin note, so it shows there and not in the panel
    var chatting: Bool { !turns.isEmpty }
    /// how long an answer may take before it is stopped and says so
    static var patience: TimeInterval = 150

    @ObservationIgnored private var flag: Flag?
    @ObservationIgnored private var work: DispatchWorkItem?

    init(home: URL) {
        self.home = home
        var said: [String: Bool] = [:]
        chats = ChatStore.load(home, newID: { self.newID() }, judged: &said)
        judged = said
    }

    var flat: [Hit] { groups.flatMap(\.hits) }
    var words: [String] { AskModel.terms(query) }

    /// Words that say nothing about what is being looked for. Exact-word search leaves them out.
    static let stopWords: Set<String> = ["a", "an", "the", "to", "my", "me", "i", "of", "in", "on", "at", "for", "and", "or", "is", "it", "that",
                                         "this", "with", "from", "by", "as", "be", "was", "are", "do", "did", "what", "where", "when", "who", "how",
                                         "link", "find", "show", "about", "you", "your", "we", "our", "have", "has", "had", "any", "some"]

    /// The words an exact search looks for: whole words, lower case, without the ones above.
    static func terms(_ query: String) -> [String] {
        let all = query.lowercased().split { !($0.isLetter || $0.isNumber) }.map(String.init)
        let kept = all.filter { !stopWords.contains($0) }
        return kept.isEmpty ? all.filter { $0.count > 1 } : kept       // a query of only small words still looks for them
    }

    /// A question that starts a conversation of its own, whatever is in the window: the panel, the morning card.
    @discardableResult
    func ask(_ engine: Engine, _ text: String) -> Bool {
        guard text.trimmingCharacters(in: .whitespacesAndNewlines).count >= 2 else { return false }
        fresh()
        return submit(text, engine)
    }

    /// The input becomes the next turn: of the chat in the window, or of a new one when the owner is on home.
    func send(_ engine: Engine) {
        let fromHome = currentID == nil
        let text = draft
        if let id = editing, let i = turns.firstIndex(where: { $0.id == id }), !asking {
            // the last question, changed: it is asked again in its own place
            let q = text.split(whereSeparator: \.isNewline).joined(separator: " ").trimmingCharacters(in: .whitespaces)
            guard q.count >= 2 else { notice = "say a little more, then return."; return }
            turns[i].q = q
            editing = nil
            draft = ""
            submit(q, engine, retry: id)
            return
        }
        if submit(text, engine) {
            draft = ""
            if fromHome { homeDraft = "" }
        }
    }

    /// A chat turn. The turn is on screen before the engine starts, and every way this can end writes a sentence into it.
    /// One at a time in each chat: a send while one is running there waits in the conversation and goes when its turn comes.
    @discardableResult
    func submit(_ raw: String, _ engine: Engine, retry: Int? = nil, in chat: String? = nil) -> Bool {
        let q = raw.split(whereSeparator: \.isNewline).joined(separator: " ").trimmingCharacters(in: .whitespaces)
        guard !q.isEmpty else { return false }
        guard q.count >= 2 else { notice = "say a little more, then return."; return false }
        notice = ""
        exact = false
        lastEngine = engine
        let id = chat ?? currentID ?? make()
        guard let c = index(id) else { return false }
        if busy.contains(id), retry == nil { chats[c].queue.append(q); return true }       // it waits its turn, in the conversation, marked "next"
        if busy.contains(id) { notice = "still reading. try again once this answer lands."; return false }
        if let retry, let i = chats[c].turns.firstIndex(where: { $0.id == retry }) {
            var t = chats[c].turns[i]
            t.answer = nil
            t.first = nil
            t.showFirst = false
            t.rated = nil
            t.items = []
            t.at = Date()
            chats[c].turns[i] = t
            begin(t, engine, in: id, at: i)
        } else {
            begin(Turn(id: newID(), q: q), engine, in: id)
        }
        return true
    }

    func edit(_ chat: String, _ turn: Int, _ body: (inout Turn) -> Void) {
        if let c = index(chat), let i = chats[c].turns.firstIndex(where: { $0.id == turn }) { body(&chats[c].turns[i]) }
    }

    func turn(_ chat: String, _ id: Int) -> Turn? { index(chat).flatMap { c in chats[c].turns.first { $0.id == id } } }

    /// An answer has landed in a chat: it is saved, named if it has no name, and marked unread unless the owner is looking at it.
    private func landed(_ chat: String, _ engine: Engine) {
        guard let c = index(chat) else { return }
        chats[c].updated = Date()
        if !(onScreen && currentID == chat) || !(NSApp?.isActive ?? false) {       // a check with no app object is never in front
            if !(onScreen && currentID == chat) { chats[c].unread = true; Tick.play() }
            if chats[c].unread { AppModel.shared.pinger.answered(chat: chat, title: chats[c].title, turn: chats[c].turns.last?.id ?? 0) }
        }
        save(chat)
        if AppModel.shared.saved.nameChats { retitle(chat, engine) }
    }

    /// Puts the turn on screen and starts the engine on it: an answer, or a lens when the turn is one.
    private func begin(_ turn: Turn, _ engine: Engine, in chat: String, at index: Int? = nil) {
        guard let c = self.index(chat) else { return }
        let at: Int
        if let index { at = index } else { chats[c].turns.append(turn); at = chats[c].turns.count - 1 }
        if chats[c].title.isEmpty { chats[c].title = AskModel.firstWords(turn.q) }
        chats[c].updated = Date()
        let id = turn.id
        lastEngine = engine
        opened = nil
        peek = nil
        busy.insert(chat)
        asked = turn.q
        askedAt = Date()
        let run = runs[chat] ?? Run()
        runs[chat] = run
        run.token += 1
        let mine = run.token
        let past = AskModel.history(Array(chats[c].turns[..<at]))
        let scope = chats[c].scope, deep = chats[c].deep, model = chats[c].model
        save(chat)
        if turn.lensID == nil, AskModel.streams {
            // told as it happens: the steps it takes, then the words as they are written, then the whole reply
            let tag = "t\(id)"
            chats[c].turns[at].live = Live()
            chats[c].turns[at].streamed = false
            var settled = false
            // the first whole reply ends the wait: the answer is their to read, and the next question may go
            func settle(_ answer: Answer?) {
                guard !settled, run.token == mine else { return }
                settled = true
                busy.remove(chat)
                if currentID == chat { notice = "" }
                edit(chat, id) { t in
                    t.streamed = t.live?.text.isEmpty == false
                    t.answer = answer ?? .failure("the engine stopped before it answered. ask again.")
                    t.live = nil
                }
                landed(chat, engine)
                next(chat)
            }
            var handle: EngineClient.Handle?
            var heard = Date()
            handle = engine.client.answer(turn.q, history: past, scope: scope, deep: deep, dig: AppModel.shared.saved.lookDeeper, model: model, event: { [weak self] ev in
                guard let self, let now = self.turn(chat, id) else { return }
                heard = Date()
                if settled {
                    // after the first answer: a deeper search, only ever under an answer that was not strong
                    if ev["phase"] as? String == "dig-pending" {
                        self.edit(chat, id) { $0.dig = "" }                 // a deeper search will follow: say so at once
                    } else if ev["phase"] as? String == "dig", now.answer?.strength != "strong" {
                        self.edit(chat, id) { $0.dig = Answer.lower(ev["doing"] as? String ?? "") }
                    } else if let done = ev["done"] as? [String: Any], let deeper = Answer(done, tag: tag + "d"), deeper.deep {
                        self.edit(chat, id) { t in
                            if t.answer?.strength != "strong", !deeper.text.isEmpty {
                                t.first = t.answer
                                t.answer = deeper
                                t.streamed = true
                            }
                            t.dig = nil
                        }
                        self.save(chat)
                        handle?.finish()
                    } else if let s = WorkStep(ev["step"] as? [String: Any]), now.dig != nil {
                        self.edit(chat, id) { $0.dig = s.line }
                    } else if ev["error"] != nil || ev["end"] != nil {
                        self.edit(chat, id) { $0.dig = nil }
                        handle?.finish()
                    }
                    return
                }
                guard run.token == mine else { return }
                if let done = ev["done"] as? [String: Any] {
                    var a = Answer(done, tag: tag)
                    if a?.steps.isEmpty == true, let seen = now.live?.steps { a?.steps = seen }
                    if let a, a.secs < 1 { var b = a; b.secs = Date().timeIntervalSince(now.at); settle(b) } else { settle(a) }
                    // a strong answer is the end. under any other, a deeper search may follow: wait a little for its first word.
                    // an engine that says {"end"} when it has nothing more ends the wait at once
                    if a == nil || a?.strength == "strong" || a?.strength == "" || a?.deep == true { handle?.finish(); return }
                    DispatchQueue.main.asyncAfter(deadline: .now() + 8) { [weak self] in
                        guard let self, let t = self.turn(chat, id), t.dig == nil, t.first == nil else { return }
                        handle?.finish()
                    }
                    return
                }
                if let e = ev["error"] as? String { settle(.failure(Answer.plain(e))); handle?.finish(); return }
                self.edit(chat, id) { t in
                    var live = t.live ?? Live()
                    live.take(ev, tag: tag)
                    t.live = live
                }
            }, done: { [weak self] in
                guard let self else { return }
                self.edit(chat, id) { $0.dig = nil }
                if run.stream === handle { run.stream = nil }
                settle(nil)
            })
            run.stream = handle
            // an engine that goes silent is not waited on for ever: after `patience` with no word from it, the turn says so
            func watch(_ wait: TimeInterval) {
                DispatchQueue.main.asyncAfter(deadline: .now() + wait) { [weak self] in
                    guard let self, !settled, run.token == mine else { return }
                    let quiet = Date().timeIntervalSince(heard)
                    if quiet < AskModel.patience { watch(AskModel.patience - quiet + 0.05); return }
                    handle?.cancel()
                    if run.stream === handle { run.stream = nil }
                    settle(.failure("that took more than \(Int(AskModel.patience)) seconds, so context stopped reading. try again."))
                    _ = self
                }
            }
            if handle != nil { watch(AskModel.patience) }
            if handle == nil {
                busy.remove(chat)
                chats[c].turns[at].live = nil
                chats[c].turns[at].answer = .failure("the engine could not be started. check settings.")
            }
            return
        }
        let args = turn.lensID.map { ["lens", $0] } ?? ["answer", turn.q, "--history", past]
        run.call = EngineCall.start(repo: engine.repo, args: args, timeout: AskModel.patience) { [weak self] reply in
            guard let self, run.token == mine else { return }       // stopped, or a newer question took its place
            self.busy.remove(chat)
            run.call = nil
            if self.currentID == chat { self.notice = "" }
            self.edit(chat, id) { t in
                if turn.lensID != nil {
                    let (answer, items) = Answer.from(lens: reply, title: turn.q, tag: "t\(id)")
                    t.answer = answer
                    t.items = items
                } else {
                    t.answer = Answer.from(reply, tag: "t\(id)")
                }
            }
            self.landed(chat, engine)
            self.next(chat)
        }
    }

    private func newID() -> Int { nextID += 1; return nextID }

    /// The next question starts a conversation of its own. The one in the window is kept, and whatever it is reading goes on.
    private func fresh() {
        currentID = nil
        openCite = nil
        flash = nil
        editing = nil
        sourcesFor = nil
    }

    /// The last few questions, newest first, across every conversation.
    var recent: [Turn] {
        Array(chats.flatMap(\.turns).filter { $0.answer != nil }.sorted { $0.at > $1.at }.prefix(5))
    }

    /// Opens the conversation that holds this turn, at that turn.
    func reopen(_ id: Int) {
        if let c = current.flatMap({ $0.turns.contains { $0.id == id } ? $0 : nil }) ?? chats.first(where: { $0.turns.contains { $0.id == id } }) {
            open(c.id)
        }
        goTo = id
    }

    /// The oldest waiting question of a chat goes to the engine, if nothing is being read there.
    func next(_ chat: String? = nil) {
        guard let id = chat ?? currentID, !busy.contains(id), let c = index(id), !chats[c].queue.isEmpty, let engine = lastEngine else { return }
        submit(chats[c].queue.removeFirst(), engine, in: id)
    }

    /// Esc, or "stop": the answer being read here is stopped. A question waiting behind it is kept and goes next.
    func stop() {
        cancelAsk()
        next()
    }

    /// The same question again, in the same place.
    func again(_ turn: Turn, _ engine: Engine) { submit(turn.q, engine, retry: turn.id) }

    /// Up-arrow in an empty input: the last question comes back to be changed. Esc puts it away.
    func editLast() {
        guard !asking, let t = turns.last, t.lensID == nil else { return }
        editing = t.id
        draft = t.q
    }

    /// The last four answered turns as the engine wants them: no citation markers, each answer cut to about 600 characters.
    static func history(_ turns: [Turn]) -> String {
        let past = turns.filter { $0.answer?.text.isEmpty == false }.suffix(4).map { t -> [String: String] in
            ["q": String(t.q.prefix(300)), "a": String(Answer.strip(t.answer?.text ?? "").prefix(600))]
        }
        return (try? JSONSerialization.data(withJSONObject: past, options: [.sortedKeys])).flatMap { String(data: $0, encoding: .utf8) } ?? "[]"
    }

    /// A row the answer points to: open the sources under that answer, open the row, and mark it for a moment.
    func show(_ hit: Hit, in turn: Int) {
        openSources.insert(turn)
        sourcesFor = turn
        openCite = hit.id
        flash = hit.id
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.6) { [weak self] in if self?.flash == hit.id { self?.flash = nil } }
    }

    /// The keys of the input while a conversation, or home, is on screen. Return sends; esc stops a running answer,
    /// then puts away what is open; up-arrow in an empty input brings the last question back.
    func chatKey(_ e: NSEvent, _ engine: Engine) -> Bool {
        if thread != nil, threadKey(e, engine) { return true }
        guard e.modifierFlags.intersection([.command, .option, .control, .shift]).isEmpty else { return false }
        // space, with the pointer on a citation and nothing being typed: the message in its conversation
        if e.keyCode == 49, draft.isEmpty, peek != nil, let found = hovered { peekThread(found.hit, turn: found.turn, engine); return true }
        if e.keyCode == 36 || e.keyCode == 76 {
            if draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { return true }       // nothing to send: no stray new line
            send(engine)
            return true
        }
        if e.keyCode == 53 {
            if editing != nil { editing = nil; draft = ""; return true }
            if asking { stop(); return true }
            if sourcesFor != nil { sourcesFor = nil; return true }
            return false
        }
        if e.keyCode == 126, draft.isEmpty, chatting, !asking { editLast(); return editing != nil }
        return false
    }

    /// Home again, ready for a question that starts a new conversation. Nothing is stopped: an answer being read
    /// in the chat the owner left keeps coming, and its row in the list says so.
    func newChat() {
        fresh()
        opened = nil
        notice = ""
        exact = false
        peek = nil
        closeThread()
    }

    /// "good answer" or "not right": every row the answer leaned on is marked so for this question, on this mac.
    func rate(_ turn: Turn, ok: Bool, _ engine: Engine) {
        guard let i = turns.firstIndex(where: { $0.id == turn.id }), turns[i].rated == nil, let a = turns[i].answer else { return }
        turns[i].rated = ok
        for c in a.cites { engine.client.rate(question: turn.q, id: AskModel.rowID(c), yes: ok, kind: "answer") }
        if let id = currentID { save(id) }
    }

    /// A "might be related" row: yes moves it into what later searches trust, no keeps it out.
    func judge(_ hit: Hit, yes: Bool, question: String, _ engine: Engine) {
        guard judged[hit.id] == nil else { return }
        judged[hit.id] = yes
        engine.client.rate(question: question, id: AskModel.rowID(hit), yes: yes, kind: "maybe")
        if let id = currentID { save(id) }
    }

    /// The archive's own id of a cited row: ours is "tag:index:id".
    static func rowID(_ hit: Hit) -> String { hit.id.split(separator: ":", maxSplits: 2).last.map(String.init) ?? hit.id }

    /// The question and its answer as plain text, for the clipboard or the plan.
    /// The question and the answer as markdown that stands on its own: the answer as the engine wrote it, its markers
    /// kept, and under it the rows they point at, numbered.
    static func markdown(_ t: Turn) -> String {
        guard let a = t.answer else { return "> " + t.q }
        var out = "> " + t.q.replacingOccurrences(of: "\n", with: "\n> ") + "\n\n" + (a.text.isEmpty ? a.error : a.text)
        if !a.cites.isEmpty {
            out += "\n\n---\n"
            for (i, h) in a.cites.enumerated() {
                let said = h.text.replacingOccurrences(of: "\n", with: " ").trimmingCharacters(in: .whitespaces)
                out += "\n[\(i + 1)] \(Cite.title(h)), \(Catalog.info(h.src).name), \(Words.day(h.ts))" + (said.isEmpty ? "" : ": \"\(said.prefix(200))\"") + (Cite.link(h).map { " <\($0.absoluteString)>" } ?? "")
            }
        }
        return out
    }

    static func plain(_ t: Turn) -> String {
        guard let a = t.answer else { return t.q }
        return t.q + "\n\n" + (a.text.isEmpty ? a.error : a.text)
    }

    /// {"cmd": "starters"}: up to six short questions made from their profile. Home shows two of them before the lenses.
    func loadStarters(_ engine: Engine) {
        engine.client.call(["cmd": "starters"], timeout: 30) { [weak self] reply in
            let rows = (reply as? [Any]) ?? ((reply as? [String: Any])?["starters"] as? [Any]) ?? []
            self?.take(starters: rows)
        }
    }

    func loadLenses(_ engine: Engine) {
        engine.json(["lens", "--list"], timeout: 30) { [weak self] obj in
            guard let rows = obj?["list"] as? [[String: Any]] else { return }      // no such command yet: no row of lenses
            self?.lenses = rows.compactMap { r in
                guard let id = r["id"] as? String, let title = r["title"] as? String else { return nil }
                return LensInfo(id: id, title: title.lowercased(), about: (r["about"] as? String ?? "").lowercased())
            }
        }
    }

    /// `python3 -m ctx lens <id>`: a ready-made question. It is a turn in a chat of its own: the lens's name
    /// is the question, its summary the answer, its items a list under it, the rows they rest on the sources.
    func run(_ l: LensInfo, _ engine: Engine) {
        fresh()
        exact = false
        let id = make()
        begin(Turn(id: newID(), q: l.title, lensID: l.id), engine, in: id)
    }

    /// done, or not real: the same row the nudge actions write, so the engine learns which items were right.
    func score(_ item: LensItem, ok: Bool, in turn: Int) {
        let row: [String: Any] = ["q": item.what, "ids": [item.cite.map { String($0.id.split(separator: ":", maxSplits: 2).last ?? "") } ?? ""], "ok": ok]
        if !Engine.debug, let data = try? JSONSerialization.data(withJSONObject: row, options: [.sortedKeys]) {
            Files.append(data, to: home.appendingPathComponent("scores.jsonl"))
        }
        guard let t = turns.firstIndex(where: { $0.id == turn }), let i = turns[t].items.firstIndex(where: { $0.id == item.id }) else { return }
        if ok { turns[t].items[i].status = "done" } else { turns[t].items.remove(at: i) }
        if let id = currentID { save(id) }
    }

    /// Stops what is being read for one chat. A turn that was waiting keeps its question and says it was stopped;
    /// what was already written stays.
    func cancel(_ chat: String, keep: Bool = true) {
        if let run = runs[chat] {
            run.call?.cancel()
            run.call = nil
            run.stream?.cancel()
            run.stream = nil
            run.token += 1
        }
        // the turn being read may be the last, or an earlier one asked again in its place
        if busy.contains(chat), let c = index(chat) {
            for i in chats[c].turns.indices where chats[c].turns[i].answer == nil {
                if var part = chats[c].turns[i].live?.partial(tag: "t\(chats[c].turns[i].id)") {
                    part.stopped = true
                    chats[c].turns[i].streamed = true
                    chats[c].turns[i].answer = part
                } else {
                    chats[c].turns[i].answer = .failure("stopped before it finished.")
                }
                chats[c].turns[i].live = nil
                chats[c].turns[i].dig = nil
            }
        }
        busy.remove(chat)
        if keep { save(chat) }
    }

    /// Stops whatever is being read in the conversation in the window.
    func cancelAsk() {
        if let id = currentID { cancel(id) }
        notice = ""
    }

    /// The app is closing: nothing is left half read.
    func cancelAll() { for id in busy { cancel(id) } }

    private func changed() {
        flag?.set()
        work?.cancel()
        opened = nil
        let q = query.trimmingCharacters(in: .whitespaces)
        guard exact, q.count >= 2, !AskModel.terms(q).isEmpty else { groups = []; searching = false; return }
        searching = true
        let f = Flag()
        flag = f
        let home = self.home
        let item = DispatchWorkItem {
            let t = Date()
            let found = Jsonl.search(home: home, query: q, stop: f)
            let ms = Int(Date().timeIntervalSince(t) * 1000)
            DispatchQueue.main.async {
                guard !f.isSet else { return }
                self.groups = found
                self.selected = found.first?.hits.first?.id
                self.searching = false
                self.tookMs = ms
                if ProcessInfo.processInfo.environment["CONTEXT_DEBUG"] != nil {
                    FileHandle.standardError.write("search \(q.count) chars: \(found.reduce(0) { $0 + $1.total }) hits, \(ms) ms\n".data(using: .utf8)!)
                }
            }
        }
        work = item
        DispatchQueue.global(qos: .userInitiated).asyncAfter(deadline: .now() + 0.08, execute: item)
    }

    func rerun() { let q = query; query = ""; query = q }

    func move(_ by: Int) {
        let all = flat
        guard !all.isEmpty else { return }
        let i = all.firstIndex { $0.id == selected } ?? -1
        selected = all[max(0, min(all.count - 1, i + by))].id
        if opened != nil { open() }
    }

    func open(_ hit: Hit? = nil) {
        guard let h = hit ?? flat.first(where: { $0.id == selected }) else { return }
        selected = h.id
        opened = h
        context = [h]
        let home = self.home
        DispatchQueue.global(qos: .userInitiated).async {
            var real = h
            if h.kind == "cite", let raw = h.id.split(separator: ":", maxSplits: 2).last {
                let needle = Array("\"id\": \"\(raw.lowercased())\"".utf8)
                let path = home.appendingPathComponent("messages.jsonl").path
                let fd = Darwin.open(path, O_RDONLY)
                if fd >= 0 {
                    for c in Jsonl.candidates(path: path, needles: [needle], stop: nil) {
                        if let d = Jsonl.read(fd: fd, c), (d["id"] as? String) == String(raw), let found = Jsonl.hit(d, kind: "message", offset: c.0) {
                            real = found
                            break
                        }
                    }
                    Darwin.close(fd)
                }
            }
            var around = Jsonl.thread(home: home, hit: real)
            if real.id != h.id { around = around.map { $0.id == real.id ? Hit(id: h.id, src: $0.src, kind: "message", ts: $0.ts, thread: $0.thread, threadID: $0.threadID, who: $0.who, sender: $0.sender, text: $0.text, url: $0.url, offset: $0.offset) : $0 } }
            DispatchQueue.main.async { if self.opened?.id == h.id { self.context = around } }
        }
    }

    /// Esc in exact-word search: the open row, then the search itself.
    func close() -> Bool {
        if opened != nil { opened = nil; return true }
        if exact { exact = false; query = ""; return true }
        return false
    }
}

extension Answer {
    /// Something written for them to send, in their own voice: the engine says so, or the question asked for exactly that.
    func isDraft(for question: String) -> Bool {
        if draft { return true }
        guard error.isEmpty, !text.isEmpty else { return false }
        let q = question.lowercased()
        let asks = ["draft ", "write a reply", "write a message", "write an email", "write a text", "write back to", "reply to ", "in my voice", "as me"]
        return asks.contains { q.hasPrefix($0) || q.contains(" " + $0) } && (q.hasPrefix("draft") || q.hasPrefix("write") || q.hasPrefix("reply") || q.contains("in my voice"))
    }

    /// The words alone: no citation markers, as the owner would paste them into a message.
    var plainText: String { Answer.strip(text) }
}
