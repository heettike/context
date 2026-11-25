import AppKit
import Foundation

/// What a question is asked of: everything, or a part of it. Sent to the engine with the question.
struct Scope: Equatable {
    var sources: [String] = []
    var after = ""              // an iso day, or nothing
    var before = ""
    var people: [String] = []

    var isAll: Bool { sources.isEmpty && after.isEmpty && before.isEmpty && people.isEmpty }

    init() {}
    init(_ d: [String: Any]?) {
        sources = d?["sources"] as? [String] ?? []
        after = d?["after"] as? String ?? ""
        before = d?["before"] as? String ?? ""
        people = d?["people"] as? [String] ?? []
    }

    /// As the engine takes it: {"sources":[…],"after":…,"before":…,"people":[…]}.
    var json: [String: Any] {
        ["sources": sources, "after": after.isEmpty ? NSNull() : after as Any, "before": before.isEmpty ? NSNull() : before as Any, "people": people]
    }
}

/// One conversation. It is a file in CTX_HOME/chats, and it opens again exactly as it was left.
struct Chat: Identifiable, Equatable {
    let id: String
    var title = ""
    var named = false           // the engine or the owner gave it its title; until then it is the first words of the question
    var created = Date()
    var updated = Date()
    var pinned = false
    var turns: [Turn] = []
    var draft = ""              // what the owner had typed here when the owner went elsewhere
    var queue: [String] = []    // questions sent while an answer was being read: each goes when the one before lands
    var unread = false          // an answer landed here while the owner was looking at something else
    var scope = Scope()
    var deep = false            // "deep": the engine searches deeper from the start
    var model = ""              // a model picked for this chat alone, as the engine asks for it; "" follows the preset
}

/// Reading and writing the chat files. One JSON object per chat; a file that does not parse is left alone and skipped.
enum ChatStore {
    /// True in a check that wants the files written to its own throwaway folder. A render or a layout check writes nothing.
    static var force = false
    static var writes: Bool { !Engine.debug || force }

    static func dir(_ home: URL) -> URL { home.appendingPathComponent("chats", isDirectory: true) }
    static func file(_ id: String, _ home: URL) -> URL { dir(home).appendingPathComponent(id + ".json") }

    /// Sorts by the day it was started, and never collides.
    static func newID() -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyyMMdd-HHmmss"
        return f.string(from: Date()) + "-" + String(UUID().uuidString.prefix(6)).lowercased()
    }

    static func row(_ h: Hit) -> [String: Any] {
        ["id": AskModel.rowID(h), "src": h.src, "ts": h.ts, "thread": h.thread, "who": h.who, "text": h.text, "url": h.url]
    }

    static func answer(_ a: Answer) -> [String: Any] {
        ["answer": a.text, "error": a.error, "cites": a.cites.map(row), "maybe": a.maybe.map(row), "searched": a.searched, "found": a.found,
         "secs": a.secs, "strength": a.strength, "deep": a.deep, "stopped": a.stopped, "trail": a.trail,
         "steps": a.steps.map(\.dict), "usage": a.usage.dict, "model": a.model, "fallback": a.fallback, "draft": a.draft,
         "links": a.links.map { ["url": $0.url, "what": $0.what, "ts": $0.ts, "src": $0.src] }]
    }

    static func answer(_ d: [String: Any]?, tag: String) -> Answer? {
        guard var a = Answer(d, tag: tag) else { return nil }
        a.stopped = d?["stopped"] as? Bool ?? false
        if let t = d?["trail"] as? String { a.trail = t }
        return a
    }

    static func json(_ c: Chat, judged: [String: Bool]) -> [String: Any] {
        let turns = c.turns.map { t -> [String: Any] in
            var d: [String: Any] = ["q": t.q, "at": t.at.timeIntervalSince1970]
            if let l = t.lensID { d["lens"] = l }
            if let r = t.rated { d["rated"] = r }
            if let a = t.answer { d["answer"] = answer(a) }
            if let f = t.first { d["first"] = answer(f) }
            if !t.items.isEmpty {
                d["items"] = t.items.map { i -> [String: Any] in
                    var r: [String: Any] = ["what": i.what, "who": i.who, "when": i.when, "status": i.status]
                    if let h = i.cite { r["cite"] = row(h) }
                    return r
                }
            }
            let said = (t.answer?.maybe ?? []).reduce(into: [String: Bool]()) { if let v = judged[$1.id] { $0[AskModel.rowID($1)] = v } }
            if !said.isEmpty { d["judged"] = said }
            return d
        }
        return ["v": 1, "id": c.id, "title": c.title, "named": c.named, "created": c.created.timeIntervalSince1970,
                "updated": c.updated.timeIntervalSince1970, "pinned": c.pinned, "draft": c.draft, "scope": c.scope.json, "deep": c.deep, "model": c.model,
                "unread": c.unread, "turns": turns]
    }

    /// A chat from its file. Turn ids are this run's own: `newID` hands out the next one.
    static func chat(_ d: [String: Any], newID: () -> Int, judged: inout [String: Bool]) -> Chat? {
        guard let id = d["id"] as? String, !id.isEmpty else { return nil }
        var c = Chat(id: id)
        func date(_ k: String) -> Date { Date(timeIntervalSince1970: (d[k] as? NSNumber)?.doubleValue ?? 0) }
        c.title = d["title"] as? String ?? ""
        c.named = d["named"] as? Bool ?? false
        c.created = date("created")
        c.updated = date("updated")
        c.pinned = d["pinned"] as? Bool ?? false
        c.draft = d["draft"] as? String ?? ""
        c.scope = Scope(d["scope"] as? [String: Any])
        c.deep = d["deep"] as? Bool ?? false
        c.model = d["model"] as? String ?? ""
        c.unread = d["unread"] as? Bool ?? false
        for raw in d["turns"] as? [[String: Any]] ?? [] {
            guard let q = raw["q"] as? String else { continue }
            let n = newID(), tag = "t\(n)"
            var t = Turn(id: n, q: q, lensID: raw["lens"] as? String)
            t.at = Date(timeIntervalSince1970: (raw["at"] as? NSNumber)?.doubleValue ?? 0)
            t.rated = raw["rated"] as? Bool
            // a turn that was still being read when the app closed has no answer to come back to
            t.answer = answer(raw["answer"] as? [String: Any], tag: tag) ?? .failure("this one was not finished. try again.")
            t.first = answer(raw["first"] as? [String: Any], tag: tag + "f")
            t.streamed = true
            t.items = ((raw["items"] as? [[String: Any]]) ?? []).enumerated().map { i, r in
                let cite = (r["cite"] as? [String: Any]).flatMap { Answer.cite($0, i, prefix: tag) }
                return LensItem(id: cite?.id ?? "\(tag):item\(i)", what: r["what"] as? String ?? "", who: r["who"] as? String ?? "",
                                when: r["when"] as? String ?? "", status: r["status"] as? String ?? "unclear", cite: cite)
            }
            if let said = raw["judged"] as? [String: Bool] {
                for h in t.answer?.maybe ?? [] { if let v = said[AskModel.rowID(h)] { judged[h.id] = v } }
            }
            c.turns.append(t)
        }
        return c
    }

    static func load(_ home: URL, newID: () -> Int, judged: inout [String: Bool]) -> [Chat] {
        let files = (try? FileManager.default.contentsOfDirectory(at: dir(home), includingPropertiesForKeys: nil)) ?? []
        var out: [Chat] = []
        for f in files.filter({ $0.pathExtension == "json" }).sorted(by: { $0.lastPathComponent < $1.lastPathComponent }) {
            guard let data = try? Data(contentsOf: f), let d = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
                  let c = chat(d, newID: newID, judged: &judged), !c.turns.isEmpty else { continue }
            out.append(c)
        }
        return out
    }

    static func write(_ c: Chat, judged: [String: Bool], home: URL) {
        guard writes, !c.turns.isEmpty,
              let data = try? JSONSerialization.data(withJSONObject: json(c, judged: judged), options: [.sortedKeys]) else { return }
        try? FileManager.default.createDirectory(at: dir(home), withIntermediateDirectories: true)
        try? data.write(to: file(c.id, home), options: .atomic)
    }

    /// A deleted chat goes to the Trash, where it can be found again.
    static func trash(_ id: String, home: URL) {
        guard writes else { return }
        let f = file(id, home)
        // a check never puts anything in their Trash
        if force || (try? FileManager.default.trashItem(at: f, resultingItemURL: nil)) == nil {
            // no Trash to be had (a throwaway folder on a volume without one): keep the file, under a name the list does not read
            try? FileManager.default.moveItem(at: f, to: f.appendingPathExtension("deleted"))
        }
    }
}

// MARK: the list of chats

extension AskModel {
    struct Section: Equatable { let name: String; let chats: [Chat] }

    var current: Chat? { currentID.flatMap { id in chats.first { $0.id == id } } }
    func index(_ id: String?) -> Int? { id.flatMap { id in chats.firstIndex { $0.id == id } } }

    /// A new, empty conversation, made the moment its first question is sent. It becomes the one in the window.
    @discardableResult
    func make() -> String {
        var c = Chat(id: ChatStore.newID())
        c.scope = homeScope
        c.deep = homeDeep
        c.model = homeModel
        chats.append(c)
        currentID = c.id
        return c.id
    }

    /// The first words of a question, as a title until the engine gives a better one.
    static func firstWords(_ q: String, max: Int = 42) -> String {
        let flat = q.split(whereSeparator: \.isWhitespace).joined(separator: " ")
        guard flat.count > max else { return flat }
        var out = ""
        for w in flat.split(separator: " ") {
            if out.count + w.count + 1 > max { break }
            out += (out.isEmpty ? "" : " ") + w
        }
        return out.isEmpty ? String(flat.prefix(max)) : out
    }

    /// Newest first, pinned ones on top. Every chat that has been asked something.
    var ordered: [Chat] {
        chats.filter { !$0.turns.isEmpty }.sorted { ($0.pinned ? 1 : 0, $0.updated) > ($1.pinned ? 1 : 0, $1.updated) }
    }

    /// The sidebar's list: pinned, today, yesterday, last 7 days, older. `matching` keeps titles and questions that hold the words.
    func sections(matching: String = "", now: Date = Date()) -> [Section] {
        let words = matching.lowercased().split(whereSeparator: \.isWhitespace).map(String.init)
        let all = ordered.filter { c in
            guard !words.isEmpty else { return true }
            let hay = (c.title + " " + c.turns.map(\.q).joined(separator: " ")).lowercased()
            return words.allSatisfy(hay.contains)
        }
        let cal = Calendar.current
        let today = cal.startOfDay(for: now)
        func bucket(_ c: Chat) -> Int {
            if c.pinned { return 0 }
            let days = cal.dateComponents([.day], from: cal.startOfDay(for: c.updated), to: today).day ?? 0
            return days <= 0 ? 1 : (days == 1 ? 2 : (days <= 7 ? 3 : 4))
        }
        let names = ["pinned", "today", "yesterday", "last 7 days", "older"]
        return (0..<5).compactMap { b in
            let mine = all.filter { bucket($0) == b }
            return mine.isEmpty ? nil : Section(name: names[b], chats: mine)
        }
    }

    /// Opens a conversation in the window. Whatever is running elsewhere keeps running.
    func open(_ id: String) {
        guard let i = index(id) else { return }
        if currentID != id {
            currentID = id
            closeThread()
            peek = nil
            notice = ""
            openCite = nil
            flash = nil
            editing = nil
            sourcesFor = nil
        }
        if chats[i].unread { chats[i].unread = false; save(id) }
        exact = false
    }

    /// The chat above or below this one in the list, as the keys walk it.
    func step(_ by: Int) {
        let all = sections().flatMap(\.chats)
        guard !all.isEmpty else { return }
        guard let i = all.firstIndex(where: { $0.id == currentID }) else { open(all[by > 0 ? 0 : all.count - 1].id); return }
        open(all[min(max(i + by, 0), all.count - 1)].id)
    }

    func rename(_ id: String, to title: String) {
        let t = title.split(whereSeparator: \.isWhitespace).joined(separator: " ")
        guard let i = index(id), !t.isEmpty else { return }
        chats[i].title = String(t.prefix(80))
        chats[i].named = true
        save(id)
    }

    func pin(_ id: String) {
        guard let i = index(id) else { return }
        chats[i].pinned.toggle()
        save(id)
    }

    /// The file goes to the Trash. An answer still being read for it is stopped.
    func delete(_ id: String) {
        guard index(id) != nil else { return }
        cancel(id, keep: false)
        chats.removeAll { $0.id == id }
        runs[id] = nil
        if currentID == id { currentID = nil }
        ChatStore.trash(id, home: home)
    }

    func save(_ id: String) {
        guard let i = index(id) else { return }
        ChatStore.write(chats[i], judged: judged, home: home)
    }

    /// `python3 -m ctx title "<question>" "<answer>"`: a few words for the list. An engine without it leaves the first words in place.
    func retitle(_ id: String, _ engine: Engine) {
        guard !Probe.on, let i = index(id), !chats[i].named, let t = chats[i].turns.first, let a = t.answer, !a.text.isEmpty else { return }
        engine.json(["title", String(t.q.prefix(400)), String(Answer.strip(a.text).prefix(600))], timeout: 40) { [weak self] obj in
            guard let self, let said = obj?["title"] as? String, let i = self.index(id), !self.chats[i].named else { return }
            let clean = said.split(whereSeparator: \.isWhitespace).joined(separator: " ").trimmingCharacters(in: CharacterSet(charactersIn: "\"'."))
            guard clean.count >= 2 else { return }
            self.chats[i].title = String(clean.prefix(80)).lowercased()
            self.chats[i].named = true
            self.save(id)
        }
    }

    /// For the checks: conversations as if asked earlier, oldest first, each an hour after the one before.
    func seed(_ all: [[Turn]], ago: TimeInterval = 3600) {
        for (i, turns) in all.enumerated() where !turns.isEmpty {
            var c = Chat(id: "seed-\(chats.count)-\(i)")
            c.turns = turns
            c.title = AskModel.firstWords(turns[0].q)
            c.created = Date().addingTimeInterval(-ago * Double(all.count - i))
            c.updated = c.created
            chats.append(c)
        }
    }

    /// For the checks: no conversations at all.
    func wipe() {
        busy.forEach { cancel($0, keep: false) }
        chats = []
        runs = [:]
        busy = []
        currentID = nil
        homeDraft = ""
        homeScope = Scope()
        homeDeep = false
        homeModel = ""
        editing = nil
        sourcesFor = nil
        judged = [:]
    }
}
