import AppKit
import ApplicationServices
import IOKit.pwr_mgt
import Observation
import SwiftUI

/// Why a panel may drop from the menu-bar mark. Nothing else may: a thing that only waits on them (a code, a
/// password, the extension) is listed under "need you" and never raises a panel.
enum PingKind: String, Codable, CaseIterable {
    case answer         // an answer the owner left running is ready
    case arrived        // an export the owner asked for has arrived and was read in
    case finished       // the first read, or the wiki, finished
    case lost           // a permission the owner gave earlier is gone
    case waits          // waits on them: listed, never raised

    static let raised: [PingKind] = [.answer, .arrived, .finished, .lost]
    var word: String {
        switch self {
        case .answer: return "an answer is ready"
        case .arrived: return "an export arrived"
        case .finished: return "a long read finished"
        case .lost: return "a permission was lost"
        case .waits: return "something waits on you"
        }
    }
    var about: String {
        switch self {
        case .answer: return "an answer you left running, once it is written"
        case .arrived: return "an export you asked for, once it has been read in"
        case .finished: return "the first read of your mac, or the wiki, when it is done"
        case .lost: return "full disk access or accessibility switched off after you gave it"
        case .waits: return ""
        }
    }
    /// On unless the owner says otherwise: only the two the owner started themselves.
    var onByDefault: Bool { self == .answer || self == .arrived }
}

/// One thing to tell them, or one thing that waits on them, with the one click that settles it.
struct Ping: Identifiable, Equatable, Codable {
    enum Fix: String, Codable { case chat, sources, profile, disk, titles, scripting, browser, window }
    var key: String             // source id | state | the fact that changed. one panel per key, ever
    var kind: PingKind
    var src = ""                // the source it is about, for its icon
    var text: String
    var action: String
    var fix: Fix = .window
    var target = ""             // the chat to open
    var brief = ""              // a few words for it when it shares a panel: "an answer", "x archive"
    var why = ""                // why it fired, for the list in settings
    var notBefore: Double = 0   // put off until then with "not now"
    var keys: [String] = []     // several merged into one panel: every key it stands for
    var id: String { key }
    var all: [String] { keys.isEmpty ? [key] : keys }
}

/// One line of "the last ten pings".
struct PingNote: Codable, Equatable, Identifiable {
    var at: Double
    var kind: String
    var text: String
    var why: String
    var id: String { "\(at)|\(text)" }
}

/// What has been said and what the owner said back, kept in app.json.
struct PingBook: Codable, Equatable {
    var shown: [String: Double] = [:]       // key -> when its panel went up
    var snoozes: [String: Int] = [:]        // key -> how many times the owner said "not now"
    var pending: [Ping] = []                // raised, waiting for a moment that is allowed
    var fired: [Double] = []                // when each panel went up, for the hour and the day
    var last: [PingNote] = []               // the last ten, newest first
    var kinds: [String: Bool] = [:]         // a kind the owner switched themselves

    init() {}
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        shown = (try? c.decode([String: Double].self, forKey: .shown)) ?? [:]
        snoozes = (try? c.decode([String: Int].self, forKey: .snoozes)) ?? [:]
        pending = (try? c.decode([Ping].self, forKey: .pending)) ?? []
        fired = (try? c.decode([Double].self, forKey: .fired)) ?? []
        last = (try? c.decode([PingNote].self, forKey: .last)) ?? []
        kinds = (try? c.decode([String: Bool].self, forKey: .kinds)) ?? [:]
    }

    func on(_ k: PingKind) -> Bool { k != .waits && (kinds[k.rawValue] ?? k.onByDefault) }
}

/// The rules, with no clock and no screen of their own, so the check can run them on a made-up day.
enum PingPolicy {
    static let perHour = 1, perDay = 3
    static let snooze: TimeInterval = 24 * 3600
    static let typing: TimeInterval = 30

    struct World {
        var now: Date
        var typedElsewhere: TimeInterval? = nil     // seconds since a key was pressed in another app
        var fullScreen = false                      // the app in front fills the screen
        var busy = false                            // a call or a film holds the display
        var calendar = Calendar.current
    }

    /// Why no panel may go up right now, or nil when one may.
    static func held(_ w: World, _ book: PingBook) -> String? {
        let hour = w.calendar.component(.hour, from: w.now)
        if hour >= 23 || hour < 8 { return "quiet hours" }
        if w.fullScreen { return "a full-screen app is in front" }
        if w.busy { return "a call or a film is on" }
        if let t = w.typedElsewhere, t < typing { return "you are typing in another app" }
        let now = w.now.timeIntervalSince1970
        if book.fired.filter({ now - $0 < 3600 }).count >= perHour { return "one an hour" }
        if book.fired.filter({ now - $0 < 86400 }).count >= perDay { return "three a day" }
        return nil
    }

    /// Whether this key may still be raised: never shown, or put off once and not yet shown again.
    static func open(_ key: String, _ book: PingBook) -> Bool {
        if book.pending.contains(where: { $0.all.contains(key) }) { return false }
        return book.shown[key] == nil
    }

    /// Takes a new thing in, unless its kind is off or its key has been used. Returns whether it was taken.
    @discardableResult static func raise(_ p: Ping, _ book: inout PingBook) -> Bool {
        guard book.on(p.kind), open(p.key, book) else { return false }
        book.pending.append(p)
        return true
    }

    /// The panel to put up now, if any: everything that is due, as one. The book is marked as it is taken.
    static func next(_ w: World, _ book: inout PingBook) -> Ping? {
        let now = w.now.timeIntervalSince1970
        book.fired.removeAll { now - $0 >= 86400 }
        let due = book.pending.filter { $0.notBefore <= now && book.on($0.kind) }
        guard !due.isEmpty, held(w, book) == nil else { return nil }
        book.pending.removeAll { p in due.contains { $0.key == p.key } }
        let p = merge(due)
        for k in p.all { book.shown[k] = now }
        book.fired.append(now)
        for d in due { book.last.insert(PingNote(at: now, kind: d.kind.rawValue, text: d.text, why: d.why), at: 0) }
        book.last = Array(book.last.prefix(10))
        return p
    }

    /// Several things due at once are one panel: "3 things are ready".
    static func merge(_ due: [Ping]) -> Ping {
        guard due.count > 1, var p = due.first else { return due[0] }
        p.keys = due.flatMap(\.all)
        p.key = p.keys.joined(separator: "+")
        let names = due.prefix(3).map { $0.brief.isEmpty ? $0.kind.word : $0.brief } + (due.count > 3 ? ["\(due.count - 3) more"] : [])
        p.text = "\(due.count) things are ready: " + names.dropLast().joined(separator: ", ") + " and " + (names.last ?? "") + "."
        p.action = "open context"
        p.fix = .window
        p.src = Set(due.map(\.src)).count == 1 ? p.src : ""
        return p
    }

    /// "not now": it may come back once, a day later. Said twice, it never raises a panel again by itself.
    static func notNow(_ p: Ping, _ book: inout PingBook, now: Date) {
        for k in p.all {
            let n = (book.snoozes[k] ?? 0) + 1
            book.snoozes[k] = n
            guard n < 2, p.all.count == 1 else { continue }
            book.shown[k] = nil
            var again = p
            again.notBefore = now.timeIntervalSince1970 + snooze
            book.pending.append(again)
        }
    }

    /// The thing itself changed (the permission came back, the chat was read): its key is free again, and nothing waits for it.
    static func forget(_ prefix: String, _ book: inout PingBook) {
        book.shown = book.shown.filter { !$0.key.hasPrefix(prefix) }
        book.snoozes = book.snoozes.filter { !$0.key.hasPrefix(prefix) }
        book.pending.removeAll { $0.key.hasPrefix(prefix) }
    }

    /// Runs the rules on a made-up day: one key shows once, one an hour, three a day, nothing at night.
    static func faults() -> [String] {
        var out: [String] = []
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = TimeZone(identifier: "UTC")!
        func at(_ h: Int, _ m: Int = 0, day: Int = 14) -> World {
            World(now: cal.date(from: DateComponents(year: 2026, month: 11, day: day, hour: h, minute: m))!, calendar: cal)
        }
        func ping(_ key: String, _ kind: PingKind = .answer) -> Ping { Ping(key: key, kind: kind, text: key, action: "open") }
        var b = PingBook()
        raise(ping("chat:a|answered|1"), &b)
        if next(at(10), &b)?.key != "chat:a|answered|1" { out.append("pings: a new answer does not raise a panel") }
        if raise(ping("chat:a|answered|1"), &b) || next(at(12), &b) != nil { out.append("pings: the same key showed twice") }
        raise(ping("chat:b|answered|1"), &b)
        raise(ping("chat:b|answered|1"), &b)
        if b.pending.count != 1 { out.append("pings: the same key waits twice") }
        b = PingBook()
        raise(ping("k1"), &b); _ = next(at(10), &b)
        raise(ping("k2"), &b)
        if next(at(10, 40), &b) != nil { out.append("pings: two panels inside one hour") }
        if next(at(11, 1), &b)?.key != "k2" { out.append("pings: nothing after the hour has passed") }
        raise(ping("k3"), &b); _ = next(at(12, 2), &b)
        raise(ping("k4"), &b)
        if next(at(15), &b) != nil { out.append("pings: a fourth panel in one day") }
        if next(at(10, 1, day: 15), &b)?.key != "k4" { out.append("pings: nothing the next day") }
        b = PingBook()
        raise(ping("n1"), &b)
        for h in [23, 0, 3, 7] where next(at(h), &b) != nil { out.append("pings: a panel at \(h):00, in the quiet hours") }
        raise(ping("n2"), &b); raise(ping("n3"), &b)
        var w = at(9); w.typedElsewhere = 12
        if next(w, &b) != nil { out.append("pings: a panel while the owner types in another app") }
        w = at(9); w.fullScreen = true
        if next(w, &b) != nil { out.append("pings: a panel over a full-screen app") }
        let merged = next(at(9), &b)
        if merged?.all.count != 3 || merged?.text.hasPrefix("3 things") != true || !b.pending.isEmpty { out.append("pings: three waiting things are not one panel") }
        b = PingBook()
        let s = ping("s1")
        raise(s, &b)
        if let p = next(at(9), &b) { notNow(p, &b, now: at(9).now) }
        if next(at(15), &b) != nil { out.append("pings: back within a day of \u{201C}not now\u{201D}") }
        guard let back = next(at(9, 1, day: 15), &b) else { return out + ["pings: \u{201C}not now\u{201D} did not bring it back a day later"] }
        notNow(back, &b, now: at(9, 1, day: 15).now)
        if next(at(12, 0, day: 17), &b) != nil || raise(s, &b) { out.append("pings: back after \u{201C}not now\u{201D} twice") }
        b = PingBook()
        if raise(ping("f1", .finished), &b) || raise(ping("w1", .waits), &b) { out.append("pings: a kind that is off, or one that only waits, was taken") }
        b.kinds["finished"] = true
        if !raise(ping("f1", .finished), &b) { out.append("pings: a kind the owner switched on is not taken") }
        b = PingBook()
        for i in 0..<14 { raise(ping("l\(i)"), &b); _ = next(at(9, 0, day: 1 + i), &b) }
        if b.last.count != 10 || b.last.first?.text != "l13" { out.append("pings: the list of the last ten is \(b.last.count) long") }
        return out
    }
}

/// Decides when to tap them on the shoulder, and keeps the list of what waits on them.
@Observable final class Pinger {
    var queue: [Ping] = []          // what waits on them, newest first: listed in the popover and counted, never raised
    var attention = false           // the menu-bar dot stays coloured until the popover is opened
    var showing: Ping?

    @ObservationIgnored unowned let model: AppModel
    @ObservationIgnored var present: ((Ping) -> Void)?
    @ObservationIgnored var withdraw: (() -> Void)?
    @ObservationIgnored var attentionChanged: ((Bool, Bool) -> Void)?   // (on, pulse)
    @ObservationIgnored private var dropped = Set<String>()
    @ObservationIgnored private var timer: Timer?

    init(model: AppModel) { self.model = model }

    func start() {
        guard timer == nil, !Engine.debug else { return }
        timer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in self?.evaluate() }
    }

    var quiet: Bool { model.saved.quietUntil > Date().timeIntervalSince1970 }

    func setQuiet(_ on: Bool) {
        model.saved.quietUntil = on ? Date().addingTimeInterval(3600).timeIntervalSince1970 : 0
        model.persist()
        if on { withdraw?(); showing = nil }
    }

    /// True while something holds the display awake: a video playing, a call, a shared screen in most meeting apps.
    static func screenBusy() -> Bool {
        var out: Unmanaged<CFDictionary>?
        guard IOPMCopyAssertionsByProcess(&out) == kIOReturnSuccess, let all = out?.takeRetainedValue() as? [AnyHashable: Any] else { return false }
        for (_, list) in all {
            for a in (list as? [[String: Any]]) ?? [] {
                let type = a["AssertType"] as? String ?? "", name = a["Process Name"] as? String ?? ""
                if type == "PreventUserIdleDisplaySleep" || type == "NoDisplaySleepAssertion", name != "caffeinate" { return true }
            }
        }
        return false
    }

    /// The app in front has a window that covers a whole screen.
    static func fullScreenInFront() -> Bool {
        guard let front = NSWorkspace.shared.frontmostApplication, front.processIdentifier != ProcessInfo.processInfo.processIdentifier,
              let list = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] else { return false }
        let screens = NSScreen.screens.map(\.frame.size)
        for w in list where (w[kCGWindowOwnerPID as String] as? Int32) == front.processIdentifier && (w[kCGWindowLayer as String] as? Int) == 0 {
            guard let b = w[kCGWindowBounds as String] as? [String: CGFloat], let width = b["Width"], let height = b["Height"] else { continue }
            if screens.contains(where: { abs($0.width - width) < 1 && abs($0.height - height) < 1 }) { return true }
        }
        return false
    }

    /// The moment as the rules need it.
    static func world() -> PingPolicy.World {
        var w = PingPolicy.World(now: Date())
        let ours = NSWorkspace.shared.frontmostApplication?.processIdentifier == ProcessInfo.processInfo.processIdentifier
        if !ours { w.typedElsewhere = CGEventSource.secondsSinceLastEventType(.combinedSessionState, eventType: .keyDown) }
        w.fullScreen = fullScreenInFront()
        w.busy = screenBusy()
        return w
    }

    /// Something happened that the owner may be told about. It is taken once per key; when it shows is the rules' to say.
    func raise(_ p: Ping) {
        guard !Engine.debug else { return }
        guard !model.saved.pingsOff else { return }
        if PingPolicy.raise(p, &model.saved.pings) { model.persist() }
    }

    /// An answer landed in a chat the owner was not looking at.
    func answered(chat: String, title: String, turn: Int) {
        let front = (NSApp?.isActive ?? false) && (NSApp?.delegate as? AppDelegate)?.window?.isVisible == true
        raise(Ping(key: "chat:\(chat)|answered|\(turn)", kind: .answer, text: "your answer is ready: \(title.isEmpty ? "a question you asked" : title)", action: "read it",
                   fix: .chat, target: chat, brief: "an answer", why: front ? "it was written while you were in another chat" : "it was written while context was behind another app"))
    }

    /// A long job is done: the first read of this mac, or the wiki.
    func finished(_ what: String, text: String, fix: Ping.Fix) {
        raise(Ping(key: "\(what)|finished|\(Words.isoDay(Date()))", kind: .finished, text: text, action: "see it", fix: fix, brief: what == "read" ? "the first read" : "the \(what)", why: "you started it and it ran to the end"))
    }

    func evaluate() {
        guard model.saved.onboarded || model.started, !model.activity.frozen else { return }
        var want: [Ping] = []
        var changed = false
        var book = model.saved.pings
        let off = model.saved.pingsOff

        // a permission that was on and is now off: listed, and told once per loss
        func lost(_ key: String, _ has: Bool, _ had: WritableKeyPath<Saved, Bool>, _ text: String, _ fix: Ping.Fix) {
            if has {
                if !model.saved[keyPath: had] { model.saved[keyPath: had] = true; changed = true }
                PingPolicy.forget("\(key)|off", &book)
            } else if model.saved[keyPath: had] {
                let p = Ping(key: "\(key)|off", kind: .lost, text: text, action: "open settings", fix: fix, why: "it was on, and macos now says it is off")
                want.append(Ping(key: p.key, kind: .waits, text: text, action: p.action, fix: fix))
                if !off { PingPolicy.raise(p, &book) }
            }
        }
        lost("disk", Access.fullDisk, \.hadDisk, "full disk access is off. imessage, notes and mail stopped coming in.", .disk)
        lost("titles", AXIsProcessTrusted(), \.hadTitles, "accessibility is off. context sees app names only, not window titles.", .titles)

        // what waits on them in their browser: listed, never raised
        let req = model.requests
        let browser = req.browser?.name ?? "your browser"
        for s in req.services where s.state == .needsYou {
            want.append(Ping(key: "\(s.id)|needs_you", kind: .waits, src: s.id, text: "\(s.name) is waiting for you in \(browser).", action: "go to \(browser)", fix: .browser))
        }
        let waiting = req.services.filter { $0.state == .requested || $0.state == .needsYou }.count
        if req.browser?.scripting == false, waiting > 0 {
            want.append(Ping(key: "browser|scripting_off", kind: .waits,
                             text: "\(browser) stopped letting context press buttons, and \(waiting == 1 ? "an export is" : "\(waiting) exports are") waiting. turning it on reopens \(browser) with your tabs.",
                             action: "turn it on", fix: .scripting))
        }

        // an export the owner asked for is in, and read
        let arrived = req.services.filter { $0.state == .arrived }
        if let seen = model.saved.seenArrived {
            for s in arrived where !seen.contains(s.id) {
                let rows = model.engine.order.filter { $0 == s.id || $0.hasPrefix(s.id + "_") }.reduce(0) { $0 + model.engine.state($1).rows }
                model.saved.seenArrived?.append(s.id)
                changed = true
                if !off {
                    PingPolicy.raise(Ping(key: "\(s.id)|arrived|\(Int(s.requestedAt))", kind: .arrived, src: s.id,
                                          text: "\(s.name) archive is in" + (rows > 0 ? ": \(Words.count(rows)) rows" : " and has been read"), action: "see it", fix: .sources, brief: "\(s.name) archive",
                                          why: "the export you asked for arrived and was read in"), &book)
                }
            }
            // asked for again later: its next arrival is news again
            let gone = seen.filter { id in !arrived.contains { $0.id == id } }
            if !gone.isEmpty { model.saved.seenArrived?.removeAll { gone.contains($0) }; changed = true }
        } else if !req.services.isEmpty {
            model.saved.seenArrived = arrived.map(\.id)      // first look: what is already here is not news
            changed = true
        }

        // an answer the owner has since read is no longer something to tell them
        book.pending.removeAll { p in p.kind == .answer && model.ask.chats.first { $0.id == p.target }?.unread != true }

        // the list: keep what still holds, newest first
        let ids = Set(want.map(\.key))
        dropped = dropped.filter { ids.contains($0) }
        let kept = queue.filter { ids.contains($0.key) && !dropped.contains($0.key) }
        let next = want.filter { p in !kept.contains { $0.key == p.key } && !dropped.contains(p.key) } + kept
        if next != queue { queue = next }
        let lit = !queue.isEmpty
        if lit != attention { attention = lit; attentionChanged?(lit, false) }

        if !off, !quiet, showing == nil, let p = PingPolicy.next(Pinger.world(), &book) {
            showing = p
            present?(p)
        }
        if book != model.saved.pings { model.saved.pings = book; changed = true }
        if changed { model.persist() }
    }

    /// The popover was opened: the owner has seen the list.
    func seen() {
        withdraw?()
        showing = nil
    }

    /// The one click. Does the whole thing.
    func act(_ p: Ping, showWindow: () -> Void) {
        switch p.fix {
        case .chat: model.openChat(p.target); showWindow()
        case .sources: model.tab = .sources; showWindow()
        case .profile: model.tab = .profile; showWindow()
        case .window: showWindow()
        case .browser:
            let name = (model.requests.browser?.name ?? "").lowercased()
            NSWorkspace.shared.runningApplications.first { ($0.localizedName ?? "").lowercased() == name }?.activate()
        case .disk: Access.openSettings()
        case .titles: model.askForTitles()
        case .scripting: model.requests.enableBrowser()
        }
        if p.kind == .waits { drop(p) } else { withdraw?(); showing = nil }
    }

    /// "not now" on a panel: a day's peace for that thing, and after the second time, for good.
    func notNow(_ p: Ping) {
        PingPolicy.notNow(p, &model.saved.pings, now: Date())
        model.persist()
        withdraw?()
        showing = nil
    }

    /// Takes a waiting thing off the list for this run of the app. It is still counted on the sources page.
    func drop(_ p: Ping) {
        dropped.insert(p.key)
        queue.removeAll { $0.key == p.key }
        if queue.isEmpty, attention { attention = false; attentionChanged?(false, false) }
    }
}

/// The panel that drops from the menu-bar mark: one sentence, one action, a quiet way out. It is cut from the same
/// cloth as the panel the key opens: its ground, its corner, its hairline, and the ember bar for what is yours now.
struct PingView: View {
    @Environment(\.colorScheme) private var scheme
    let ping: Ping
    let act: () -> Void
    let dismiss: () -> Void
    var hover: (Bool) -> Void = { _ in }
    static let width: CGFloat = 340

    var body: some View {
        let shape = RoundedRectangle(cornerRadius: PanelTray.radius, style: .continuous)
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .top, spacing: 11) {
                Group {
                    if !ping.src.isEmpty { SourceIcon(id: ping.src, size: 18) }
                    else { RoundedRectangle(cornerRadius: 1).fill(Ink.ember).frame(width: 2, height: 15) }
                }
                .frame(width: 18, height: 20)
                .accessibilityHidden(true)
                Text(ping.text)
                    .font(.system(size: 14, weight: .medium)).lineSpacing(2.5)
                    .foregroundStyle(Ink.ink)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .probe("ping.text", .text, group: "ping.parts")
            }
            .padding(.horizontal, 16).padding(.top, 15).padding(.bottom, 13)
            Rectangle().fill(Ink.ink.opacity(0.08)).frame(height: 1)
            HStack(spacing: 14) {
                Button(ping.action, action: act).buttonStyle(PingButton())
                    .probe("ping.act", .button, group: "ping.parts")
                Button("not now", action: dismiss).buttonStyle(QuietButton(size: 12))
                    .help("it may come back once, tomorrow. say it twice and it stays quiet.")
                    .probe("ping.later", .button, group: "ping.parts")
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 16).frame(height: 46)
        }
        .frame(width: PingView.width, alignment: .leading)
        .background { if Probe.on { Ink.paper } else { ZStack { Glass(); Ink.paper.opacity(0.72) } } }
        .clipShape(shape)
        .overlay { shape.strokeBorder(scheme == .dark ? Color.white.opacity(0.14) : Color.black.opacity(0.10), lineWidth: 0.5) }
        .overlay(alignment: .top) {
            shape.strokeBorder(LinearGradient(colors: [.white.opacity(scheme == .dark ? 0.22 : 0.6), .clear], startPoint: .top, endPoint: .center), lineWidth: 0.5)
                .frame(height: 40).allowsHitTesting(false)
        }
        .onHover(perform: hover)
        .probe("ping.panel", .block)
    }
}

struct PingButton: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 12, weight: .semibold)).lineLimit(1).fixedSize()
            .foregroundStyle(Ink.paper)
            .padding(.horizontal, 13).frame(height: 28)
            .background(Ink.ink, in: Capsule())
            .scaleEffect(configuration.isPressed ? Motion.press : 1)
            .animation(.spring(response: 0.25, dampingFraction: 0.7), value: configuration.isPressed)
    }
}

/// What waits on them, in the popover.
struct PingQueue: View {
    @Environment(AppModel.self) private var model
    let showWindow: () -> Void

    var body: some View {
        let pinger = model.pinger!
        if let p = pinger.queue.first {
            VStack(alignment: .leading, spacing: 9) {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    if !p.src.isEmpty { SourceIcon(id: p.src, size: 14).alignmentGuide(.firstTextBaseline) { $0[.bottom] - 3 } }
                    else { Circle().fill(LogoMark.dot).frame(width: 6, height: 6).offset(y: -2) }
                    Text(p.text).font(.system(size: 13, weight: .medium)).foregroundStyle(Ink.ink).lineSpacing(2)
                        .fixedSize(horizontal: false, vertical: true)
                }
                HStack(spacing: 14) {
                    Button(p.action) { pinger.act(p, showWindow: showWindow) }.buttonStyle(PingButton())
                    Button("not now") { pinger.drop(p) }.buttonStyle(QuietButton(size: 13))
                    Spacer()
                    if pinger.queue.count > 1 {
                        Text("\(pinger.queue.count - 1) more").font(.system(size: 12, weight: .medium)).monospacedDigit().foregroundStyle(Ink.faint)
                    }
                }
                .padding(.leading, 14)
                Rectangle().fill(Ink.line).frame(height: 1).padding(.top, 5)
            }
            .padding(.top, 12)
        }
    }
}

extension LayoutTest {
    static func pingScreens(_ m: AppModel, main: @escaping (Tab) -> Void) -> [(String, () -> Void)] {
        // a fixed day: 14 nov 2026, 10:02 utc
        let day = 1_794_650_520.0
        var out: [(String, () -> Void)] = []
        out.append(("ping-answer", { main(.home); m.pingProof = Ping(key: "chat:a|answered|3", kind: .answer, text: "your answer is ready: where the lease stands", action: "read it", fix: .chat) }))
        out.append(("ping-arrived", { main(.home); m.pingProof = Ping(key: "x|arrived|1", kind: .arrived, src: "x_posts", text: "x archive is in: 12,300 rows", action: "see it", fix: .sources) }))
        out.append(("ping-merged", {
                main(.home)
                m.pingProof = PingPolicy.merge([
                    Ping(key: "a", kind: .answer, text: "your answer is ready: \(longName), and what the committee said about it", action: "read it", brief: "an answer"),
                    Ping(key: "b", kind: .arrived, src: "x_posts", text: "x archive is in: 12,300 rows", action: "see it", brief: "x archive"),
                    Ping(key: "c", kind: .finished, text: "the first read of this mac is done: 123,456 rows", action: "see it", brief: "the first read")])
            }))
        // the menu bar's popover: at rest, and with something waiting on them and a source that could not be read
        out.append(("popover-rest", { main(.home); m.popoverProof = true }))
        out.append(("popover-waiting", {
                main(.home)
                m.popoverProof = true
                m.engine.states["imessage"] = .skipped("blocked by macOS: grant Full Disk Access to the app running this")
                m.plan = ModelPlan(["using": "none", "fix": "no plan is signed in. answers wait until one is."])
                m.pinger.queue = [Ping(key: "a", kind: .answer, text: "your answer is ready: \(longName), and what the committee said about it", action: "read it", fix: .chat),
                                  Ping(key: "b", kind: .arrived, src: "x_posts", text: "x archive is in: 12,300 rows", action: "see it", fix: .sources)]
            }))
        out.append(("settings-pings", {
                main(.settings)
                m.settingsPane = .notifications
                m.settings.loaded = true
                m.settings.answered = true
                m.saved.pings.kinds = ["finished": true]
                var notes: [PingNote] = []
                for i in 0..<10 {
                    let answer = i % 2 == 0
                    var text = answer ? "your answer is ready: where the lease stands" : "x archive is in: 12,300 rows"
                    if i == 1 { text = "your answer is ready: " + longName + ", and what the committee said about it" }
                    let why = answer ? "it was written while context was behind another app" : "the export you asked for arrived and was read in"
                    notes.append(PingNote(at: day - Double(i) * 5400, kind: answer ? "answer" : "arrived", text: text, why: why))
                }
                m.saved.pings.last = notes
            }))
        out.append(("settings-pings-off", { main(.settings); m.settingsPane = .notifications; m.settings.loaded = true; m.settings.answered = true; m.saved.pingsOff = true }))
        return out
    }
}

/// The panel drawn inside the test window, and the rows of settings that go with it.
struct PingProof: View {
    let ping: Ping
    var body: some View {
        VStack(spacing: 0) {
            PingView(ping: ping, act: {}, dismiss: {}).padding(.top, 40)
            Spacer(minLength: 0)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Ink.wash)
    }
}

extension LogoMark {
    /// the menu-bar mark while something is waiting: the same brackets, the dot in persimmon and a little larger.
    /// not a template, so the brackets take the menu bar's own text colour when it is drawn.
    static func menuBarAttentionImage() -> NSImage {
        let image = NSImage(size: NSSize(width: 18, height: 18), flipped: false) { rect in
            drawMenuBarMark(in: rect, ink: .labelColor, dot: NSColor(LogoMark.dot), dotRadius: 2.3)
            return true
        }
        image.isTemplate = false
        return image
    }
}

/// The panel and the menu-bar state live with the app delegate.
extension AppDelegate {
    func wirePings() {
        let pinger = model.pinger!
        pinger.present = { [weak self] p in self?.showPing(p) }
        pinger.withdraw = { [weak self] in self?.hidePing() }
        pinger.attentionChanged = { [weak self] on, pulse in self?.setAttention(on, pulse: pulse) }
        if model.saved.onboarded { pinger.start(); model.loadPending(); model.now.load(model.engine, force: true); model.rules.load(model.engine); model.made.load(model.engine); model.exports.load(model.engine); model.keys.load(model.engine) }
        debugPing()
    }

    private var reduceMotion: Bool { NSWorkspace.shared.accessibilityDisplayShouldReduceMotion }

    func setAttention(_ on: Bool, pulse: Bool) {
        guard let button = statusItem.button else { return }
        attention = on
        button.image = on ? LogoMark.menuBarAttentionImage() : LogoMark.menuBarImage()
        guard on, pulse, !reduceMotion else { return }
        button.wantsLayer = true
        let a = CAKeyframeAnimation(keyPath: "opacity")     // one soft pulse
        a.values = [1, 0.35, 1]
        a.keyTimes = [0, 0.45, 1]
        a.duration = 0.9
        a.timingFunction = CAMediaTimingFunction(name: .easeInEaseOut)
        button.layer?.add(a, forKey: "pulse")
    }

    func showPing(_ p: Ping) {
        let panel = pingPanel ?? {
            let w = NSPanel(contentRect: .zero, styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
            w.level = .statusBar                 // above full-screen apps, like the menu bar itself
            w.isOpaque = false
            w.backgroundColor = .clear
            w.hasShadow = true
            w.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
            w.hidesOnDeactivate = false
            w.becomesKeyOnlyIfNeeded = true
            pingPanel = w
            return w
        }()
        let pinger = model.pinger!
        let host = NSHostingView(rootView: PingView(ping: p,
            act: { [weak self] in pinger.act(p, showWindow: { self?.showWindow(nil) }) },
            dismiss: { pinger.notNow(p) },
            hover: { [weak self] inside in if inside { self?.pingTimer?.invalidate() } else { self?.armPingTimer() } }))
        let size = host.fittingSize
        panel.contentView = host
        // under the menu-bar mark when the menu bar is there. in a full-screen space the menu bar is hidden and the
        // mark has no usable frame: then sit at the top right of the screen. never park the panel off screen, macos
        // pushes it back into the bottom-left corner where it covers other apps.
        if shooting { return }
        guard let screen = statusItem.button?.window?.screen ?? NSScreen.main else { return }
        var origin = NSPoint(x: screen.frame.maxX - size.width - 16, y: screen.frame.maxY - size.height - 12)
        if let item = statusItem.button?.window?.frame, item.width > 0, item.minY > screen.frame.maxY - 80 {
            let x = min(max(item.midX - size.width / 2, screen.frame.minX + 8), screen.frame.maxX - size.width - 8)
            origin = NSPoint(x: x, y: item.minY - size.height - 6)
        }
        let rest = NSRect(origin: origin, size: size)
        if shooting {                           // drawn for a render, never shown
            panel.setFrame(rest, display: false)
            host.layoutSubtreeIfNeeded()
            return
        }
        if reduceMotion {
            panel.setFrame(rest, display: true)
            panel.alphaValue = shooting ? 1 : 0
            panel.orderFrontRegardless()
            panel.animator().alphaValue = 1
        } else {
            panel.setFrame(rest.offsetBy(dx: 0, dy: 10), display: true)     // drops from under the mark and settles
            panel.alphaValue = 0
            panel.orderFrontRegardless()
            NSAnimationContext.runAnimationGroup { ctx in
                ctx.duration = 0.42
                ctx.timingFunction = CAMediaTimingFunction(controlPoints: 0.2, 1.25, 0.35, 1)
                panel.animator().setFrame(rest, display: true)
                panel.animator().alphaValue = 1
            }
        }
        armPingTimer()
    }

    func armPingTimer() {
        pingTimer?.invalidate()
        pingTimer = Timer.scheduledTimer(withTimeInterval: 8, repeats: false) { [weak self] _ in
            self?.hidePing()
            self?.model.pinger.showing = nil       // said once: it does not come back by itself
        }
    }

    func hidePing() {
        pingTimer?.invalidate()
        guard let panel = pingPanel, panel.isVisible else { return }
        NSAnimationContext.runAnimationGroup({ ctx in
            ctx.duration = 0.3
            panel.animator().alphaValue = 0
        }, completionHandler: { if panel.alphaValue == 0 { panel.orderOut(nil) } })
    }

    /// Development: `ping=arrived` or `ping=lost` draws that ping for an offscreen render; any other word draws an answer that is ready.
    private func debugPing() {
        guard let d = ProcessInfo.processInfo.environment["CONTEXT_DEBUG"],
              let kind = d.split(separator: ",").first(where: { $0.hasPrefix("ping=") })?.dropFirst(5) else { return }
        let sample: Ping
        switch kind {
        case "arrived": sample = Ping(key: "d", kind: .arrived, src: "x", text: "x archive is in: 12,300 rows", action: "see it", fix: .sources)
        case "lost": sample = Ping(key: "d", kind: .lost, text: "full disk access is off. imessage, notes and mail stopped coming in.", action: "open settings", fix: .disk)
        default: sample = Ping(key: "d", kind: .answer, text: "your answer is ready: the lease renewal", action: "read it", fix: .chat)
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) {
                        self.showPing(sample)
        }
    }
}
