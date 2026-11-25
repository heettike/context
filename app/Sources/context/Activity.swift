import AppKit
import ApplicationServices
import Observation

/// One stretch of time in one window.
struct Span: Codable, Equatable {
    var app: String
    var title: String
    var start: Double
    var secs: Double
    var end: Double { start + secs }
}

/// Knows what is in front right now and keeps today's timeline: app, window title, seconds.
/// It reads the frontmost app's name and, with Accessibility on, its window title. No screenshots, no keys.
/// The timeline is written to a file a day only while `keeps` says so (the switch for nudges worded by the plan, off
/// until the owner turns it on); otherwise it lives in memory for the plain nudges and is gone when the app quits.
/// No day older than `days` is kept: older files go when the app starts.
@Observable final class Activity {
    let dir: URL
    var spans: [Span] = []
    var app = ""
    var title = ""
    var trusted = AXIsProcessTrusted()
    var onChange: (() -> Void)?
    /// whether the timeline may be written to disk. off by default
    @ObservationIgnored var keeps: () -> Bool = { false }
    static let days = 14

    @ObservationIgnored private var day = Words.isoDay(Date())
    @ObservationIgnored private var timer: Timer?
    @ObservationIgnored private var watcher: NSObjectProtocol?
    @ObservationIgnored private var unsaved = 0
    @ObservationIgnored var frozen = false

    init(home: URL) {
        dir = home.appendingPathComponent("activity")
        prune()
        load()
    }

    private var file: URL { dir.appendingPathComponent(day + ".json") }

    private func load() {
        spans = (try? JSONDecoder().decode([Span].self, from: Data(contentsOf: file))) ?? []
        if let last = spans.last { app = last.app; title = last.title }
    }

    /// Deletes every day's file older than the last `days` days, today included in the count.
    private func prune() {
        guard !Engine.debug, let names = try? FileManager.default.contentsOfDirectory(atPath: dir.path) else { return }
        let oldest = Words.isoDay(Date().addingTimeInterval(-Double(Activity.days - 1) * 86400))
        for n in names where n.hasSuffix(".json") && n.count == 15 && String(n.prefix(10)) < oldest {
            try? FileManager.default.removeItem(at: dir.appendingPathComponent(n))
        }
    }

    func save() {
        guard !frozen, !Engine.debug, keeps() else { unsaved = 0; return }
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        if let d = try? JSONEncoder().encode(spans) { try? d.write(to: file, options: .atomic) }
        unsaved = 0
    }

    func start() {
        guard timer == nil, !frozen else { return }
        sample()
        timer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in self?.sample() }
        watcher = NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.didActivateApplicationNotification, object: nil, queue: .main) { [weak self] _ in self?.sample() }
    }

    static func windowTitle(_ pid: pid_t) -> String {
        let ax = AXUIElementCreateApplication(pid)
        AXUIElementSetMessagingTimeout(ax, 0.25)
        var win: CFTypeRef?
        guard AXUIElementCopyAttributeValue(ax, kAXFocusedWindowAttribute as CFString, &win) == .success, let w = win,
              CFGetTypeID(w) == AXUIElementGetTypeID() else { return "" }
        var t: CFTypeRef?
        guard AXUIElementCopyAttributeValue(w as! AXUIElement, kAXTitleAttribute as CFString, &t) == .success else { return "" }
        return String(((t as? String) ?? "").prefix(140))
    }

    private func sample() {
        let today = Words.isoDay(Date())
        if today != day { save(); day = today; spans = [] }
        trusted = AXIsProcessTrusted()
        guard let front = NSWorkspace.shared.frontmostApplication else { return }
        let name = front.localizedName ?? "?"
        let t = trusted ? Activity.windowTitle(front.processIdentifier) : ""
        let moved = name != app || t != title
        app = name
        title = t
        let idle = CGEventSource.secondsSinceLastEventType(.combinedSessionState, eventType: CGEventType(rawValue: ~0)!)
        let now = Date().timeIntervalSince1970
        if idle < 150 {
            if let i = spans.indices.last, spans[i].app == name, spans[i].title == t, now - spans[i].end < 20 {
                spans[i].secs = now - spans[i].start
            } else {
                spans.append(Span(app: name, title: t, start: now, secs: 0))
            }
            unsaved += 1
            if unsaved >= 12 { save() }
        }
        if moved { onChange?() }
    }

    // MARK: reading the day

    var total: Double { spans.reduce(0) { $0 + $1.secs } }

    /// Spans clipped to the last `minutes`.
    func recent(_ minutes: Double) -> [Span] {
        let from = Date().timeIntervalSince1970 - minutes * 60
        return spans.compactMap { s in
            guard s.end > from else { return nil }
            var c = s
            if c.start < from { c.secs = c.end - from; c.start = from }
            return c
        }
    }

    struct Row: Identifiable { let app: String; let title: String; let secs: Double; let onFocus: Bool; var id: String { app } }

    func rows(focus: [String]) -> [Row] {
        var secs: [String: Double] = [:], titles: [String: [String: Double]] = [:], on: [String: Double] = [:]
        for s in spans {
            secs[s.app, default: 0] += s.secs
            if !s.title.isEmpty { titles[s.app, default: [:]][s.title, default: 0] += s.secs }
            if Activity.matches(s, focus) { on[s.app, default: 0] += s.secs }
        }
        return secs.filter { $0.value >= 30 }.map { app, v in
            Row(app: app, title: titles[app]?.max { $0.value < $1.value }?.key ?? "", secs: v, onFocus: (on[app] ?? 0) > v / 2)
        }.sorted { $0.secs > $1.secs }
    }

    static func matches(_ s: Span, _ words: [String]) -> Bool {
        guard !words.isEmpty else { return false }
        let hay = (s.app + " " + s.title).lowercased()
        return words.contains { hay.contains($0) }
    }

    static func clock(_ secs: Double) -> String {
        let m = Int(secs / 60)
        return m < 1 ? "under a minute" : (m < 60 ? "\(m) min" : "\(m / 60)h \(String(format: "%02d", m % 60))m")
    }
}
