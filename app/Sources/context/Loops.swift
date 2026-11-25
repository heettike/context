import Foundation
import Observation

/// A question the engine wrote about something left hanging. Here it is one input to the coach, not a screen.
struct Loop: Identifiable, Equatable {
    let q: String
    let kind: String
    let thread: String
    let date: String
    let ids: [String]
    let why: String
    var id: String { q }

    var kindWords: String {
        switch kind {
        case "waiting": return "someone is waiting"
        case "promise": return "you said you would"
        case "owe": return "you owe a reply"
        case "agent": return "an agent is waiting"
        default: return kind
        }
    }
}

/// Small things the app remembers, kept beside the data in `app.json`.
struct Saved: Codable {
    var onboarded = false
    var hourly = true
    var pill = false
    var focus = ""
    var focusSet: Double = 0
    var hidden: [String: Double] = [:]   // nudge id -> hidden until
    var quietUntil: Double = 0           // no pings before this time
    var hadDisk = false                  // full disk access was on at some point, so losing it is news
    var hadTitles = false
    var seenArrived: [String]?           // exports whose arrival was already announced
    var pingsOff = false                 // the menu-bar ping, switched off in settings
    var soundOff = false                 // the one sound, switched off in settings
    var hotkey = "control-option"                // the key that opens the panel from anywhere: see HotKey.choices
    var python = ""                      // a python to run the engine with, if the usual places do not have one
    var sidebar = true                   // the list of chats on the left is open
    var pings = PingBook()               // what the menu-bar panel has said, and what the owner said back
    // what context does on its own, each with a switch in settings (SettingsPanes.swift, OwnCard). The engine reads the
    // same file for the two it does itself during the daily run: morningCard and modelCheck.
    var linksFromOthers = false          // the app's copy of links_from_others, shown only when the engine's settings report does not carry it
    var webIcons = false                 // ask a service's own site for its icon. off: icons come from this mac alone
    var nudgeModel = false               // let the plan word a nudge: it is sent the app in front and its window title
    var nameChats = true                 // one small call to name a new chat
    var lookDeeper = true                // the longer look that follows an unsure answer
    var relatePast = true                // one call per paragraph written in the journal, for the notes from their past
    var morningCard = true               // the one card a day
    var modelCheck = true                // the daily measure of which models the plan can run

    init() {}
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        onboarded = (try? c.decode(Bool.self, forKey: .onboarded)) ?? false
        hourly = (try? c.decode(Bool.self, forKey: .hourly)) ?? true
        pill = (try? c.decode(Bool.self, forKey: .pill)) ?? false
        focus = (try? c.decode(String.self, forKey: .focus)) ?? ""
        focusSet = (try? c.decode(Double.self, forKey: .focusSet)) ?? 0
        python = (try? c.decode(String.self, forKey: .python)) ?? ""
        pingsOff = (try? c.decode(Bool.self, forKey: .pingsOff)) ?? false
        hotkey = (try? c.decode(String.self, forKey: .hotkey)) ?? "control-option"
        soundOff = (try? c.decode(Bool.self, forKey: .soundOff)) ?? false
        hidden = (try? c.decode([String: Double].self, forKey: .hidden)) ?? [:]
        quietUntil = (try? c.decode(Double.self, forKey: .quietUntil)) ?? 0
        hadDisk = (try? c.decode(Bool.self, forKey: .hadDisk)) ?? false
        hadTitles = (try? c.decode(Bool.self, forKey: .hadTitles)) ?? false
        seenArrived = try? c.decode([String].self, forKey: .seenArrived)
        sidebar = (try? c.decode(Bool.self, forKey: .sidebar)) ?? true
        webIcons = (try? c.decode(Bool.self, forKey: .webIcons)) ?? false
        linksFromOthers = (try? c.decode(Bool.self, forKey: .linksFromOthers)) ?? false
        nudgeModel = (try? c.decode(Bool.self, forKey: .nudgeModel)) ?? false
        nameChats = (try? c.decode(Bool.self, forKey: .nameChats)) ?? true
        lookDeeper = (try? c.decode(Bool.self, forKey: .lookDeeper)) ?? true
        relatePast = (try? c.decode(Bool.self, forKey: .relatePast)) ?? true
        morningCard = (try? c.decode(Bool.self, forKey: .morningCard)) ?? true
        modelCheck = (try? c.decode(Bool.self, forKey: .modelCheck)) ?? true
        pings = (try? c.decode(PingBook.self, forKey: .pings)) ?? PingBook()
    }

    static func load(_ url: URL) -> Saved {
        (try? JSONDecoder().decode(Saved.self, from: Data(contentsOf: url))) ?? Saved()
    }
    func save(_ url: URL) {
        try? FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        if let d = try? JSONEncoder().encode(self) { try? d.write(to: url, options: .atomic) }
    }
}

@Observable final class LoopsModel {
    let home: URL
    var all: [Loop] = []
    var scored: Set<String> = []

    init(home: URL) {
        self.home = home
        reload()
    }

    var open: [Loop] { all.filter { !scored.contains($0.q) } }

    func reload() {
        if let data = try? Data(contentsOf: home.appendingPathComponent("loops.json")),
           let rows = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]] {
            all = rows.compactMap { r in
                guard let q = r["q"] as? String else { return nil }
                return Loop(q: q, kind: r["kind"] as? String ?? "", thread: r["thread"] as? String ?? "",
                            date: r["date"] as? String ?? "", ids: (r["ids"] as? [Any])?.map { "\($0)" } ?? [],
                            why: r["why"] as? String ?? "")
            }
        } else {
            all = []
        }
        scored = []
        if let text = try? String(contentsOf: home.appendingPathComponent("scores.jsonl"), encoding: .utf8) {
            for line in text.split(separator: "\n") {
                if let d = try? JSONSerialization.jsonObject(with: Data(line.utf8)) as? [String: Any], let q = d["q"] as? String {
                    scored.insert(q)
                }
            }
        }
    }

    /// Same row the engine's `review` command writes: was the question real.
    func score(_ loop: Loop, ok: Bool) {
        let row: [String: Any] = ["q": loop.q, "ids": loop.ids, "ok": ok]
        guard let data = try? JSONSerialization.data(withJSONObject: row, options: [.sortedKeys]) else { return }
        if !Engine.debug { Files.append(data, to: home.appendingPathComponent("scores.jsonl")) }
        scored.insert(loop.q)
    }
}
