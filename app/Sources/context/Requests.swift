import Foundation
import Observation
import SwiftUI

/// An account export context can ask for on your behalf, by driving your own browser.
struct Service: Identifiable, Equatable {
    enum State: String { case idle, declined, requested, needsYou = "needs_you", arrived, failed }
    let id: String
    var name: String
    var what: String
    var state: State
    var detail: String
    var asksFor: String     // nothing, password, code
    var arrives: String     // minutes, hours, a day
    var requestedAt: Double

    init?(_ d: [String: Any]) {
        guard let id = d["id"] as? String else { return nil }
        self.id = id
        name = (d["name"] as? String ?? id).lowercased()
        what = d["what"] as? String ?? ""
        state = State(rawValue: d["state"] as? String ?? "idle") ?? .idle
        detail = d["detail"] as? String ?? ""
        asksFor = d["asks_for"] as? String ?? "nothing"
        arrives = d["arrives"] as? String ?? "hours"
        if let t = d["requested_at"] as? Double { requestedAt = t }
        else if let t = d["requested_at"] as? String { requestedAt = ISO8601DateFormatter().date(from: t)?.timeIntervalSince1970 ?? 0 }
        else { requestedAt = 0 }
    }

    /// The mark of the source this export feeds, so colour stays with the source.
    var mark: SourceInfo {
        let map = ["x": "x_archive", "google": "gmail_takeout", "instagram": "instagram", "linkedin": "linkedin",
                   "chatgpt": "chatgpt_export", "notion": "notion"]
        return Catalog.info(map[id] ?? id)
    }

    var arrivesWords: String {
        switch arrives {
        case "minutes": return "in a few minutes"
        case "hours": return "in a few hours"
        case "a day": return "in about a day"
        default: return arrives
        }
    }

    var asksWords: String {
        switch asksFor {
        case "password": return "your password, typed by you on the site. context never sees it."
        case "code": return "a code the site sends you. you type it on the site."
        default: return "nothing. you are already signed in."
        }
    }

    var mood: MarkMood {
        switch state {
        case .idle: return .waiting
        case .requested, .arrived: return .done
        case .declined, .needsYou, .failed: return .blocked
        }
    }
}

struct BrowserInfo: Equatable {
    var name: String
    var scripting: Bool
    var howToEnable: String
}

/// Talks to `python3 -m ctx request`. If the engine has no such command yet, the list stays empty and the
/// app shows no export steps at all.
@Observable final class Requests {
    var browser: BrowserInfo?
    var services: [Service] = []
    var busy: Set<String> = []
    var asked: Set<String> = []     // asked in this run of the app, as opposed to found already pending
    var enabling = false

    @ObservationIgnored private let engine: Engine

    init(engine: Engine) {
        self.engine = engine
        refresh()
    }

    func service(_ id: String) -> Service? { services.first { $0.id == id } }

    func refresh() {
        engine.json(["request", "--list"], timeout: 30) { [weak self] obj in
            guard let self, let obj, let rows = obj["services"] as? [[String: Any]] else { return }
            let found = rows.compactMap(Service.init)
            if found != self.services { self.services = found }
            if let b = obj["browser"] as? [String: Any] {
                self.browser = BrowserInfo(name: (b["name"] as? String ?? "your browser").lowercased(),
                                           scripting: b["scripting"] as? Bool ?? false,
                                           howToEnable: b["how_to_enable"] as? String ?? "")
            }
        }
    }

    private func run(_ args: [String], id: String, then: (() -> Void)? = nil) {
        guard !busy.contains(id) else { return }
        busy.insert(id)
        engine.json(["request"] + args) { [weak self] obj in
            guard let self else { return }
            self.busy.remove(id)
            if let obj, let s = Service(obj), let i = self.services.firstIndex(where: { $0.id == s.id }) {
                self.services[i] = s
                then?()
            } else if let i = self.services.firstIndex(where: { $0.id == id }), then == nil, args.count == 1 {
                self.services[i].state = .failed
                self.services[i].detail = "the engine gave no answer."
            } else {
                self.refresh()
                then?()
            }
        }
    }

    /// Asks the site for the export, or checks again on one that is waiting on you.
    func request(_ id: String) {
        asked.insert(id)
        run([id], id: id)
    }

    func decline(_ id: String) { run(["--decline", id], id: id) }
    func reset(_ id: String) { asked.remove(id); run(["--reset", id], id: id) }
    /// Changed your mind after saying no: clear the no, then ask.
    func askAfterAll(_ id: String) { run(["--reset", id], id: id) { [weak self] in self?.request(id) } }

    func enableBrowser() {
        guard !enabling else { return }
        enabling = true
        engine.json(["request", "--enable-browser"]) { [weak self] _ in
            self?.enabling = false
            self?.refresh()
        }
    }

    /// The one-word state and the sentence under it.
    func words(_ s: Service) -> (word: String, line: String) {
        if busy.contains(s.id) { return ("asking", "opening the page in \(browser?.name ?? "your browser").") }
        switch s.state {
        case .idle: return ("not asked", "")
        case .declined: return ("not this one", "you said no. nothing was requested.")
        case .requested:
            return asked.contains(s.id)
                ? ("requested", "expect it \(s.arrivesWords). context picks it up on the next sync.")
                : ("asked", "it has not arrived yet. context picks it up from downloads when it does.")
        case .needsYou: return ("needs you", s.detail.isEmpty ? "the site is waiting for you in the browser." : s.detail)
        case .arrived: return ("arrived", "it is in. the rows show up under sources.")
        case .failed: return ("did not work", s.detail.isEmpty ? "the site did not take the request." : s.detail)
        }
    }
}

// MARK: sources tab

/// What the list of exports on the sources page holds: only what still needs something. An export that has
/// arrived and been read has no row (its rows are sources, above); one never asked for is a tile on the shelf;
/// the ones the owner said no to are one quiet line at the end.
extension Requests {
    var waiting: [Service] { services.filter { [.requested, .needsYou, .failed].contains($0.state) } }
    var declined: [Service] { services.filter { $0.state == .declined } }
    /// the export behind a source that came from one, once it has arrived: where "ask for a newer copy" lives
    func arrived(for source: String) -> Service? { services.first { $0.state == .arrived && $0.mark.id == source } }

    /// "asked 3 days ago"
    static func asked(_ at: Double, now: Date = Date()) -> String {
        guard at > 0 else { return "" }
        let days = Int(now.timeIntervalSince1970 - at) / 86400
        return days <= 0 ? "asked today" : (days == 1 ? "asked yesterday" : "asked \(days) days ago")
    }

    /// One whole sentence for a row: when it was asked and where the file comes from; or what the owner must do; or why it failed.
    func sentence(_ s: Service) -> String {
        if busy.contains(s.id) { return "opening the page in \(browser?.name ?? "your browser")." }
        switch s.state {
        case .requested:
            let when = Requests.asked(s.requestedAt)
            return (when.isEmpty ? "asked." : when + ".") + " \(s.name) sends the file as a download, \(s.arrivesWords). context reads it from downloads when it lands."
        case .needsYou: return s.detail.isEmpty ? "\(s.name) is waiting for you in the browser\(s.asksFor == "nothing" ? "" : ": it wants a \(s.asksFor)")." : s.detail.lowercased()
        case .failed: return s.detail.isEmpty ? "\(s.name) did not take the request." : s.detail.lowercased()
        default: return ""
        }
    }
}

/// The exports that still need something, under one small heading; then the ones the owner said no to, as one line.
/// With nothing waiting and nothing declined there is nothing here at all: no heading, no row that says all is done.
struct ExportList: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let req = model.requests
        let rows = model.exports.rows
        // the engine's own rows when it gives them (`exports`); an older engine's requests otherwise
        let waiting = rows == nil ? req.waiting : []
        let items = model.exports.shown
        VStack(alignment: .leading, spacing: 0) {
            if !items.isEmpty {
                Text("exports you asked for").font(Face.heading).foregroundStyle(Ink.soft).lineLimit(1)
                    .padding(.top, Space.xxl)
                    .accessibilityAddTraits(.isHeader)
                    .probe("export.head", .line, scrolls: true)
                VStack(spacing: 0) { ForEach(items) { ExportItemRow(item: $0) } }.padding(.top, 6)
            }
            if !waiting.isEmpty {
                Text("exports you asked for").font(Face.heading).foregroundStyle(Ink.soft).lineLimit(1)
                    .padding(.top, Space.xxl)
                    .accessibilityAddTraits(.isHeader)
                    .probe("export.head", .line, scrolls: true)
                VStack(spacing: 0) { ForEach(waiting) { ExportRow(service: $0) } }.padding(.top, 6)
            }
            // what the owner said no to is in settings, with the way to start it again: here, one quiet line that goes there
            let off = model.declined.count
            if off > 0 {
                Button { model.openSettings(.sync) } label: {
                    HStack(spacing: 6) {
                        Text("\(off) declined").probe("export.declined", .line, scrolls: true)
                        Text("·").foregroundStyle(Ink.faint)
                        Text("settings")
                    }
                }
                .buttonStyle(QuietButton(size: Face.small))
                .accessibilityLabel("\(off) declined. open settings to start one again")
                .help("in settings, under sources & sync: each one, with the way to start it again")
                .padding(.top, waiting.isEmpty && items.isEmpty ? Space.xl : Space.m)
            }
        }
    }
}

/// One export that still needs something: its name, how it stands as a dot and a word, one whole sentence, and
/// the one button when there is something for them to do.
struct ExportRow: View {
    @Environment(AppModel.self) private var model
    let service: Service

    var body: some View {
        let req = model.requests
        let busy = req.busy.contains(service.id)
        let needs = service.state == .needsYou || service.state == .failed
        HStack(alignment: .center, spacing: Space.m) {
            VStack(alignment: .leading, spacing: 3) {
                HStack(alignment: .firstTextBaseline, spacing: Space.s) {
                    SourceIcon.inline(id: service.mark.id, font: .systemFont(ofSize: 15, weight: .medium), name: service.name)
                    Text(service.name).font(.system(size: Face.body, weight: .medium)).foregroundStyle(Ink.ink).lineLimit(1)
                    Pill(text: busy ? "asking" : (service.state == .requested ? "on its way" : (service.state == .needsYou ? "needs you" : "did not work")),
                         tone: needs && !busy ? .warn : .quiet)
                }
                Text(req.sentence(service)).font(.system(size: Face.label)).foregroundStyle(Ink.soft).lineSpacing(2)
                    .fixedSize(horizontal: false, vertical: true).padding(.leading, 24)
                    .probe("export.line", .text, scrolls: true)
            }
            Spacer(minLength: Space.s)
            if !busy {
                if needs {
                    Button(service.state == .needsYou ? "open it" : "try again") { req.request(service.id) }
                        .buttonStyle(SetButtonStyle())
                        .accessibilityLabel(service.state == .needsYou ? "open \(service.name) in the browser" : "ask \(service.name) again")
                        .probe("export.act", .button, scrolls: true)
                }
                Button("don't want it") { req.decline(service.id) }.buttonStyle(QuietButton(size: Face.small))
                    .accessibilityLabel("do not ask \(service.name)")
            }
        }
        .padding(.vertical, 10)
        .overlay(alignment: .bottom) { Rectangle().fill(Ink.line).frame(height: 1) }
        .probe("export.row", .block, group: "export.rows", scrolls: true)
    }
}
