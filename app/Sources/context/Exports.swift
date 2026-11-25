import AppKit
import CoreImage
import SwiftUI

// Exports, the nightly catch-up and telegram's sign-in, from the engine's own commands (ctx/serve.py):
//   exports          {}                                   -> {"rows": [{"id","name","state": denied|waiting on you|asked|failed|in|idle,
//                                                              "show","detail","restart","every","next_in","asks_for"}], "reminders", "done"}
//   exports-restart  {"service": id}                      -> {"rows"} | {"error"}
//   exports-every    {"service": id, "every": weekly|monthly|off} -> {"rows"} | {"error"}
//   catchup-status   {} | {"fresh": true}                 -> {"nightly_calls","last_night","tonight","behind","nights_to_catch_up","may_run_now","why_not"}
//   telegram-login   {}   streams {"event":"qr","qr": address, "n", "of"} each time the code renews, then {"result": {"state": ok|needs_you|cannot, "detail"}}
// An engine without `exports` leaves the list as the older `request` rows give it.

struct ExportItem: Identifiable, Equatable {
    var id: String
    var name: String
    var state: String           // denied, waiting on you, asked, failed, in, idle
    var show: Bool
    var detail: String
    var restart: Bool
    var every: String
    var nextIn: Double?
    var asksFor: String

    init?(_ d: [String: Any]) {
        guard let id = d["id"] as? String, !id.isEmpty else { return nil }
        self.id = id
        name = (d["name"] as? String ?? id).lowercased()
        state = d["state"] as? String ?? "idle"
        show = d["show"] as? Bool ?? false
        detail = (d["detail"] as? String ?? "").lowercased()
        restart = d["restart"] as? Bool ?? false
        every = d["every"] as? String ?? ""
        nextIn = (d["next_in"] as? Double) ?? (d["next_in"] as? Int).map(Double.init)
        asksFor = d["asks_for"] as? String ?? ""
    }

    /// One whole sentence for its row.
    var sentence: String {
        if !detail.isEmpty { return detail.hasSuffix(".") ? detail : detail + "." }
        switch state {
        case "asked":
            let next = nextIn.map { $0 >= 86400 ? "about \(Int($0 / 86400)) days" : "about \(max(1, Int($0 / 3600))) hours" }
            return "asked. \(name) sends the file as a download; context reads it from downloads when it lands." + (next.map { " it looks again in \($0)." } ?? "")
        case "waiting on you": return "\(name) is waiting for you in the browser\(asksFor.isEmpty || asksFor == "nothing" ? "" : ": it wants a \(asksFor)")."
        case "failed": return "\(name) did not take the request."
        case "denied": return "you chose not to ask \(name) for your archive. nothing was requested."
        default: return ""
        }
    }
    /// "asked again monthly. next in about 12 days." off has no next date.
    static func cadence(_ r: ExportItem) -> String {
        if r.every == "off" { return "not asked again." }
        let next = r.nextIn.map { $0 <= 0 ? " due now." : ($0 >= 86400 ? " next in about \(Int(($0 / 86400).rounded())) day\(Int(($0 / 86400).rounded()) == 1 ? "" : "s")." : " next in about \(max(1, Int($0 / 3600))) hours.") } ?? ""
        return "asked again \(r.every.isEmpty ? "monthly" : r.every)." + next
    }
    var word: String { ["asked": "on its way", "waiting on you": "needs you", "failed": "did not work", "denied": "denied", "in": "in", "idle": "not asked"][state] ?? state }
}

/// What the browser can do for context, as the engine's `exports` says: two abilities, not one. The extension reads
/// what the owner is signed in to; asking a site for an export needs page scripting as well.
struct BrowserAbility: Equatable {
    var name = ""
    var canRead = false
    var readsThrough = ""           // extension, page scripting, or ""
    var canRequest = false
    var requestNeeds = ""           // what to switch on, when it cannot ask
    init?(_ any: Any?) {
        guard let d = any as? [String: Any], d["can_read"] != nil || d["can_request"] != nil else { return nil }
        name = (d["name"] as? String ?? "").lowercased()
        canRead = d["can_read"] as? Bool ?? false
        readsThrough = d["reads_through"] as? String ?? ""
        canRequest = d["can_request"] as? Bool ?? false
        requestNeeds = (d["request_needs"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    }
}

struct Catchup: Equatable {
    var nightly = 0
    var nights: Double = 0
    var mayRun = false
    var whyNot = ""
    var lastNight = Night()
    var tonight = Night()
    var conversations = 0, readingCalls = 0, pages = 0, pageCalls = 0

    /// One night's work, as catchup.py records it: {"night", "calls", "conversations", "pages", "stopped"}.
    struct Night: Equatable {
        var night = ""
        var calls = 0
        var conversations = 0
        var pages = 0
        var stopped = ""
        init() {}
        init(_ any: Any?) {
            let d = any as? [String: Any] ?? [:]
            night = d["night"] as? String ?? ""
            calls = d["calls"] as? Int ?? 0
            conversations = d["conversations"] as? Int ?? 0
            pages = d["pages"] as? Int ?? 0
            stopped = (d["stopped"] as? String ?? "").lowercased()
        }
        /// "20 nov: 40 calls. 31 conversations read, 4 pages written."
        func sentence(none: String) -> String {
            guard !night.isEmpty else { return none }
            let did = [conversations > 0 ? "\(Words.count(conversations)) conversation\(conversations == 1 ? "" : "s") read" : "", pages > 0 ? "\(Words.count(pages)) page\(pages == 1 ? "" : "s") written" : ""].filter { !$0.isEmpty }
            return "\(Words.day(night)): \(Words.count(calls)) call\(calls == 1 ? "" : "s"). " + (did.isEmpty ? "nothing was read or written." : did.joined(separator: ", ") + ".")
                + (stopped.isEmpty || stopped == "budget" ? "" : " it stopped: \(stopped).")
        }
    }

    init?(_ any: Any?) {
        guard let d = any as? [String: Any], d["nightly_calls"] != nil else { return nil }
        nightly = d["nightly_calls"] as? Int ?? 0
        nights = (d["nights_to_catch_up"] as? Double) ?? Double(d["nights_to_catch_up"] as? Int ?? 0)
        mayRun = d["may_run_now"] as? Bool ?? false
        whyNot = (d["why_not"] as? String ?? "").lowercased()
        lastNight = Night(d["last_night"])
        tonight = Night(d["tonight"])
        let b = d["behind"] as? [String: Any] ?? [:]
        conversations = b["conversations"] as? Int ?? 0
        readingCalls = b["reading_calls"] as? Int ?? 0
        pages = b["wiki_pages"] as? Int ?? 0
        pageCalls = b["wiki_calls"] as? Int ?? 0
    }

    /// "up to 40 calls a night on your own plan."
    var sentence: String {
        "the read-through and about you are brought up to date at night, up to \(Words.count(nightly)) calls a night on your own plan." + (mayRun || whyNot.isEmpty ? "" : " not running now: " + whyNot + (whyNot.hasSuffix(".") ? "" : "."))
    }

    /// "250 conversations to read (about 260 calls) and 30 pages to write (about 50 calls). about 3 nights."
    var behind: String {
        let parts = [conversations > 0 ? "\(Words.count(conversations)) conversation\(conversations == 1 ? "" : "s") to read (about \(Words.count(readingCalls)) calls)" : "",
                     pages > 0 ? "\(Words.count(pages)) page\(pages == 1 ? "" : "s") to write (about \(Words.count(pageCalls)) calls)" : ""].filter { !$0.isEmpty }
        guard !parts.isEmpty else { return "nothing. it is all read and written." }
        let n = Int(nights.rounded(.up))
        return parts.joined(separator: " and ") + "." + (n > 0 ? " about \(n) night\(n == 1 ? "" : "s")." : "")
    }
}

@Observable final class ExportsModel {
    var rows: [ExportItem]?         // nil until the engine has answered `exports`; stays nil with an engine that has no such command
    var busy: Set<String> = []
    var fault: [String: String] = [:]
    var catchup: Catchup?
    var browser: BrowserAbility?    // from `exports`: reading, and asking sites for exports, each by itself
    // telegram's sign-in, in the app: the code to scan, and how it ended
    var qr: String?
    var qrN = 0
    var qrOf = 0
    var telegramSaid = ""           // the engine's one sentence when it ends
    var telegramState = ""          // ok, needs_you, cannot; "" while it runs or before it starts
    var telegramOn = false
    var telegramTerminal = false    // it ended on something only Terminal can do: a two-step password is typed there, never here
    @ObservationIgnored private var stream: Int?
    @ObservationIgnored weak var engine: Engine?

    var shown: [ExportItem] { (rows ?? []).filter { $0.show && $0.state != "denied" } }
    var denied: [ExportItem] { (rows ?? []).filter { $0.state == "denied" } }

    private func take(_ any: Any?, for id: String = "") {
        guard let d = any as? [String: Any] else { return }
        if let e = d["error"] as? String, !id.isEmpty { fault[id] = e.lowercased(); return }
        if let list = d["rows"] as? [[String: Any]] { rows = list.compactMap { ExportItem($0) }; if !id.isEmpty { fault[id] = nil } }
        if let b = BrowserAbility(d["browser"]) { browser = b }
    }

    func load(_ engine: Engine) {
        self.engine = engine
        guard !Probe.on else { return }
        engine.client.call(["cmd": "exports"], timeout: 30) { [weak self] reply in self?.take(reply) }
        engine.client.call(["cmd": "catchup-status"], timeout: 30) { [weak self] reply in if let c = Catchup(reply) { self?.catchup = c } }
    }

    func restart(_ id: String) {
        guard !Probe.on, let engine, !busy.contains(id) else { return }
        busy.insert(id)
        engine.client.call(["cmd": "exports-restart", "service": id], timeout: 30) { [weak self] reply in self?.busy.remove(id); self?.take(reply, for: id) }
    }

    func every(_ id: String, _ every: String) {
        if let i = rows?.firstIndex(where: { $0.id == id }) { rows?[i].every = every }
        guard !Probe.on, let engine else { return }
        engine.client.call(["cmd": "exports-every", "service": id, "every": every], timeout: 30) { [weak self] reply in self?.take(reply, for: id) }
    }

    /// Telegram's sign-in without a terminal: the engine sends an address to draw as a code each time it renews, then
    /// how it ended. Nothing is typed here; when telegram wants a two-step password the engine says so and where.
    /// False when the warm engine is not there to ask: the caller falls back to the terminal.
    func telegramLogin() -> Bool {
        guard !Probe.on, let warm = engine?.client.warmEngine else { return false }
        telegramCancel()
        telegramOn = true; qr = nil; telegramSaid = ""; telegramState = ""; telegramTerminal = false
        var result: [String: Any]?
        stream = warm.send(["cmd": "telegram-login"], open: true, event: { [weak self] d in
            if d["event"] as? String == "qr", let address = d["qr"] as? String {
                self?.qr = address; self?.qrN = d["n"] as? Int ?? 0; self?.qrOf = d["of"] as? Int ?? 0
            }
            if let r = d["result"] as? [String: Any] { result = r }
        }, end: { [weak self] in
            guard let self else { return }
            self.stream = nil
            self.qr = nil
            self.telegramState = result?["state"] as? String ?? "cannot"
            // the engine's sentence, its command for a working copy turned into the button that runs the engine in the app
            let said = Blocked.telegramSaid(result?["detail"] as? String ?? "the sign-in stopped before telegram answered. try again, or press open terminal to sign in there.")
            self.telegramSaid = said.text
            self.telegramTerminal = said.terminal || result == nil
            if self.telegramState == "ok", let e = self.engine { e.readRun.remove("telegram"); e.read("telegram", first: true) }
        })
        return stream != nil
    }

    func telegramCancel() {
        if let id = stream, let warm = engine?.client.warmEngine { warm.cancel(id); warm.finish(id) }
        stream = nil
    }

    func telegramClose() { telegramCancel(); telegramOn = false; qr = nil; telegramSaid = ""; telegramState = ""; telegramTerminal = false }

    func reset() { rows = nil; busy = []; fault = [:]; catchup = nil; browser = nil; qr = nil; qrN = 0; qrOf = 0; telegramSaid = ""; telegramState = ""; telegramOn = false; telegramTerminal = false }
}

/// An address drawn as a code to scan, in the page's own ink on its own paper.
struct QRCode: View {
    let text: String
    var side: CGFloat = 148

    static func image(_ text: String) -> NSImage? {
        guard let f = CIFilter(name: "CIQRCodeGenerator") else { return nil }
        f.setValue(Data(text.utf8), forKey: "inputMessage")
        f.setValue("M", forKey: "inputCorrectionLevel")
        guard let out = f.outputImage?.transformed(by: CGAffineTransform(scaleX: 8, y: 8)) else { return nil }
        let rep = NSCIImageRep(ciImage: out)
        let img = NSImage(size: rep.size)
        img.addRepresentation(rep)
        return img
    }

    var body: some View {
        Group {
            if let img = QRCode.image(text) { Image(nsImage: img).interpolation(.none).resizable() } else { Color.clear }
        }
        .frame(width: side, height: side)
        .padding(10)
        .background(Color.white, in: RoundedRectangle(cornerRadius: Radius.row, style: .continuous))     // a code is black on white, in light and in dark, or a phone will not read it
        .accessibilityLabel("the code to scan with telegram on your phone")
    }
}

/// Telegram's sign-in, at the top of the sources page while it is open: what to do on the phone, the code, and how it ended.
struct TelegramCard: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let x = model.exports
        if x.telegramOn {
            HStack(alignment: .top, spacing: Space.l) {
                VStack(alignment: .leading, spacing: Space.s) {
                    HStack(spacing: 7) {
                        SourceIcon(id: "telegram", size: 16)
                        Text("sign in to telegram").font(.system(size: Face.body, weight: .medium)).foregroundStyle(Ink.ink)
                    }
                    if x.telegramState.isEmpty {
                        Text("on your phone: telegram, settings, devices, link desktop device. then point it at the code. nothing is typed here.")
                            .font(.system(size: Face.label)).foregroundStyle(Ink.soft).lineSpacing(2.5).fixedSize(horizontal: false, vertical: true)
                            .probe("tg.how", .text, scrolls: true)
                        HStack(spacing: 8) {
                            if x.qr == nil { Spinner(size: 10) }
                            Text(x.qr == nil ? "asking telegram for a code" : (x.qrOf > 0 ? "code \(x.qrN) of \(x.qrOf). it renews by itself." : "the code renews by itself."))
                                .font(Face.meta).foregroundStyle(Ink.faint)
                        }
                    } else {
                        // how it ended, in the engine's own sentence. a two-step password is asked for in a terminal, never here
                        Text(x.telegramSaid).font(.system(size: Face.label)).foregroundStyle(x.telegramState == "ok" ? Ink.ink : Ink.soft).lineSpacing(2.5)
                            .fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
                            .probe("tg.said", .text, scrolls: true)
                    }
                    HStack(spacing: Space.l) {
                        if !x.telegramState.isEmpty, x.telegramState != "ok" {
                            Button("try again") { _ = x.telegramLogin() }.buttonStyle(SetButtonStyle()).probe("tg.again", .button, scrolls: true)
                        }
                        if x.telegramTerminal, x.telegramState != "ok" {
                            Button("open terminal") { Blocked.telegramTerminal() }.buttonStyle(SetButtonStyle())
                                .help("starts telegram's sign-in in terminal, with the engine inside this app")
                                .probe("tg.terminal", .button, scrolls: true)
                        }
                        Button(x.telegramState.isEmpty ? "stop" : "close") { x.telegramClose() }.buttonStyle(QuietButton(size: Face.small))
                            .accessibilityLabel(x.telegramState.isEmpty ? "stop signing in to telegram" : "close")
                    }
                    .padding(.top, 2)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                if let qr = x.qr, x.telegramState.isEmpty { QRCode(text: qr).probe("tg.qr", .block, scrolls: true) }
            }
            .padding(Space.l)
            .background(Ink.raised, in: RoundedRectangle(cornerRadius: Radius.card, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: Radius.card, style: .continuous).strokeBorder(Ink.line, lineWidth: 1))
            .padding(.top, Space.l).padding(.bottom, Space.s)
            .probe("tg.card", .block, scrolls: true)
        }
    }
}

/// One export that still needs something, from the engine's `exports` rows.
struct ExportItemRow: View {
    @Environment(AppModel.self) private var model
    let item: ExportItem

    var body: some View {
        let x = model.exports, busy = x.busy.contains(item.id)
        let needs = item.state == "waiting on you" || item.state == "failed"
        HStack(alignment: .center, spacing: Space.m) {
            VStack(alignment: .leading, spacing: 3) {
                HStack(alignment: .firstTextBaseline, spacing: Space.s) {
                    SourceIcon.inline(id: Service(["id": item.id, "name": item.name])?.mark.id ?? item.id, font: .systemFont(ofSize: 15, weight: .medium), name: item.name)
                    Text(item.name).font(.system(size: Face.body, weight: .medium)).foregroundStyle(Ink.ink).lineLimit(1)
                    Pill(text: busy ? "asking" : item.word, tone: needs && !busy ? .warn : .quiet)
                }
                Text(x.fault[item.id] ?? item.sentence).font(.system(size: Face.label)).foregroundStyle(Ink.soft).lineSpacing(2)
                    .fixedSize(horizontal: false, vertical: true).padding(.leading, 24)
                    .probe("export.line", .text, scrolls: true)
            }
            Spacer(minLength: Space.s)
            if !busy, needs {
                // waiting on them: the site is opened where the owner is signed in. failed: asked again on the next look
                Button(item.state == "failed" ? "try again" : "open it") { if item.state == "failed" { x.restart(item.id) } else { model.requests.request(item.id) } }
                    .buttonStyle(SetButtonStyle())
                    .accessibilityLabel(item.state == "failed" ? "ask \(item.name) again" : "open \(item.name) in the browser")
                    .probe("export.act", .button, scrolls: true)
            }
        }
        .padding(.vertical, 10)
        .overlay(alignment: .bottom) { Rectangle().fill(Ink.line).frame(height: 1) }
        .probe("export.row", .block, group: "export.rows", scrolls: true)
    }
}

/// In settings, sources & sync: how often each export comes round, and the nightly catch-up.
struct ExportsEveryCard: View {
    @Environment(AppModel.self) private var model
    var body: some View {
        let x = model.exports
        if let rows = x.rows, !rows.isEmpty {
            SetCard(title: "exports, how often", note: "a site's archive goes stale. context asks again on this round, and you are asked for one step at most.") {
                ForEach(Array(rows.enumerated()), id: \.element.id) { i, r in
                    SetRow(title: r.name, about: x.fault[r.id] ?? ExportItem.cadence(r), pill: r.word,
                           tone: r.state == "waiting on you" || r.state == "failed" ? .warn : (r.state == "in" ? .good : .quiet), last: i == rows.count - 1) {
                        SetMenu(word: r.every.isEmpty ? "choose" : r.every, label: "how often \(r.name) is asked for") {
                            ForEach(["weekly", "monthly", "off"], id: \.self) { e in
                                Toggle(isOn: Binding(get: { r.every == e }, set: { _ in x.every(r.id, e) })) { Text(e) }
                            }
                        }
                    }
                    .probe("setting.every", .block, scrolls: true)
                }
            }
        }
        if let c = x.catchup {
            SetCard(title: "at night") {
                SetRow(title: "catching up", about: c.sentence, pill: c.mayRun ? "may run now" : "waits", tone: .quiet)
                    .probe("setting.catchup", .block, scrolls: true)
                SetRow(title: "last night", about: c.lastNight.sentence(none: "nothing ran last night."))
                    .probe("setting.night", .block, scrolls: true)
                SetRow(title: "tonight", about: c.tonight.sentence(none: "nothing yet tonight."))
                    .probe("setting.night", .block, scrolls: true)
                SetRow(title: "still to do", about: c.behind, last: true)
                    .probe("setting.behind", .block, scrolls: true)
            }
        }
    }
}

// MARK: in the gate

extension LayoutTest {
    static func exportScreens(_ m: AppModel, main: @escaping (Tab) -> Void) -> [(String, () -> Void)] {
        func rows(_ states: [String: String], detail: String = "") -> [ExportItem] {
            ["x", "google", "instagram", "linkedin", "chatgpt", "notion"].compactMap { id in
                let st = states[id] ?? "in"
                return ExportItem(["id": id, "name": id, "state": st, "show": ["denied", "waiting on you", "asked", "failed"].contains(st), "detail": st == "waiting on you" ? detail : "",
                                   "restart": st == "denied" || st == "failed", "every": id == "notion" ? "off" : (id == "google" ? "weekly" : "monthly"), "next_in": id == "notion" ? NSNull() : (1_036_800.0 as Any), "asks_for": "password"])
            }
        }
        func sources(_ states: [String: String], detail: String = "") { main(.sources); m.requests.services = []; m.exports.rows = rows(states, detail: detail) }
        return [
            // the engine's own export rows: all in (no section), one asked, one that waits on them and one that failed, one the owner denied
            ("xrows-none", { sources([:]) }),
            ("xrows-asked", { sources(["x": "asked"]) }),
            ("xrows-needs", { sources(["linkedin": "waiting on you", "google": "failed", "chatgpt": "denied"], detail: "linkedin has your archive ready. open it and press download: it asks for your password first.") }),
            ("xrows-denied", { sources(["chatgpt": "denied", "notion": "denied"]) }),
            // settings: how often each comes round, the nightly catch-up, and a denied export with its way back
            ("settings-exports", {
                main(.settings); m.settingsPane = .sync; m.settings.loaded = true; m.settings.answered = true
                m.exports.rows = rows(["linkedin": "waiting on you", "chatgpt": "denied"])
                m.exports.catchup = Catchup(["nightly_calls": 40, "nights_to_catch_up": 3, "may_run_now": false, "why_not": "it is not night yet, and your plan was used in the last hour",
                                             "last_night": ["night": "2026-11-19", "calls": 40, "conversations": 31, "pages": 4, "stopped": "budget"],
                                             "tonight": [String: Any](), "behind": ["conversations": 250, "reading_calls": 260, "wiki_pages": 30, "wiki_calls": 50]])
            }),
            // the browser's two abilities: the extension alone reads but cannot ask a site for an export; with page scripting it can
            ("settings-browser-extension", {
                main(.settings); m.settingsPane = .permissions; m.settings.loaded = true; m.settings.answered = true; m.bridge = true
                m.exports.browser = BrowserAbility(["name": "your browser", "can_read": true, "reads_through": "extension", "can_request": false,
                                                    "request_needs": "in your browser: view, developer, allow javascript from apple events. context then asks each site for your archive by itself."])
            }),
            ("settings-browser-both", {
                main(.settings); m.settingsPane = .permissions; m.settings.loaded = true; m.settings.answered = true; m.bridge = true
                m.exports.browser = BrowserAbility(["name": "your browser", "can_read": true, "reads_through": "page scripting", "can_request": true, "request_needs": ""])
            }),
            // telegram's sign-in in the app: asking for a code, the code, signed in, and the two-step password said plainly
            ("tg-asking", { main(.sources); m.exports.telegramOn = true }),
            ("tg-code", { main(.sources); m.exports.telegramOn = true; m.exports.qr = "tg://login?token=AQJ3made-up-token-for-the-layout-gate-only-0000"; m.exports.qrN = 2; m.exports.qrOf = 8 }),
            ("tg-ok", { main(.sources); m.exports.telegramOn = true; m.exports.telegramState = "ok"; m.exports.telegramSaid = "signed in to telegram" }),
            ("tg-password", { main(.sources); m.exports.telegramOn = true; m.exports.telegramState = "needs_you"
                              // the engine's own sentence, as the app turns it into what to do here
                              (m.exports.telegramSaid, m.exports.telegramTerminal) = Blocked.telegramSaid("telegram wants your two-step password. it is typed in a terminal, never here: press open terminal on the sign-in card in the app's sources page") }),
        ]
    }

    static func exportCheck(_ screen: String, _ at: String, _ found: [ProbeInfo]) -> [String] {
        var out: [String] = []
        func has(_ n: String) -> Bool { found.contains { $0.name == n } }
        func count(_ n: String) -> Int { found.filter { $0.name == n }.count }
        let want: [String: (rows: Int, head: Bool, declined: Bool, acts: Int)] = ["xrows-none": (0, false, false, 0), "xrows-asked": (1, true, false, 0), "xrows-needs": (2, true, true, 2), "xrows-denied": (0, false, true, 0)]
        if let w = want[screen] {
            if count("export.row") != w.rows { out.append("\(at): \(count("export.row")) exports have a row, not \(w.rows): one that is in, idle or denied has none") }
            if has("export.head") != w.head { out.append("\(at): the exports heading is \(w.head ? "missing" : "drawn over nothing")") }
            if has("export.declined") != w.declined { out.append("\(at): the line for denied exports is \(w.declined ? "missing" : "drawn though there are none")") }
            if count("export.act") != w.acts { out.append("\(at): \(count("export.act")) buttons for \(w.acts) exports that need them") }
        }
        switch screen {
        case "settings-browser-extension", "settings-browser-both":
            if count("setting.ask") != 1 { out.append("\(at): asking sites for exports is not shown by itself beside reading (\(count("setting.ask")))") }
            if AppModel.shared.canAskExports != (screen == "settings-browser-both") { out.append("\(at): the app has the browser's two abilities the wrong way round") }
        case "settings-exports":
            if count("setting.every") != 6 || !has("setting.catchup") || count("setting.night") != 2 || !has("setting.behind") { out.append("\(at): settings does not list how often each of six exports comes round, or the nightly catch-up") }
            if count("setting.declined") != 1 { out.append("\(at): the denied export is not listed with its way back") }
        case "tg-asking": if !has("tg.card") || has("tg.qr") { out.append("\(at): telegram's sign-in shows a code before it has one, or no card") }
        case "tg-code": if !has("tg.qr") || !has("tg.how") { out.append("\(at): telegram's sign-in has no code to scan or does not say what to do") }
        case "tg-ok": if !has("tg.said") || has("tg.qr") || has("tg.again") { out.append("\(at): signed in, the card still shows a code or asks to try again") }
        case "tg-password": if !has("tg.said") || !has("tg.again") || !has("tg.terminal") { out.append("\(at): the two-step password is not said, or there is no way to try again or to open terminal") }
            if AppModel.shared.exports.telegramSaid.contains("python3 -m ctx") { out.append("\(at): telegram's sign-in tells an installed app to run the engine from a working copy") }
        default: break
        }
        return out
    }
}
