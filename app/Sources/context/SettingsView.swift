import AppKit
import ApplicationServices
import Observation
import SwiftUI

/// One ai app that can be given the local connection.
struct MCPApp: Identifiable, Equatable {
    let id: String
    var name: String
    var state: String      // connected, registered, not registered, app not found, needs a remote endpoint
    var path: String       // where its config lives, shown only behind "details"
    var detail: String
    var how = ""           // for a remote one: what turning it on would take, in the engine's words

    var good: Bool { state == "connected" || state == "registered" }
    var missing: Bool { state == "app not found" }
    /// takes only a connector it can reach over the internet
    var remote: Bool { state.hasPrefix("remote") || state.contains("remote endpoint") }
    /// an entry is there and does not work: another server under the name, or one that points at a python that cannot run context
    var broken: Bool { state == "not registered" && !detail.isEmpty }
    var canConnect: Bool { state == "not registered" && detail.isEmpty }
    /// another program altered the entry context wrote into this app's config: said with the engine's sentence, and written again only when the owner says
    var changed: Bool { state == "changed" }
}

/// What the settings page shows. Every value comes from `python3 -m ctx settings` and its neighbours; where the
/// engine has not answered, the row says so instead of guessing.
@Observable final class SettingsModel {
    var loaded = false
    var answered = false                 // the engine has a `settings` command and it answered
    var raw: [String: Any] = [:]
    var apps: [MCPApp] = []
    var busy: Set<String> = []
    var said: [String: String] = [:]        // what the last fix of an app did, shown under it until the app is left
    var test = ""                        // the last plan test, in words
    var testing = false
    var understand: (read: Int, total: Int)?
    var reading = false
    var exported = ""
    var report = ""                      // where the last tester report was written
    var reporting = false

    @ObservationIgnored private let engine: Engine
    init(engine: Engine) { self.engine = engine }

    private func dict(_ k: String) -> [String: Any] { raw[k] as? [String: Any] ?? [:] }
    private func num(_ d: [String: Any], _ k: String) -> Double? { (d[k] as? NSNumber)?.doubleValue }

    private func calls(_ span: String) -> Int? {
        guard let d = dict("usage")[span] as? [String: Any] else { return nil }
        return d.values.reduce(0) { $0 + (((($1 as? [String: Any])?["calls"]) as? Int) ?? 0) }
    }
    var callsToday: Int? { calls("today") }
    var callsWeek: Int? { calls("week") }
    var cost: String { (dict("usage")["cost"] as? String ?? "").lowercased() }
    var archivePath: String {
        let f = dict("archive")["folder"] as? String ?? ""
        return f.isEmpty ? engine.home.path : (f as NSString).expandingTildeInPath
    }
    var archiveShown: String { dict("archive")["folder"] as? String ?? engine.home.path }
    var archiveBytes: Double? { num(dict("archive"), "bytes") }
    var archiveRows: Int? { (dict("archive")["rows"] as? [String: Any]).map { $0.values.reduce(0) { $0 + (($1 as? Int) ?? 0) } } }
    var keys: [(name: String, present: Bool)] {
        let k = dict("keys")
        return ((k["present"] as? [String]) ?? []).map { ($0, true) } + ((k["not_set"] as? [String]) ?? []).map { ($0, false) }
    }
    var keysWhere: String { (dict("keys")["file"] as? String ?? ".env in the folder context came in").lowercased() }
    /// links_from_others as the engine's report gives it (a bool, or "on"/"off", at the top or with its settings); nil when it does not
    var linksFromOthers: Bool? {
        for d in [raw, dict("settings"), dict("answers"), dict("sync")["settings"] as? [String: Any] ?? [:]] {
            if let b = d["links_from_others"] as? Bool { return b }
            if let s = d["links_from_others"] as? String { return s == "on" }
        }
        return nil
    }
    var weeklyReread: Bool? { dict("read_through")["reread_weekly"] as? Bool }
    var lastRead: Double? { nil }
    var repoLink: String { dict("about")["repo"] as? String ?? "" }
    /// the remote door for chatgpt and claude.ai: whether it is open, and to where
    var remoteOn: Bool { dict("remote")["running"] as? Bool ?? false }
    var remoteHost: String { dict("remote")["host"] as? String ?? "" }
    /// "120,000 messages, 3,400 docs"
    var archiveKinds: String {
        ((dict("archive")["rows"] as? [String: Any]) ?? [:]).compactMap { k, v in (v as? Int).map { (k, $0) } }.filter { $0.1 > 0 }.sorted { $0.1 > $1.1 }
            .map { "\(Words.count($0.1)) \($0.0.replacingOccurrences(of: "_", with: " "))" }.joined(separator: ", ")
    }
    var readLeftCalls: Int? { dict("read_through")["calls_left_about"] as? Int }
    private var syncSettings: [String: Any] { dict("sync")["settings"] as? [String: Any] ?? [:] }
    var fastMinutes: Int? { syncSettings["fast_minutes"] as? Int }
    var dailyHour: Int? { syncSettings["daily_hour"] as? Int }          // nil when it is "any"
    var weeklyDay: String? { (syncSettings["weekly_day"] as? String).flatMap { $0 == "any" ? nil : $0 } }

    /// `python3 -m ctx settings --fast` first, so the page fills at once, then the full report with the read-through count.
    func load() {
        for args in [["settings", "--fast"], ["settings"]] {
            engine.json(args, timeout: 90) { [weak self] obj in
                guard let self else { return }
                self.loaded = true
                guard let obj else { return }
                self.answered = true
                self.raw = obj
                if let rt = obj["read_through"] as? [String: Any], let done = rt["read"] as? Int, let total = rt["units"] as? Int { self.understand = (done, total) }
                if let list = obj["mcp"] as? [[String: Any]] { self.apps = SettingsModel.apps(list) }
            }
        }
        engine.loadSchedule()
    }

    static func apps(_ list: [[String: Any]]) -> [MCPApp] {
        list.compactMap { a in
            guard let id = a["id"] as? String ?? a["name"] as? String else { return nil }
            return MCPApp(id: id, name: (a["name"] as? String ?? id).lowercased(), state: (a["state"] as? String ?? "not registered").lowercased(),
                          path: a["config"] as? String ?? (a["path"] as? String ?? ""), detail: (a["detail"] as? String ?? "").lowercased(),
                          how: (a["how"] as? String ?? "").lowercased())
        }
    }

    /// `python3 -m ctx model --test`: one tiny call, to see that the plan answers and how fast.
    func testPlan() {
        guard !testing else { return }
        testing = true
        test = ""
        let began = Date()
        engine.json(["model", "--test"], timeout: 120) { [weak self] obj in
            guard let self else { return }
            self.testing = false
            let secs = (obj?["secs"] as? NSNumber)?.doubleValue ?? Date().timeIntervalSince(began)
            if let err = obj?["error"] as? String, !err.isEmpty { self.test = err.lowercased() }
            else if obj == nil || (obj?["ok"] as? Bool) == false && obj?["test"] == nil { self.test = "no answer" }
            else { self.test = String(format: "answered in %.1f s", secs) }
        }
    }

    func connect(_ id: String?) {
        let key = id ?? "all"
        guard !busy.contains(key) else { return }
        busy.insert(key)
        engine.json(["mcp", "--install"] + (id.map { [$0] } ?? []), timeout: 120) { [weak self] _ in self?.busy.remove(key); self?.load() }
    }

    /// `mcp --install <id> --replace`: writes the entry again over one that does not work.
    func fix(_ id: String) {
        guard !busy.contains(id) else { return }
        busy.insert(id)
        engine.json(["mcp", "--install", id, "--replace"], timeout: 120) { [weak self] obj in
            guard let self else { return }
            self.busy.remove(id)
            let got = ((obj?.values.first as? String) ?? "").lowercased()
            let name = (self.apps.first { $0.id == id }?.name ?? id).replacingOccurrences(of: " desktop", with: "")
            // the button must always answer: what was done, and the one thing left for them to do
            if got.hasPrefix("skipped") { self.said[id] = "could not fix it: " + got.replacingOccurrences(of: "skipped: ", with: "") + "." }
            else if got.isEmpty { self.said[id] = "no answer from the engine. try again." }
            else { self.said[id] = "done: \(name) now points at this archive. quit \(name) and open it again so it loads context." }
            self.load()
        }
    }

    /// `report --out <file>`: what worked and what broke on this mac, with nothing personal in it, as a file to read and send.
    func saveReport() {
        guard !reporting else { return }
        let dir = engine.file("reports")
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let file = dir.appendingPathComponent("context-report-" + Words.isoDay(Date()) + ".txt")
        reporting = true
        var wrote = ""
        let p = engine.stream(["report", "--out", file.path], line: { line in if wrote.isEmpty, line.hasPrefix("/") { wrote = line.trimmingCharacters(in: .whitespaces) } },
                              done: { [weak self] in self?.reporting = false; self?.report = wrote.isEmpty ? "" : (wrote as NSString).abbreviatingWithTildeInPath })
        if p == nil { reporting = false }
    }

    func remove(_ id: String) {
        guard !busy.contains(id) else { return }
        busy.insert(id)
        engine.json(["mcp", "--remove", id], timeout: 60) { [weak self] _ in self?.busy.remove(id); self?.load() }
    }

    func set(_ key: String, _ value: String) {
        engine.json(["settings", "--set", "\(key)=\(value)"], timeout: 30) { [weak self] _ in self?.load() }
    }

    /// `python3 -m ctx understand`: read what has not been read through yet.
    func readRest() {
        guard !reading else { return }
        reading = true
        engine.json(["understand"], timeout: 3600) { [weak self] _ in self?.reading = false; self?.load() }
    }

    /// Copies the rows, the pages written from them, the journal, the chats and the owner's rules to a place the user
    /// picks (ArchiveCopy): no sign-in, key, token, backup or raw export. Nothing is deleted or moved.
    func exportCopy() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.canCreateDirectories = true
        panel.prompt = "copy here"
        guard panel.runModal() == .OK, let dest = panel.url else { return }
        let from = URL(fileURLWithPath: archivePath)
        let to = dest.appendingPathComponent("context-archive-" + Words.isoDay(Date()))
        exported = "copying"
        DispatchQueue.global(qos: .utility).async {
            let ok = ArchiveCopy(from).copy(to: to)
            DispatchQueue.main.async { self.exported = ok ? "copied to \(to.lastPathComponent): the rows, pages, journal, chats and rules, and nothing else" : "could not copy there" }
        }
    }

    static func size(_ bytes: Double) -> String {
        bytes >= 1e9 ? String(format: "%.1f gb", bytes / 1e9) : (bytes >= 1e6 ? "\(Int(bytes / 1e6)) mb" : "\(Int(bytes / 1e3)) kb")
    }
}

/// A copy of the archive folder that holds what was read and what was written from it, and nothing else. It copies
/// by name (an allow list): a file or folder the list does not name stays on this mac. What stays is, among the rest:
/// telegram's sign-in (a whole telegram account, signed in until the device is ended in telegram's settings), the api
/// keys, the remote url's secret, the .env, the key the browser's helper checks its jobs with, backups (whole copies of
/// other apps' configs, with their servers' tokens, and the rows the owner asked to forget), the raw exports in imports
/// (kept as they came, before the scrubber), caches, logs and settings.
final class ArchiveCopy: NSObject, FileManagerDelegate {
    let from: URL
    init(_ from: URL) { self.from = from }

    /// The files at the top of the archive that are copied: the rows, what was worked out from them, and the owner's
    /// own rules (rules.json, never.json, and forgotten.json, which holds ids only).
    static let files: Set<String> = ["messages.jsonl", "sessions.jsonl", "prompts.jsonl", "mail_index.jsonl", "docs.jsonl", "scores.jsonl", "ledger.jsonl",
                                     "loops.json", "loops.md", "journal_edits.json", "app-corrections.json", "rules.json", "never.json", "forgotten.json"]
    /// The folders at the top of the archive that are copied: the rows of each source, the pages written from them (the
    /// wiki, the short pages, the cards), the journal, what was made here and the saved chats. Only their pages and rows
    /// go: markdown and json.
    static let folders: Set<String> = ["parts", "memory", "journal", "made", "chats"]
    static let kinds: Set<String> = ["md", "json", "jsonl"]

    /// Whether a path inside the archive, relative to it, goes into the copy. `folder`: it is a folder, not a file or a link.
    static func copied(_ rel: String, folder: Bool) -> Bool {
        let parts = rel.split(separator: "/").map(String.init)
        guard let top = parts.first else { return false }
        if parts.count == 1 { return folder ? folders.contains(top) : files.contains(top) }
        guard folders.contains(top), !parts.contains(where: secret) else { return false }
        // a folder inside one that is copied is gone through; a file goes only when it is a page or rows
        return folder || kinds.contains((parts[parts.count - 1] as NSString).pathExtension.lowercased())
    }

    /// A name that stays on this mac wherever it is: any hidden file (the .env among them), a sign-in (*.session*), a
    /// key (*.pem, *.key, *.p12, a file called key, an ssh key), a json named for a token, a secret, a password or a
    /// credential, a backups folder, and a folder of forgotten rows. A page or a file of rows is named for what it is
    /// about ("projects/the-token.md"), so the token rule reads only json.
    static func secret(_ name: String) -> Bool {
        let n = name.lowercased(), ext = (n as NSString).pathExtension
        if n.hasPrefix(".") || n.contains(".session") || n == "key" || n == "backups" || n.hasPrefix("forgotten-") || n == "agent.runs" { return true }
        if ["id_rsa", "id_dsa", "id_ecdsa", "id_ed25519"].contains(where: n.hasPrefix) || ["pem", "key", "p12", "pfx", "ppk", "keystore", "jks", "token", "secret"].contains(ext) { return true }
        guard ext == "json" else { return false }
        let words = (n as NSString).deletingPathExtension.split { !($0.isLetter || $0.isNumber) }.map(String.init)
        let named = ["token", "tokens", "secret", "secrets", "password", "passwords", "passwd", "credential", "credentials", "cookie", "cookies", "apikey", "apikeys"]
        guard let w = words.last else { return false }
        return named.contains(w) || (["key", "keys"].contains(w) && words.count > 1 && ["api", "private"].contains(words[words.count - 2]))
    }

    func copy(to: URL) -> Bool {
        let fm = FileManager()
        fm.delegate = self
        return (try? fm.copyItem(at: from, to: to)) != nil
    }

    /// An item's path below the archive, relative to it: "" for the archive itself, nil for anything not found under it.
    /// Both sides are tried as given and with their folders' links resolved (/var is /private/var).
    func relative(_ src: URL) -> String? {
        let item = src.deletingLastPathComponent().resolvingSymlinksInPath().path + "/" + src.lastPathComponent
        for root in [from.standardizedFileURL.path, from.resolvingSymlinksInPath().path] {
            for p in [src.standardizedFileURL.path, item] {
                if p == root { return "" }
                if p.hasPrefix(root + "/") { return String(p.dropFirst(root.count + 1)) }
            }
        }
        return nil
    }

    func fileManager(_ fileManager: FileManager, shouldCopyItemAt src: URL, to dst: URL) -> Bool {
        // the list copies only what it can name: an item not found under the archive is left
        guard let rel = relative(src) else { return false }
        // a link is judged as a file, and copied as a link: what it points at is never read
        let folder = (try? src.resourceValues(forKeys: [.isDirectoryKey, .isSymbolicLinkKey])).map { $0.isDirectory == true && $0.isSymbolicLink != true } ?? false
        return rel.isEmpty || ArchiveCopy.copied(rel, folder: folder)
    }
}


// MARK: the page: a list of panes on the left, one pane at a time on the right

enum SettingsPane: String, CaseIterable, Identifiable {
    case general, models, ais, keys, sync, permissions, data, notifications, about
    var id: String { rawValue }
    var word: String {
        switch self {
        case .general: return "general"
        case .models: return "models"
        case .ais: return "connected ais"
        case .keys: return "what can read"
        case .sync: return "sources & sync"
        case .permissions: return "permissions"
        case .data: return "your data"
        case .notifications: return "notifications"
        case .about: return "about"
        }
    }
    var symbol: String {
        switch self {
        case .general: return "slider.horizontal.3"
        case .models: return "cpu"
        case .ais: return "point.3.connected.trianglepath.dotted"
        case .keys: return "key"
        case .sync: return "arrow.triangle.2.circlepath"
        case .permissions: return "lock"
        case .data: return "externaldrive"
        case .notifications: return "bell"
        case .about: return "info.circle"
        }
    }
}

extension AppModel {
    /// Settings, at one pane: the door for anything outside the page that points into it.
    func openSettings(_ pane: SettingsPane) {
        guard saved.onboarded else { return }
        settingsPane = pane
        go(.settings)
    }

    /// Whether a pane has something that waits on them, for the dot beside its name.
    func needsYou(_ pane: SettingsPane) -> Bool {
        switch pane {
        case .models: return planTrouble != nil
        case .ais: return settings.apps.contains { $0.broken || $0.changed }
        case .keys: return keys.notice != nil
        case .permissions: return !access || !browserOn
        default: return false
        }
    }
}

extension Words {
    /// "14:00", on this mac's clock
    static func hourMinute(_ d: Date) -> String {
        let c = Calendar.current.dateComponents([.hour, .minute], from: d)
        return String(format: "%02d:%02d", c.hour ?? 0, c.minute ?? 0)
    }
}

/// How a thing stands, in a word or two, as a small pill. Never bold text in a column.
enum Tone { case good, warn, quiet }

struct Pill: View {
    let text: String
    var tone: Tone = .quiet
    var body: some View {
        HStack(spacing: 5) {
            Circle().fill(tone == .good ? Ink.ink : (tone == .warn ? Ink.ember : Color.clear))
                .overlay(Circle().strokeBorder(Ink.soft, lineWidth: tone == .quiet ? 1 : 0))
                .frame(width: 6, height: 6)
            Text(text).font(.system(size: Face.micro, weight: .medium)).foregroundStyle(tone == .quiet ? Ink.soft : Ink.ink).lineLimit(1).fixedSize()
        }
        // how a thing stands is a dot and a word beside its name: no ground under it, so it is not taken for a button
        .frame(height: 18)
        .fixedSize()
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(text)
        .probe("setting.pill", .line, group: "", scrolls: true)
    }
}

/// Every word on the settings page is made here, so none can be cut: a sentence wraps to as many lines as it
/// needs, and a label keeps its own width. The gate measures both, and reads these files for a limit set any other way.
enum SetText {
    static func title(_ s: String) -> some View {
        Text(s).font(.system(size: Face.label, weight: .medium)).foregroundStyle(Ink.ink)
            .fixedSize(horizontal: false, vertical: true)
            .probe("setting.title", .text, scrolls: true)
    }
    static func about(_ s: String, _ color: Color = Ink.soft) -> some View {
        Text(s).font(.system(size: 12)).foregroundStyle(color).lineSpacing(2.5)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
            .probe("setting.about", .text, scrolls: true)
    }
    /// a path or a name of a key: the letters as written, each the same width, free to break anywhere
    static func mono(_ s: String) -> some View {
        Text(s).font(.system(size: 11, design: .monospaced)).foregroundStyle(Ink.soft).lineSpacing(2)
            .fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
            .frame(maxWidth: .infinity, alignment: .leading)
            .probe("setting.mono", .text, scrolls: true)
    }
    static func label(_ s: String, size: CGFloat = 12, weight: Font.Weight = .medium, color: Color = Ink.soft) -> some View {
        Text(s).font(.system(size: size, weight: weight)).monospacedDigit().foregroundStyle(color).lineLimit(1).fixedSize()
            .probe("setting.label", .line, scrolls: true)
    }
}

/// A few rows that belong together, under their name, on a raised ground.
struct SetCard<Content: View>: View {
    let title: String
    var note = ""
    @ViewBuilder var content: () -> Content

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            // the group's name is a small heading; the rows under it carry the names the owner reads. two weights, two sizes
            Text(title).font(Face.heading).foregroundStyle(Ink.soft).fixedSize(horizontal: false, vertical: true)
                .accessibilityAddTraits(.isHeader)
                .probe("setting.card.title", .text, scrolls: true)
            if !note.isEmpty { SetText.about(note).padding(.top, Space.xs) }
            VStack(alignment: .leading, spacing: 0) { content() }
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Ink.raised, in: RoundedRectangle(cornerRadius: Radius.card, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: Radius.card, style: .continuous).strokeBorder(Ink.line, lineWidth: 1))
                .probe("setting.card", .block, group: "setting.cards", scrolls: true)
                .padding(.top, Space.s)
        }
        .padding(.bottom, Space.xxl)
    }
}

/// One thing on a card: its name, a pill for how it stands, a full sentence under it, and at the right the one control.
/// `more` is what unfolds under the sentence: a path behind "details", a list behind "choose per job".
struct SetRow<Control: View, More: View>: View {
    let title: String
    var about = ""
    var pill = ""
    var tone: Tone = .quiet
    var icon = ""              // a source's or an app's own icon
    var last = false
    @ViewBuilder var control: () -> Control
    @ViewBuilder var more: () -> More

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            if !icon.isEmpty { SourceIcon(id: icon, size: 22).padding(.top, 1).accessibilityHidden(true) }
            VStack(alignment: .leading, spacing: 4) {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    SetText.title(title)
                    if !pill.isEmpty { Pill(text: pill, tone: tone) }
                }
                if !about.isEmpty { SetText.about(about) }
                more()
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            control().padding(.top, 1)
        }
        .padding(.horizontal, Space.l).padding(.vertical, 14)
        .overlay(alignment: .bottom) { if !last { Rectangle().fill(Ink.line).frame(height: 1).padding(.leading, Space.l) } }
        .probe("setting.row", .block, group: "setting.rows", scrolls: true)
    }
}

extension SetRow where More == EmptyView {
    init(title: String, about: String = "", pill: String = "", tone: Tone = .quiet, icon: String = "", last: Bool = false, @ViewBuilder control: @escaping () -> Control) {
        self.init(title: title, about: about, pill: pill, tone: tone, icon: icon, last: last, control: control, more: { EmptyView() })
    }
}

extension SetRow where Control == EmptyView, More == EmptyView {
    init(title: String, about: String = "", pill: String = "", tone: Tone = .quiet, icon: String = "", last: Bool = false) {
        self.init(title: title, about: about, pill: pill, tone: tone, icon: icon, last: last, control: { EmptyView() }, more: { EmptyView() })
    }
}

/// The one button a row carries: an outlined word.
struct SetButton: View {
    let word: String
    var busy = false
    let action: () -> Void
    var body: some View {
        Button(word, action: action).buttonStyle(SetButtonStyle()).ring(14, inset: 1)
            .disabled(busy).opacity(busy ? 0.6 : 1)
            .probe("setting.control", .button, scrolls: true)
    }
}

/// A word on a faint tint of the ink, which reads on the paper and on a raised card, light and dark, with no outline.
struct SetButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View { Look(configuration: configuration) }
    struct Look: View {
        let configuration: Configuration
        @State private var hover = false
        var body: some View {
            configuration.label
                .font(.system(size: Face.small, weight: .medium)).lineLimit(1).fixedSize()
                .foregroundStyle(Ink.ink)
                .padding(.horizontal, Space.m).frame(height: 26)
                .background(Capsule().fill(Ink.ink.opacity(hover ? 0.12 : 0.07)))
                .scaleEffect(configuration.isPressed ? Motion.press : 1)
                .animation(.spring(response: 0.22, dampingFraction: 0.8), value: configuration.isPressed)
                .animation(Motion.hover, value: hover)
                .contentShape(Capsule())
                .onHover { hover = $0 }
        }
    }
}

/// A switch, for a thing that is on or off.
struct SetSwitch: View {
    let label: String              // what it switches, for voiceover: the row's own name
    let on: Bool
    var enabled = true
    let set: (Bool) -> Void
    @Environment(\.accessibilityReduceMotion) private var reduce
    var body: some View {
        Button { set(!on) } label: {
            ZStack(alignment: on ? .trailing : .leading) {
                Capsule().fill(on ? Ink.ink : Ink.line).overlay(Capsule().strokeBorder(Ink.faint.opacity(on ? 0 : 0.55), lineWidth: 1)).frame(width: 34, height: 20)
                Circle().fill(on ? Ink.raised : Ink.soft).frame(width: 16, height: 16).padding(.horizontal, 2)
            }
            .animation(Motion.quick(reduce), value: on)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain).ring(11, inset: -2)
        .disabled(!enabled).opacity(enabled ? 1 : 0.45)
        .accessibilityLabel(label).accessibilityValue(on ? "on" : "off")
        .accessibilityAddTraits(on ? .isSelected : [])
        .probe("setting.control", .button, scrolls: true)
    }
}

/// A menu, for one of several: the word it stands at, and a small arrow.
struct SetMenu<Items: View>: View {
    let word: String
    let label: String              // what it chooses, for voiceover
    @ViewBuilder var items: () -> Items
    var body: some View {
        Menu { items() } label: {
            HStack(spacing: 5) {
                Text(word).font(.system(size: 12, weight: .semibold)).foregroundStyle(Ink.ink).lineLimit(1).fixedSize()
                Image(systemName: "chevron.down").font(.system(size: 7.5, weight: .bold)).foregroundStyle(Ink.soft)
            }
            .padding(.horizontal, 12).frame(height: 28).background(Capsule().fill(Ink.ink.opacity(0.08))).contentShape(Capsule())
        }
        .menuStyle(.button).buttonStyle(.plain).menuIndicator(.hidden).fixedSize()
        .accessibilityLabel(label + ": " + word)
        .probe("setting.control", .button, scrolls: true)
    }
}

/// A quiet word that opens what is folded under a row.
struct SetFold: View {
    let word: String
    @Binding var open: Bool
    var body: some View {
        Button { open.toggle() } label: {
            HStack(spacing: 4) {
                Text(open ? "hide " + word : word)
                Image(systemName: "chevron.down").font(.system(size: 7, weight: .bold)).rotationEffect(.degrees(open ? 180 : 0))
            }
        }
        .buttonStyle(QuietButton(size: 12)).fixedSize()
        .accessibilityLabel(open ? "hide " + word : "show " + word)
        .probe("setting.fold", .button, scrolls: true)
    }
}

struct SettingsView: View {
    @Environment(AppModel.self) private var model
    private let poll = Timer.publish(every: 2, on: .main, in: .common).autoconnect()
    static let list: CGFloat = 176

    var body: some View {
        let st = model.settings
        HStack(alignment: .top, spacing: 0) {
            VStack(alignment: .leading, spacing: 1) {
                ForEach(SettingsPane.allCases) { pane in
                    PaneRow(pane: pane, on: model.settingsPane == pane, dot: model.needsYou(pane)) { model.settingsPane = pane }
                }
            }
            .frame(width: SettingsView.list - 16)
            .padding(.leading, 16).padding(.top, 12)
            .probe("setting.list", .block)
            ScrollView {
                ScrollTop()
                VStack(alignment: .leading, spacing: 0) {
                    Text(model.settingsPane.word).font(Face.said(26)).tracking(-0.4).foregroundStyle(Ink.ink)
                        .fixedSize(horizontal: false, vertical: true)
                        .accessibilityAddTraits(.isHeader)
                        .probe("setting.heading", .text, scrolls: true)
                        .padding(.bottom, Space.xl)
                    pane(st)
                }
                .frame(maxWidth: 620, alignment: .leading)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.leading, 28).padding(.trailing, 32).padding(.top, 14).padding(.bottom, 40)
                // a pane is a page of its own: the one before is cut and this one arrives
                .modifier(PageIn())
                .id(model.settingsPane)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .onAppear { if !Probe.on { st.load(); model.loadPlan(); model.loadModels(); model.wikiBuild.load(); model.exports.load(model.engine); model.keys.load(model.engine) } }
        .onReceive(poll) { _ in model.pollSwitches(deep: false); model.pollPermissions() }
    }

    @ViewBuilder private func pane(_ st: SettingsModel) -> some View {
        switch model.settingsPane {
        case .general: GeneralPane()
        case .models: ModelsPane()
        case .ais: AIsPane()
        case .keys: KeysPane()
        case .sync: SyncPane()
        case .permissions: PermissionsPane()
        case .data: DataPane()
        case .notifications: NotificationsPane()
        case .about: AboutPane()
        }
    }

    /// "14 nov 10:02"
    static func stamp(_ at: Double, zone: TimeZone = .current) -> String {
        let d = Date(timeIntervalSince1970: at)
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = zone
        let c = cal.dateComponents([.month, .day, .hour, .minute], from: d)
        return "\(c.day ?? 1) \(Words.months[(c.month ?? 1) - 1]) " + String(format: "%02d:%02d", c.hour ?? 0, c.minute ?? 0)
    }
}

/// One pane's name in the list on the left, with a dot when something in it waits on them.
struct PaneRow: View {
    let pane: SettingsPane
    let on: Bool
    let dot: Bool
    let action: () -> Void
    @State private var hover = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: 8) {
                Image(systemName: pane.symbol).font(.system(size: Face.small)).foregroundStyle(on || hover ? Ink.ink : Ink.soft).frame(width: 18)
                Text(pane.word).font(.system(size: Face.label, weight: on ? .medium : .regular)).foregroundStyle(Ink.ink).lineLimit(1).fixedSize()
                    .probe("setting.pane.word", .line)
                Spacer(minLength: 4)
                if dot { Circle().fill(Ink.ember).frame(width: 6, height: 6).accessibilityHidden(true) }
            }
            .padding(.horizontal, 10).frame(height: 30)
            .background(Ink.ink.opacity(on ? 0.075 : (hover ? 0.04 : 0)), in: RoundedRectangle(cornerRadius: Radius.row, style: .continuous))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
        .accessibilityLabel(pane.word + (dot ? ", needs you" : ""))
        .accessibilityAddTraits(on ? .isSelected : [])
        .ring(Radius.row, inset: 0)
        .probe("setting.pane", .block, group: "setting.panes")
    }
}
