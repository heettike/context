import AppKit
import SwiftUI

/// The second pass in the gate: the ribbon with no, one and many pieces of evidence; an answer as a page with margin
/// notes, and its fallback where there is no room; the desk with full, partial and empty data. All made-up.
extension LayoutTest {
    static let nowFull: [String: Any] = [
        "at": "2026-11-21T10:02:00+00:00",
        "waiting": [["who": "Sam Okafor", "what": "renewal and deposit, asked twice", "when": "2026-11-05T09:00:00Z", "days": 16, "thread": "sam (landlord)", "id": "W1", "src": "whatsapp"],
                    ["who": "Ines Marchetti", "what": "the deposit figure", "when": "2026-11-19T21:30:00Z", "days": 1, "thread": "the flat", "id": "W2", "src": "whatsapp"],
                    ["who": "the allotment committee and friends of the lower field (2026)", "what": "whether you will take the water rota slot in the first week of december, and who covers the second", "when": "2026-11-12T18:00:00Z", "days": 9, "thread": "", "id": "W3", "src": "telegram"],
                    ["who": "Priya Raman", "what": "proofs", "when": "2026-11-18T18:00:00Z", "days": 3, "thread": "priya", "id": "W4", "src": "imessage"],
                    ["who": "Jonas Weber", "what": "a fifth line that is not shown", "when": "2026-11-18T18:00:00Z", "days": 2, "thread": "jonas", "id": "W5", "src": "imessage"]],
        "promised": [["what": "send jonas the plot plan", "when": "2026-11-18T09:00:00Z", "days": 3, "thread": "jonas weber", "id": "T1", "src": "telegram"],
                     ["what": "book the water rota slot", "when": "2026-11-13T09:00:00Z", "days": 8, "thread": "lease questions", "id": "N1", "src": "apple_notes"]],
        "mind": [["what": "the seed swap", "detail": "41 messages, 3 notes", "thread": "seed swap"],
                 ["what": "moving, or staying", "detail": "came up 6 times", "thread": "the flat"],
                 ["what": "the lease", "detail": "came up 4 times", "thread": "the flat"]],
        "strip": (0..<131).map { i -> [String: Any] in          // 131 made-up months, from a round start to 2026-11
            let y = 2016 + i / 12, mo = i % 12 + 1
            return ["ym": String(format: "%04d-%02d", y, mo), "n": 60 + i * i / 2 + (i % 4) * 90 + (i > 110 ? (i - 110) * 800 : 0)]
        },
    ]

    static func lineScreens(_ m: AppModel, main: @escaping (Tab) -> Void) -> [(String, () -> Void)] {
        func chat(_ turns: [Turn], asking: Bool = false, _ more: () -> Void = {}) {
            main(.home)
            m.ask.openSources = []; m.ask.openHow = []; m.ask.openMaybe = []; m.ask.openCite = nil; m.ask.flash = nil; m.ask.peek = nil; m.ask.goTo = nil
            m.ask.turns = turns
            m.ask.asking = asking
            m.ask.askedAt = Date()
            more()
        }
        var partial = nowFull
        partial["promised"] = [[String: Any]]()
        partial["waiting"] = Array((nowFull["waiting"] as! [[String: Any]]).prefix(1))
        partial["strip"] = Array((nowFull["strip"] as! [[String: Any]]).suffix(9))
        let empty: [String: Any] = ["at": "2026-11-21T10:02:00+00:00", "waiting": [[String: Any]](), "promised": [[String: Any]](), "mind": [[String: Any]](), "strip": [[String: Any]]()]
        func exports(_ states: [String: String], detail: String = "") {
            main(.sources)
            m.requests.services = ["x", "google", "instagram", "linkedin", "chatgpt", "notion"].compactMap {
                Service(["id": $0, "name": $0, "what": "everything you posted and every message.", "state": states[$0] ?? "arrived", "detail": $0 == "linkedin" ? detail : "",
                         "asks_for": "password", "arrives": "a day", "requested_at": Date().timeIntervalSince1970 - 3 * 86400])
            }
        }
        return [
            // the exports on the sources page: nothing waiting, one on its way, one that needs them, only ones the owner said no to
            ("exports-none", { exports([:]) }),
            ("exports-one", { exports(["x": "requested"]) }),
            ("exports-needs", { exports(["linkedin": "needs_you", "google": "failed", "chatgpt": "declined"], detail: "linkedin wants the code it sent to your phone before it will prepare the file, and it asks again after ten minutes.") }),
            ("exports-declined", { exports(["chatgpt": "declined", "notion": "declined"]) }),
            // settings, sources & sync: nothing declined, one export, and one of each kind
            ("settings-declined-0", { exports([:]); main(.settings); m.settingsPane = .sync; m.settings.loaded = true; m.settings.answered = true; m.requests.services = [] }),
            ("settings-declined-1", { exports(["notion": "declined"]); m.tab = .settings; m.settingsPane = .sync; m.settings.loaded = true; m.settings.answered = true }),
            ("settings-declined-3", {
                exports(["chatgpt": "declined"]); m.tab = .settings; m.settingsPane = .sync; m.settings.loaded = true; m.settings.answered = true
                // a source tried and never switched on is not declined: it must not be listed here
                m.pending = [PendingSource(["id": "seed_ledger", "name": "A seed ledger", "kind": "folder", "how": "", "created": "2026-11-12T09:30:00Z", "rows": 0, "enabled": false])].compactMap { $0 }
                m.automation = ["com.apple.Notes": .asked, "com.apple.mail": .asked]
            }),
            ("desk-full", { main(.home); m.now.data = NowData(nowFull) }),
            ("desk-partial", { main(.home); m.now.data = NowData(partial) }),
            ("desk-empty", { main(.home); m.now.data = NowData(empty) }),
            ("desk-collapsed", { main(.home); m.saved.sidebar = false; m.now.data = NowData(nowFull) }),
            // the ribbon: looking, with nothing found yet; one message found while the answer is written; eight, one chosen
            ("ribbon-none", { chat([Turn(id: 0, q: question)], asking: true) }),
            ("ribbon-one", {
                var t = Turn(id: 0, q: question)
                t.live = Live(phase: "read", rows: 250, sources: ["whatsapp"], text: "Not yet. Sam asked about the renewal twice [1] and you have",
                              cites: [Answer.cite(source(1, "whatsapp", "sam (landlord)", "them", "the lease renewal is due on the first"), 0, prefix: "t0")!])
                chat([t], asking: true)
            }),
            ("ribbon-many", { chat([Turn(id: 0, q: question, answer: Answer(eight, tag: "t0"))]) { m.ask.pinned = Pick(turn: 0, n: 3) } }),
            // an answer as a page: at rest, with one piece of evidence chosen, and with its message unfolded in the margin
            ("notes-rest", { m.saved.sidebar = false; chat(turns(1)); m.saved.sidebar = false }),
            ("notes-pick", { chat(turns(1)) { m.ask.pinned = Pick(turn: 0, n: 2) } }),
            ("notes-open", {
                let t = turns(1)
                chat(t) {
                    m.ask.pinned = Pick(turn: 0, n: 2)
                    if let hit = t[0].answer?.cites.dropFirst().first {
                        var peek = ThreadPeek(hit: hit, turn: 0, number: 2)
                        peek.take(["title": "the allotment committee", "src": "whatsapp", "rows_total": 3, "rows": [
                            ["id": "a", "ts": "2026-11-04T10:00:00Z", "sender": "sam", "text": "the lease renewal is due on the first."],
                            ["id": "b", "ts": "2026-11-10T10:00:00Z", "sender": "sam", "text": "did you see my message about the renewal? i also need to know about the deposit.", "here": true],
                            ["id": "c", "ts": "2026-11-10T10:04:00Z", "me": true, "text": "Give me until the end of the month, please."]]])
                        m.ask.thread = peek
                        m.ask.threadInMargin = true
                    }
                }
            }),
            ("notes-many", { m.saved.sidebar = false; chat([Turn(id: 0, q: question, answer: Answer(eight, tag: "t0"))]); m.saved.sidebar = false }),
        ]
    }

    static func lineCheck(_ screen: String, _ at: String, _ size: CGSize, _ found: [ProbeInfo]) -> [String] {
        var out: [String] = []
        func has(_ n: String) -> Bool { found.contains { $0.name == n } }
        func count(_ n: String) -> Int { found.filter { $0.name == n }.count }
        let side = found.first { $0.name == "side.ground" }?.frame.maxX ?? 0
        let panel = found.first { $0.name == "refs.panel" }.map { size.width - $0.frame.minX } ?? 0
        let column = size.width - side - panel
        let m = AppModel.shared

        // the spine stands wherever the owner asks, and nothing of the page lies on it
        if screen.hasPrefix("desk-") || screen.hasPrefix("ribbon-") || screen.hasPrefix("notes-") || screen == "chat-one" || screen == "frame-3" {
            if let spine = found.first(where: { $0.name == "spine" }) {
                for p in found where !p.name.hasPrefix("spine") && !p.name.hasPrefix("side.") && !p.name.hasPrefix("bar.") && !p.name.hasPrefix("refs.") && p.frame.width > 0
                    && p.frame.minX < spine.frame.maxX - 0.5 && p.frame.maxX > spine.frame.minX && p.frame.maxY > spine.frame.minY && p.name != "desk" {
                    out.append("\(at): \(p.name) lies on the spine of years (starts at \(Int(p.frame.minX)), the spine ends at \(Int(spine.frame.maxX)))")
                }
                if !has("spine.now") { out.append("\(at): the spine does not say now") }
            } else { out.append("\(at): there is no spine of years") }
        }

        if screen.hasPrefix("ribbon-") {
            let want = ["ribbon-none": 0, "ribbon-one": 1, "ribbon-many": 8][screen] ?? 0
            if !has("ribbon.line") { out.append("\(at): the ribbon has no line") }
            if count("ribbon.dot") != want { out.append("\(at): the ribbon has \(count("ribbon.dot")) dots for \(want) pieces of evidence") }
            if let r = found.first(where: { $0.name == "ribbon" }) {
                for d in found where d.name == "ribbon.dot" && (d.frame.minX < r.frame.minX - 3 || d.frame.maxX > r.frame.maxX + 3) { out.append("\(at): a dot stands off the end of the ribbon") }
            }
            let labels = found.filter { $0.name == "ribbon.label" }
            if want > 1, labels.count < 2 { out.append("\(at): the ribbon has no date at its ends") }
            if screen == "ribbon-many", labels.count != 3 { out.append("\(at): the chosen dot has no date of its own (\(labels.count) labels)") }
            for i in labels.indices { for j in labels.indices where j > i {
                let x = labels[i].frame.intersection(labels[j].frame)
                if !x.isNull, x.width > 1, x.height > 1 { out.append("\(at): two dates of the ribbon lie on each other") }
            } }
        }

        // the page and its margin: with room, a note for every piece of evidence beside the text and no panel; without, none
        if ["chat-one", "notes-rest", "notes-pick", "notes-open", "notes-many"].contains(screen) {
            let cites = m.ask.turns.first?.answer?.cites.count ?? 0
            if column >= PageMeasure.least {
                if count("note") != cites { out.append("\(at): \(count("note")) margin notes for \(cites) pieces of evidence, in a column \(Int(column)) wide") }
                let textRight = found.filter { $0.name == "chat.answer" }.map(\.frame.maxX).max() ?? 0
                for n in found where n.name == "note" && n.frame.minX < textRight - 0.5 { out.append("\(at): a margin note starts at \(Int(n.frame.minX)), inside the text, which ends at \(Int(textRight))") }
                if let widest = found.filter({ $0.name == "chat.answer" }).map(\.frame.width).max(), widest > 482 { out.append("\(at): the page's measure is \(Int(widest)) wide: more than a line of a book") }
                if screen != "notes-many", let ys = Optional(found.filter { $0.name == "note" }.map(\.frame.minY)), let lo = ys.min(), let first = found.filter({ $0.name == "chat.answer" }).map(\.frame.minY).min(), lo < first - 8 {
                    out.append("\(at): the first note stands above the text it belongs to")
                }
                if has("refs.panel"), screen != "chat-one" { out.append("\(at): the sources panel is open beside a page that has its notes in the margin") }
                if screen == "notes-open", !has("note.thread") { out.append("\(at): the message is not unfolded under its note") }
            } else {
                if count("note") > 0 { out.append("\(at): margin notes are drawn in a column \(Int(column)) wide, which has no room for them") }
                if screen == "notes-open", !has("peek.card") { out.append("\(at): with no margin, the opened message is not in the panel") }
            }
            if !has("ribbon.line"), cites > 0 { out.append("\(at): an answer with evidence has no ribbon") }
        }

        if screen.hasPrefix("exports-") || screen.hasPrefix("sources") {
            let want: [String: (rows: Int, head: Bool, declined: Bool, acts: Int)] = ["exports-none": (0, false, false, 0), "exports-one": (1, true, false, 0),
                                                                                    "exports-needs": (2, true, true, 2), "exports-declined": (0, false, true, 0)]
            if let w = want[screen] {
                if count("export.row") != w.rows { out.append("\(at): \(count("export.row")) exports are listed, not \(w.rows): only what still needs something has a row") }
                if has("export.head") != w.head { out.append("\(at): the exports heading is \(w.head ? "missing" : "drawn over nothing")") }
                if has("export.declined") != w.declined { out.append("\(at): the line for exports the owner said no to is \(w.declined ? "missing" : "drawn though there are none")") }
                if count("export.act") != w.acts { out.append("\(at): \(count("export.act")) buttons for \(w.acts) exports that need them") }
            }
            // an export that arrived, or was never asked for, has no row anywhere on the page
            let quiet = m.requests.services.filter { $0.state == .arrived || $0.state == .idle }.count
            if count("export.row") > m.requests.services.count - quiet { out.append("\(at): an export that needs nothing has a row") }
        }

        if let want = ["settings-declined-0": 0, "settings-declined-1": 1, "settings-declined-3": 3][screen] {
            if count("setting.declined") != want { out.append("\(at): settings lists \(count("setting.declined")) declined things, not \(want)") }
            if m.declined.count != want { out.append("\(at): the model counts \(m.declined.count) declined things, not \(want)") }
        }

        if screen.hasPrefix("desk-") {
            if count("desk.col") != 3 { out.append("\(at): the desk has \(count("desk.col")) columns, not three") }
            let want = ["desk-full": 4 + 2 + 3, "desk-collapsed": 4 + 2 + 3, "desk-partial": 1 + 0 + 3, "desk-empty": 0][screen] ?? 0
            if count("desk.line") != want { out.append("\(at): the desk shows \(count("desk.line")) lines, not \(want)") }
            let quiet = ["desk-partial": 1, "desk-empty": 3][screen] ?? 0
            if count("desk.empty") != quiet { out.append("\(at): \(count("desk.empty")) empty columns say so, not \(quiet)") }
            if has("desk.strip") != (screen != "desk-empty") { out.append("\(at): the strip of months is \(has("desk.strip") ? "drawn with nothing in it" : "missing")") }
            if !has("chat.input") || !has("desk.key") { out.append("\(at): the desk has no input, or the input does not show the key") }
            if has("home.greeting") { out.append("\(at): the greeting is drawn over the desk") }
            if let input = found.first(where: { $0.name == "chat.input" }) {
                if input.frame.maxY > size.height - 8 || input.frame.maxY < size.height - 40 { out.append("\(at): the input is not docked at the foot of home (ends at \(Int(input.frame.maxY)) of \(Int(size.height)))") }
                for c in found where c.name == "desk.col.name" && c.frame.maxY > input.frame.minY { out.append("\(at): a column starts under the input") }
            }
        } else if screen.hasPrefix("home-") || screen.hasPrefix("frame-"), has("desk") {
            out.append("\(at): the desk is drawn though the engine has not said how the month stands")
        }
        return out
    }
}

/// The motions of the second pass, each drawn as twelve frames across its length into one strip, unseen: so a move
/// can be judged without a screen. `strip-<name>.png` in the folder the gate writes to. A few are measured as well.
extension LayoutTest {
    static func motionStrips(_ window: NSWindow, _ m: AppModel, out: String?) -> [String] {
        var more: [String] = []
        let all = scenarios(m)
        func set(_ name: String) { all.first { $0.0 == name }?.1() }
        Probe.moving = true
        defer { Probe.moving = false }

        func run(_ name: String, size: CGSize = CGSize(width: 920, height: 640), secs: Double, before: () -> Void, change: (Int) -> Void, check: ((Int, [ProbeInfo]) -> Void)? = nil) {
            autoreleasepool {
                FileHandle.standardError.write("motion \(name)\n".data(using: .utf8)!)
                (window.contentView as? NSHostingView<AnyView>)?.rootView = AnyView(EmptyView())
                window.contentView = nil
                before()
                window.setContentSize(size)
                NSApplication.shared.appearance = NSAppearance(named: .aqua)
                Probe.found = []
                let host = NSHostingView(rootView: AnyView(RootView().environment(m)))       // animations on
                window.contentView = host
                host.layoutSubtreeIfNeeded()
                pump(0.7)
                var frames: [NSBitmapImageRep] = [], times: [Double] = []
                let start = Date()
                for i in 0..<12 {
                    change(i)
                    // drawing a frame takes time of its own: the run loop is always given a turn, or nothing would
                    // move at all, and each frame is labelled with the time it was really drawn at
                    let wait = secs * Double(i + 1) / 12 - Date().timeIntervalSince(start)
                    pump(max(wait, 0.025))
                    host.layoutSubtreeIfNeeded()
                    check?(i, Probe.found)
                    if let rep = host.bitmapImageRepForCachingDisplay(in: host.bounds) {
                        host.cacheDisplay(in: host.bounds, to: rep)
                        frames.append(rep)
                        times.append(Date().timeIntervalSince(start))
                    }
                }
                if let out, !frames.isEmpty {
                    // two rows of six, each frame 460 wide, with the time under it
                    let w: CGFloat = 460, h = (w * size.height / size.width).rounded(), pad: CGFloat = 10, label: CGFloat = 18
                    let sheet = NSImage(size: NSSize(width: 6 * (w + pad) + pad, height: 2 * (h + label + pad) + pad), flipped: true) { rect in
                        NSColor(white: 0.82, alpha: 1).setFill()
                        rect.fill()
                        for (i, rep) in frames.enumerated() {
                            let x = pad + CGFloat(i % 6) * (w + pad), y = pad + CGFloat(i / 6) * (h + label + pad)
                            let img = NSImage(size: size)
                            img.addRepresentation(rep)
                            img.draw(in: NSRect(x: x, y: y, width: w, height: h), from: .zero, operation: .sourceOver, fraction: 1, respectFlipped: true, hints: nil)
                            ("\(name)  ·  \(Int(times[i] * 1000)) ms" as NSString).draw(at: NSPoint(x: x, y: y + h + 2), withAttributes: [
                                .font: NSFont.monospacedSystemFont(ofSize: 10, weight: .regular), .foregroundColor: NSColor(white: 0.2, alpha: 1)])
                        }
                        return true
                    }
                    if let tiff = sheet.tiffRepresentation, let rep = NSBitmapImageRep(data: tiff) {
                        try? rep.representation(using: .png, properties: [:])?.write(to: URL(fileURLWithPath: "\(out)/strip-\(name).png"))
                    }
                }
                (window.contentView as? NSHostingView<AnyView>)?.rootView = AnyView(EmptyView())
                window.contentView = nil
            }
        }

        let wide = CGSize(width: 1280, height: 760)
        let cites = Answer(eight, tag: "t0")?.cites ?? []
        let long = "Not yet. Sam asked about the renewal twice [1] and you have not written back. He first raised it on the fourth, then again six days later, when he also asked about the deposit. You did write a note with two questions for him: the renewal date, and whether the deposit carries over. Nothing in your mail mentions the lease at all."
        let words = long.split(separator: " ")
        func live(_ k: Int, text: String = "") -> Live { Live(phase: "read", rows: 250, sources: ["whatsapp"], text: text, cites: Array(cites.prefix(k))) }

        run("page", secs: 0.4, before: { set("frame-3") }, change: { if $0 == 0 { m.go(.sources) } })
        // the question lifts, the desk falls back: by 350 ms nothing of the desk is laid out, and at the end the
        // question stands once, near the top
        run("lift", secs: 0.72, before: { set("desk-full") }, change: { i in
            if i == 0 { m.ask.turns = [Turn(id: 0, q: question)]; m.ask.asking = true; m.ask.askedAt = Date() }
        }, check: { i, found in
            let desk = found.filter { $0.name == "desk.line" }.count, qs = found.filter { $0.name == "chat.question" }
            if i >= 8, desk > 0 { more.append("the question lifting, frame \(i + 1) of 12: \(desk) lines of the desk are still laid out under the conversation") }
            if i == 11, qs.count != 1 || (qs.first?.frame.minY ?? 999) > 220 { more.append("the question lifting: at the end the question is not once, at the top (\(qs.count) at \(Int(qs.first?.frame.minY ?? -1)))") }
        })
        run("ribbon", secs: 1.5, before: { set("ribbon-none") }, change: { i in
            if i % 2 == 1, !m.ask.turns.isEmpty { m.ask.turns[0].live = live((i + 1) / 2) }
        }, check: { i, found in
            let dots = found.filter { $0.name == "ribbon.dot" }.count
            if i == 11, dots != 6 { more.append("the ribbon filling: \(dots) dots at the end for 6 messages found") }
        })
        run("words", secs: 1.2, before: { set("ribbon-one") }, change: { i in
            if !m.ask.turns.isEmpty { m.ask.turns[0].live = live(1, text: words.prefix(6 + i * 5).joined(separator: " ")) }
        })
        run("notes", size: wide, secs: 0.9, before: { set("ribbon-none") }, change: { if $0 == 0 { m.ask.turns = turns(1); m.ask.asking = false } }, check: { i, found in
            if i == 11, found.filter({ $0.name == "note" }).count != 3 { more.append("the notes arriving: \(found.filter { $0.name == "note" }.count) notes at the end, not 3") }
        })
        run("lit", size: wide, secs: 0.3, before: { set("notes-rest") }, change: { if $0 == 0 { m.ask.pinned = Pick(turn: 0, n: 2) } })
        run("unfold", size: wide, secs: 0.6, before: { set("notes-pick") }, change: { i in
            guard i == 0, let hit = m.ask.turns.first?.answer?.cites.dropFirst().first else { return }
            var peek = ThreadPeek(hit: hit, turn: 0, number: 2)
            peek.take(["title": "the allotment committee", "src": "whatsapp", "rows_total": 3, "rows": [
                ["id": "a", "ts": "2026-11-04T10:00:00Z", "sender": "sam", "text": "the lease renewal is due on the first."],
                ["id": "b", "ts": "2026-11-10T10:00:00Z", "sender": "sam", "text": "did you see my message about the renewal? i also need to know about the deposit.", "here": true],
                ["id": "c", "ts": "2026-11-10T10:04:00Z", "me": true, "text": "Give me until the end of the month, please."]]])
            withAnimation(Motion.unfold(false)) { m.ask.thread = peek; m.ask.threadInMargin = true }
        })
        run("desk", secs: 1.0, before: { set("frame-3") }, change: { if $0 == 0 { m.now.data = NowData(nowFull) } })
        // the input, when what is typed runs to more lines: the box grows on a spring. it never shrinks on the way, it
        // ends at least four lines taller, and as tall as its text. on the desk and on the plain home
        for (name, screen) in [("input", "desk-full"), ("input-plain", "frame-3")] {
            var first: CGFloat = 0, last: CGFloat = 0
            run(name, secs: 0.6, before: { set(screen) }, change: { i in
                if i == 0 {
                    first = Probe.found.first { $0.name == "chat.input" }?.frame.height ?? 0
                    last = first
                    m.ask.homeDraft = Array(repeating: "what did sam say about the lease, and what did i tell him about the deposit", count: 4).joined(separator: "\n")
                }
            }, check: { i, found in
                let h = found.first { $0.name == "chat.input" }?.frame.height ?? 0
                if h < last - 1 { more.append("the input growing (\(name)), frame \(i + 1): the box got shorter on its way to taller (\(Int(last)) to \(Int(h)))") }
                last = h
                if i == 11 {
                    if h < first + 40 { more.append("the input growing (\(name)): the box did not grow for four more lines (\(Int(first)) to \(Int(h)))") }
                    if let text = found.first(where: { $0.name == "chat.input.text" }), text.ideal.height > h { more.append("the input growing (\(name)): the box is shorter than what is typed in it") }
                }
            })
            m.ask.homeDraft = ""
        }
        m.ask.homeDraft = ""
        set("frame-0")
        return more
    }
}
