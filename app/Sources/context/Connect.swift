import AppKit
import Observation
import SwiftUI

/// An app or service that could be connected.
struct Found: Identifiable, Equatable {
    let id: String
    let name: String
    let kind: String          // app, service
    let installed: Bool
    let iconPath: String
    let known: Bool
    var what = ""             // one sentence from the engine: what adding it will do

    /// The word at the right of a row: where it is, or what kind of thing it is.
    var word: String {
        if installed { return "on this mac" }
        switch kind {
        case "service": return "service"
        case "site": return "website"
        case "feed": return "feed"
        case "folder": return "folder"
        case "file": return "file"
        case "repo": return "github repo"
        case "channel", "youtube": return "youtube channel"
        case "note": return "your own notes"
        case "app": return "not installed"
        default: return kind
        }
    }

    /// What its rows are called: "40 posts since 2018".
    static func unit(_ kind: String, _ n: Int) -> String {
        let one = ["site": "page", "feed": "post", "folder": "file", "file": "part", "repo": "item", "youtube": "video", "channel": "video", "note": "note"][kind] ?? "row"
        return n == 1 ? one : one + "s"
    }

    /// Typed or dropped by them, not found among apps: the engine reads it as it stands.
    var canvas: Bool { ["site", "feed", "folder", "file", "repo", "youtube", "channel", "note"].contains(kind) }

    /// A picture for a thing that has no app icon.
    var symbol: String {
        ["site": "globe", "feed": "dot.radiowaves.up.forward", "folder": "folder", "file": "doc", "repo": "chevron.left.forwardslash.chevron.right", "channel": "play.rectangle", "youtube": "play.rectangle", "note": "square.and.pencil"][kind] ?? ""
    }
}

/// What the engine worked out about reading one.
struct ConnectResult: Equatable {
    let id: String
    let name: String
    let state: String         // ready, needs_you, cannot
    let how: String
    let rows: Int
    let since: String
    let detail: String
    var source = ""           // the source it becomes once added: "canvas_<slug>"
    var kind = ""
    var question = ""         // the engine asks before it reads: "only the posts, or every page?"
    var choices: [Choice] = []
    struct Choice: Equatable, Identifiable { var label: String; var only: String; var id: String { only + label } }

    init?(_ d: [String: Any]?) {
        guard let d else { return nil }
        // the engine could not even start: its own sentence, as something that cannot be read
        if let e = d["error"] as? String, !e.isEmpty, d["state"] == nil {
            id = d["id"] as? String ?? ""; state = "cannot"; name = (d["name"] as? String ?? "this").lowercased(); how = ""; rows = 0; since = ""; detail = e.lowercased()
            return
        }
        guard let id = d["id"] as? String, let state = d["state"] as? String else { return nil }
        source = d["source"] as? String ?? ""
        kind = d["kind"] as? String ?? ""
        if let ask = d["ask"] as? [String: Any] {
            question = (ask["question"] as? String ?? "").lowercased()
            choices = ((ask["choices"] as? [[String: Any]]) ?? []).compactMap { c in
                guard let label = c["label"] as? String, !label.isEmpty else { return nil }
                let pages = c["pages"] as? Int ?? 0
                return Choice(label: label.lowercased() + (pages > 0 ? "  ·  \(Words.count(pages))" : ""), only: c["only"] as? String ?? "all")
            }
        }
        self.id = id
        self.state = state
        name = (d["name"] as? String ?? id).lowercased()
        how = (d["how"] as? String ?? "").lowercased()
        detail = (d["detail"] as? String ?? "").lowercased()
        let sample = d["sample"] as? [String: Any]
        rows = sample?["rows"] as? Int ?? 0
        since = sample?["since"] as? String ?? ""
    }

    /// "found granola's notes in its app folder. 300 rows since may 2024. add it?"
    var sentence: String {
        switch state {
        case "ready":
            var s = how.isEmpty ? "context can read \(name)." : how
            if !s.hasSuffix(".") { s += "." }
            if rows > 0 { s += " \(Words.count(rows)) \(Found.unit(kind, rows))" + (since.isEmpty ? "." : " since \(since.count == 4 ? since : Words.monthLong(since)).") }
            return s + (choices.isEmpty ? " add it?" : " " + question)
        case "needs_you": return detail.isEmpty ? (how.isEmpty ? "\(name) needs something from you first." : how) : detail
        default:
            // the engine's own reason, in its words; without one, the plain fact
            let why = detail.isEmpty ? how : detail
            return "context cannot read \(name) yet." + (why.isEmpty ? "" : " " + why + (why.hasSuffix(".") ? "" : "."))
        }
    }
}

/// The add sheet's state: search, pick, watch the engine work it out, then add or not.
@Observable final class AddModel {
    enum Stage: Equatable { case search, working, result(ConnectResult), note, added, unavailable }
    var noteText = ""               // their own notes, as the owner writes or pastes them
    var noteLoaded = false
    var only = ""                   // the part the owner chose, when the engine asked which
    @ObservationIgnored private var call: Int?
    var query = "" { didSet { if query != oldValue { search() } } }
    var results: [Found] = []
    var searching = false           // asked, and the engine has not answered yet
    var selected = 0
    var stage = Stage.search
    var picked: Found?
    var phases: [String] = []
    var since = Date()

    @ObservationIgnored private let engine: Engine
    @ObservationIgnored private var work: DispatchWorkItem?
    @ObservationIgnored private var process: Process?

    init(engine: Engine) { self.engine = engine }

    /// `python3 -m ctx connect --search "<q>"`: apps on this mac and services the engine knows.
    private func search() {
        work?.cancel()
        let q = query.trimmingCharacters(in: .whitespaces)
        guard q.count >= 2, stage == .search else { results = []; searching = false; return }
        searching = true               // from the first key: "nothing by that name" is only said once the engine has answered
        let w = DispatchWorkItem { [weak self] in
            guard let self else { return }
            func take(_ rows: [[String: Any]]) {
                self.searching = false
                self.results = Array(rows.compactMap { r -> Found? in
                    guard let id = r["id"] as? String else { return nil }
                    return Found(id: id, name: (r["name"] as? String ?? id).lowercased(), kind: r["kind"] as? String ?? "app",
                                 installed: r["installed"] as? Bool ?? false, iconPath: r["icon_path"] as? String ?? r["app_path"] as? String ?? "", known: r["known"] as? Bool ?? false,
                                 what: (r["what"] as? String ?? r["does"] as? String ?? r["about"] as? String ?? "").lowercased())
                }.prefix(7))
                self.selected = 0
            }
            // the warm engine first: it also knows a website, a feed, a folder, a file, and always offers their own notes
            self.engine.client.call(["cmd": "connect-search", "q": q], timeout: 20) { [weak self] reply in
                guard let self, self.query.trimmingCharacters(in: .whitespaces) == q, self.stage == .search else { return }
                if let rows = reply as? [[String: Any]] { take(rows); return }
                self.engine.json(["connect", "--search", q], timeout: 20) { [weak self] obj in
                    guard let self, self.query.trimmingCharacters(in: .whitespaces) == q, self.stage == .search else { return }
                    guard let rows = obj?["list"] as? [[String: Any]] else { self.searching = false; self.stage = .unavailable; return }     // no such command yet
                    take(rows)
                }
            }
        }
        work = w
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.25, execute: w)
    }

    func move(_ by: Int) { if !results.isEmpty { selected = max(0, min(results.count - 1, selected + by)) } }

    /// `python3 -u -m ctx connect <id>`: the engine works out, on the user's own plan, how to read this one.
    /// It says what it is doing in lines that start with @, then one last line with the verdict.
    func pick(_ f: Found? = nil, only: String = "") {
        guard stage == .search, let f = f ?? (results.indices.contains(selected) ? results[selected] : nil) else { return }
        picked = f
        phases = []
        since = Date()
        self.only = only
        // their own notes: nothing to work out, a page to write on
        if f.kind == "note" { openNote(f); return }
        stage = .working
        var last: [String: Any]?
        // the warm engine tries it and says what it is doing as it goes; a site can take most of a minute
        if let w = engine.client.warmEngine {
            var request: [String: Any] = ["cmd": "connect", "source": f.id]
            if !only.isEmpty { request["only"] = only }
            var result: [String: Any]?
            call = w.send(request, event: { [weak self] d in
                if let p = d["phase"] as? String, !p.isEmpty { self?.phases.append(p.lowercased()) }
                if let r = d["result"] as? [String: Any] { result = r }
            }, end: { [weak self] in
                guard let self, self.stage == .working, self.picked?.id == f.id else { return }
                self.call = nil
                if let r = ConnectResult(result) { self.stage = .result(r) } else { self.viaProcess(f) }
            })
            if call != nil { return }
        }
        viaProcess(f)
    }

    /// The same through the command line, for an engine with no warm `connect`.
    private func viaProcess(_ f: Found) {
        var last: [String: Any]?
        process = engine.stream(["connect", f.id], line: { [weak self] line in
            if line.hasPrefix("@"), let d = (try? JSONSerialization.jsonObject(with: Data(line.dropFirst().utf8))) as? [String: Any],
               let phase = d["phase"] as? String {
                self?.phases.append(phase.lowercased())
            } else if line.hasPrefix("{"), let d = (try? JSONSerialization.jsonObject(with: Data(line.utf8))) as? [String: Any] {
                last = d
            }
        }, done: { [weak self] in
            guard let self, self.stage == .working else { return }
            self.process = nil
            self.stage = ConnectResult(last).map { .result($0) } ?? .unavailable
        })
        if process == nil { stage = .unavailable }
    }

    /// `python3 -m ctx connect --enable <id>`, then read it like any other source.
    func add() {
        guard case .result(let r) = stage, r.state == "ready" else { return }
        stage = .added
        func read(_ id: String) {
            if !engine.order.contains(id) { engine.order.append(id) }
            engine.readRun.remove(id)
            engine.read(id, first: true)
        }
        var request: [String: Any] = ["cmd": "connect-enable", "source": r.source.isEmpty ? r.id : r.source, "on": true]
        if !only.isEmpty { request["only"] = only }
        engine.client.call(request, timeout: 60) { [weak self] reply in
            guard let self else { return }
            if let d = reply as? [String: Any], d["error"] == nil { read(d["source"] as? String ?? (r.source.isEmpty ? r.id : r.source)); return }
            if let d = reply as? [String: Any], let e = d["error"] as? String { self.stage = .result(ConnectResult(["id": r.id, "name": r.name, "error": e])!); return }
            self.engine.json(["connect", "--enable", r.id], timeout: 60) { _ in read(r.id) }
        }
    }

    /// The engine asked which part to read, and the owner chose: the trial runs again with that.
    func choose(_ c: ConnectResult.Choice) {
        guard let f = picked else { return }
        stage = .search
        pick(f, only: c.only)
    }

    /// Their own notes under this name: the page as it stands, to write on.
    private func openNote(_ f: Found) {
        noteText = ""
        noteLoaded = Engine.debug
        stage = .note
        engine.client.call(["cmd": "note", "name": AddModel.noteName(f)], timeout: 20) { [weak self] reply in
            guard let self, self.stage == .note, self.picked?.id == f.id else { return }
            if self.noteText.isEmpty, let t = (reply as? [String: Any])?["text"] as? String { self.noteText = t }
            self.noteLoaded = true
        }
    }

    static func noteName(_ f: Found) -> String { f.id.hasPrefix("note:") ? String(f.id.dropFirst(5)) : f.name }

    /// Keeps the page as the owner left it, and reads it in.
    func saveNote() {
        guard stage == .note, let f = picked else { return }
        let text = noteText
        stage = .added
        engine.client.call(["cmd": "note", "name": AddModel.noteName(f), "text": text, "mode": "replace"], timeout: 30) { [weak self] reply in
            guard let self else { return }
            guard let d = reply as? [String: Any], d["error"] == nil, let src = d["source"] as? String else {
                self.noteText = text
                self.stage = .result(ConnectResult(["id": f.id, "name": f.name, "error": (reply as? [String: Any])?["error"] as? String ?? "the engine did not keep the note. it is still here: try again."])!)
                return
            }
            if !self.engine.order.contains(src) { self.engine.order.append(src) }
            self.engine.readRun.remove(src)
            self.engine.read(src, first: true)
        }
    }

    /// Back to the search, to look for something else.
    func back() {
        picked = nil
        phases = []
        stage = .search
        query = ""
        results = []
        searching = false
    }

    func again() {
        guard let f = picked else { return }
        stage = .search
        pick(f, only: only)
    }

    func cancel() {
        work?.cancel()
        if let call, let w = engine.client.warmEngine { w.cancel(call); w.finish(call) }
        call = nil
        process?.terminate()
        process = nil
    }
}

extension Engine {
    /// Runs one engine command and hands over its output a line at a time, on the main thread.
    func stream(_ args: [String], line: @escaping (String) -> Void, done: @escaping () -> Void) -> Process? {
        guard let repo else { return nil }
        let p = Engine.python(args, repo: repo)
        let out = Pipe()
        p.standardOutput = out
        p.standardError = FileHandle.nullDevice
        var buffer = Data()
        let lock = NSLock()
        out.fileHandleForReading.readabilityHandler = { h in
            let d = h.availableData
            guard !d.isEmpty else { return }
            lock.lock()
            buffer.append(d)
            var lines: [String] = []
            while let nl = buffer.firstIndex(of: 0x0A) {
                lines.append(String(decoding: buffer[buffer.startIndex..<nl], as: UTF8.self))
                buffer.removeSubrange(buffer.startIndex...nl)
            }
            lock.unlock()
            DispatchQueue.main.async { lines.forEach(line) }
        }
        p.terminationHandler = { _ in
            out.fileHandleForReading.readabilityHandler = nil
            // whatever is still in the pipe, however long the last line is, without waiting on a pipe a child holds open
            lock.lock()
            let rest = String(decoding: buffer + EngineCall.drain(out.fileHandleForReading), as: UTF8.self)
            buffer = Data()
            lock.unlock()
            DispatchQueue.main.async {
                rest.split(separator: "\n").map(String.init).forEach(line)
                done()
            }
        }
        do { try p.run() } catch { return nil }
        DispatchQueue.global().asyncAfter(deadline: .now() + 240) { if p.isRunning { p.terminate() } }
        return p
    }
}

/// The add sheet: a small panel over home. Search, then a short honest exchange, then add or not now.
struct AddSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduce
    @Bindable var add: AddModel
    @FocusState private var focused: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            AddRail(step: AddRail.step(add.stage)).padding(.bottom, 14)
            switch add.stage {
            case .search: search
            case .working: working
            case .result(let r): result(r)
            case .note: note
            case .added: said("added. it is being read now, and will be on the shelf in a moment.", buttons: [("done", true, { model.closeAdd() })])
            case .unavailable: said("context cannot add apps by itself yet.", buttons: [("ok", true, { model.closeAdd() })])
            }
        }
        .padding(22)
        .frame(width: 460, alignment: .leading)
        .background(Ink.paper, in: RoundedRectangle(cornerRadius: Radius.field, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: Radius.field, style: .continuous).strokeBorder(Ink.line, lineWidth: 1))
        .shadow(color: .black.opacity(0.14), radius: 30, y: 14)
        .probe("add.sheet", .block)
        // a folder or a file dropped on the panel is typed for them
        .onDrop(of: [.fileURL], isTargeted: nil) { items in
            guard let item = items.first else { return false }
            _ = item.loadObject(ofClass: URL.self) { url, _ in
                guard let url else { return }
                DispatchQueue.main.async { if add.stage != .search { add.back() }; add.query = url.path }
            }
            return true
        }
        .animation(Motion.spring(reduce), value: add.stage)
        .animation(Motion.quick(reduce), value: add.results)
    }

    private var search: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("add a source").font(.system(size: 10.5, weight: .medium, design: .monospaced)).foregroundStyle(Ink.faint)
            TextField("", text: $add.query, prompt: Text("an app, a service, a website, a folder").foregroundStyle(Ink.faint))
                .tint(Ink.ember)
                .textFieldStyle(.plain)
                // what the owner types is set in the serif, as a line said: at 22 pt the whole prompt fits the panel
                .font(Face.said(22)).tracking(-0.3)
                .foregroundStyle(Ink.ink)
                .focused($focused)
                .padding(.top, 8)
                .onAppear { DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) { focused = true } }
            if add.results.isEmpty {
                Text(AddSheet.hint(query: add.query, searching: add.searching))
                    .font(.system(size: 13)).foregroundStyle(Ink.faint).lineSpacing(3)
                    .fixedSize(horizontal: false, vertical: true)
                    .probe("add.hint", .text, group: "add.column")
                    .padding(.top, 12)
            } else {
                VStack(spacing: 0) {
                    ForEach(Array(add.results.enumerated()), id: \.element.id) { i, f in
                        Button { add.pick(f) } label: {
                            HStack(spacing: 10) {
                                if f.symbol.isEmpty { icon(f, 24) } else {
                                    Image(systemName: f.symbol).font(.system(size: 13, weight: .medium)).foregroundStyle(Ink.soft).frame(width: 24, height: 24)
                                        .background(Ink.wash, in: RoundedRectangle(cornerRadius: Radius.chip, style: .continuous)).accessibilityHidden(true)
                                }
                                VStack(alignment: .leading, spacing: 1) {
                                    Text(f.name).font(.system(size: 14, weight: .medium)).foregroundStyle(Ink.ink).lineLimit(1)
                                    if !f.what.isEmpty {
                                        Text(f.what).font(.system(size: 12)).foregroundStyle(Ink.soft).lineLimit(2).fixedSize(horizontal: false, vertical: true)
                                    }
                                }
                                Spacer(minLength: 8)
                                Text(f.word)
                                    .font(Face.meta).foregroundStyle(Ink.soft).lineLimit(1).fixedSize()
                            }
                            .padding(.horizontal, 10).padding(.vertical, f.what.isEmpty ? 0 : 7).frame(minHeight: 40)
                            .background(i == add.selected ? Ink.wash : .clear, in: RoundedRectangle(cornerRadius: Radius.row, style: .continuous))
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .probe("add.result", .block, group: "add.results")
                    }
                }
                .padding(.top, 12).padding(.horizontal, -10)
            }
        }
    }

    /// Under the field while there are no rows: what this is, that it is looking, or that it found nothing.
    static func hint(query: String, searching: Bool) -> String {
        if query.trimmingCharacters(in: .whitespaces).count < 2 {
            return "anything that keeps what you wrote or saved. context works out how to read it and asks before it does."
        }
        return searching ? "looking on this mac and among the services context knows."
            : "no app on this mac and no service context knows goes by that name. try the app's own name (granola, linear), a service (notion, spotify), a website's address, or a folder's path."
    }

    /// The trial read, shown as it goes: every step the engine has named, in order, the one it is on last and
    /// lit, with the seconds it has been at it. Nothing is added by this: it is one bounded read to see what is there.
    private var working: some View {
        VStack(alignment: .leading, spacing: 0) {
            head
            Text("a trial read. on your own plan; nothing is added until you say so.")
                .font(.system(size: 12)).foregroundStyle(Ink.soft).fixedSize(horizontal: false, vertical: true)
                .padding(.top, 10)
            let steps = add.phases.isEmpty ? ["working out how to read it"] : Array(add.phases.suffix(6))
            VStack(alignment: .leading, spacing: 0) {
                ForEach(Array(steps.enumerated()), id: \.offset) { i, phase in
                    let now = i == steps.count - 1
                    HStack(alignment: .firstTextBaseline, spacing: 10) {
                        Text("\(add.phases.count - steps.count + i + 1)").font(Face.meta).foregroundStyle(Ink.faint).frame(width: 14, alignment: .trailing)
                            .accessibilityHidden(true)
                        Text(phase.lowercased()).font(now ? Face.said(17) : .system(size: 13)).foregroundStyle(now ? Ink.ink : Ink.soft)
                            .fixedSize(horizontal: false, vertical: true)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .probe("add.step", .text, group: "add.steps")
                        if now {
                            TimelineView(.periodic(from: add.since, by: 1)) { t in
                                Text("\(max(0, Int(t.date.timeIntervalSince(add.since)))) s").font(Face.meta).monospacedDigit().foregroundStyle(Ink.faint).fixedSize()
                            }
                        } else {
                            Image(systemName: "checkmark").font(.system(size: 8, weight: .bold)).foregroundStyle(Ink.faint).accessibilityLabel("done")
                        }
                    }
                    .padding(.vertical, 7)
                    .overlay(alignment: .bottom) { if now { Sweep().frame(height: 1.5).padding(.leading, 24) } else { Rectangle().fill(Ink.line).frame(height: 1).padding(.leading, 24) } }
                    .transition(reduce || Probe.still ? .identity : .opacity.combined(with: .offset(y: 6)))
                }
            }
            .padding(.top, 12)
            .animation(Motion.settle(reduce || Probe.still, 0), value: add.phases.count)
            HStack(spacing: 16) {
                // it keeps working if the owner leaves: the job waits in the corner of the window
                Button("carry on in the background") { model.addHidden = true }.buttonStyle(QuietButton(size: 13))
                KeyHint(key: "esc")
                Button("stop") { model.closeAdd() }.buttonStyle(QuietButton(size: 13))
            }
            .padding(.top, 16)
        }
    }

    private func result(_ r: ConnectResult) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            head
            Text(r.sentence)
                .font(.system(size: 19, weight: .regular, design: .serif)).lineSpacing(4).foregroundStyle(Ink.ink)
                .fixedSize(horizontal: false, vertical: true)
                .probe("add.sentence", .text, group: "add.column")
                .padding(.top, 14)
            if !r.choices.isEmpty {
                // the engine asked which part: each answer runs the trial again with it
                Flow(spacing: 8, lineSpacing: 8) {
                    ForEach(r.choices) { c in
                        Button(c.label) { add.choose(c) }.buttonStyle(SwitchButton()).ring(14, inset: 1)
                            .probe("add.choice", .button, group: "add.choices")
                    }
                }
                .padding(.top, 16)
            }
            HStack(spacing: 18) {
                switch r.state {
                case "ready":
                    Button(r.choices.isEmpty ? "add" : "add as it is") { add.add() }.buttonStyle(PrimaryButton())
                    Button("not now") { model.closeAdd() }.buttonStyle(QuietButton())
                case "needs_you" where !r.choices.isEmpty:
                    Button("not now") { model.closeAdd() }.buttonStyle(QuietButton())
                case "needs_you":
                    Button("try again") { add.again() }.buttonStyle(PrimaryButton(hint: nil))
                    Button("not now") { model.closeAdd() }.buttonStyle(QuietButton())
                default:
                    // it could not: say so, and offer the search again rather than a dead end
                    Button("try another") { add.back() }.buttonStyle(PrimaryButton())
                    Button("close") { model.closeAdd() }.buttonStyle(QuietButton())
                }
            }
            .padding(.top, 18)
            .probe("add.buttons", .block, group: "add.column")
        }
    }

    /// Their own notes: a page to write or paste into. It is kept as a source like any other.
    private var note: some View {
        @Bindable var add = add
        return VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 10) {
                Image(systemName: "square.and.pencil").font(.system(size: 13, weight: .medium)).foregroundStyle(Ink.soft).frame(width: 28, height: 28)
                    .background(Ink.wash, in: RoundedRectangle(cornerRadius: Radius.row, style: .continuous)).accessibilityHidden(true)
                Text(add.picked.map(AddModel.noteName) ?? "notes").font(.system(size: 15, weight: .semibold)).foregroundStyle(Ink.ink).lineLimit(1).truncationMode(.middle)
            }
            TextEditor(text: $add.noteText)
                .font(.system(size: 14)).foregroundStyle(Ink.ink).tint(Ink.ember)
                .scrollContentBackground(.hidden)
                .padding(8)
                .frame(height: 170)
                .background(Ink.raised, in: RoundedRectangle(cornerRadius: Radius.card, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: Radius.card, style: .continuous).strokeBorder(Ink.line, lineWidth: 1))
                .overlay(alignment: .topLeading) {
                    if add.noteText.isEmpty {
                        Text(add.noteLoaded ? "write or paste what you know about it. context reads it like anything else you wrote." : "opening the page")
                            .font(.system(size: 14)).foregroundStyle(Ink.soft).padding(.horizontal, 13).padding(.vertical, 8).allowsHitTesting(false)
                    }
                }
                .accessibilityLabel("your notes")
                .padding(.top, 14)
                .probe("add.note", .block, group: "add.column")
            HStack(spacing: 18) {
                Button("save") { add.saveNote() }.buttonStyle(PrimaryButton(hint: nil))
                    .disabled(add.noteText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                Button("back") { add.back() }.buttonStyle(QuietButton())
                Spacer(minLength: 0)
            }
            .padding(.top, 16)
            .probe("add.buttons", .block, group: "add.column")
        }
    }

    private func said(_ text: String, buttons: [(String, Bool, () -> Void)]) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            if add.picked != nil { head }
            Text(text).font(.system(size: 19, weight: .regular, design: .serif)).lineSpacing(4).foregroundStyle(Ink.ink)
                .fixedSize(horizontal: false, vertical: true)
                .probe("add.sentence", .text, group: "add.column")
                .padding(.top, add.picked != nil ? 14 : 0)
            HStack(spacing: 18) {
                ForEach(Array(buttons.enumerated()), id: \.offset) { _, b in
                    Button(b.0, action: b.2).buttonStyle(PrimaryButton())
                }
            }
            .padding(.top, 18)
        }
    }

    private var head: some View {
        HStack(spacing: 10) {
            if let f = add.picked {
                if f.symbol.isEmpty || f.kind == "site" { icon(f, 28) } else {
                    Image(systemName: f.symbol).font(.system(size: 13, weight: .medium)).foregroundStyle(Ink.soft).frame(width: 28, height: 28)
                        .background(Ink.wash, in: RoundedRectangle(cornerRadius: Radius.row, style: .continuous)).accessibilityHidden(true)
                }
            }
            Text(add.picked?.name ?? "").font(.system(size: 15, weight: .semibold)).foregroundStyle(Ink.ink).lineLimit(1)
        }
    }

    private func icon(_ f: Found, _ size: CGFloat) -> some View {
        SourceIcon(id: f.id, size: size, name: f.name, path: f.iconPath)
    }
}

// MARK: tried, saved, never switched on

/// A source the engine tried once and saved, which was never switched on: the add panel was closed, or the app went
/// away, before "add" was pressed. The engine keeps it (`connect-list` returns it with `enabled: false`); the sources
/// page shows it with the one button that finishes the job, so a half-finished add is never lost from view.
struct PendingSource: Identifiable, Equatable {
    let id: String, name: String, kind: String, how: String, created: String
    let rows: Int

    init?(_ d: [String: Any]) {
        guard let id = d["id"] as? String, !id.isEmpty, (d["enabled"] as? Bool) == false else { return nil }
        self.id = id
        name = (d["name"] as? String ?? id).lowercased()
        kind = (d["kind"] as? String ?? "").lowercased()
        how = (d["how"] as? String ?? "").lowercased()
        created = d["created"] as? String ?? ""
        rows = d["rows"] as? Int ?? 0
    }

    /// "tried on 20 nov and saved. it is not being read."
    var line: String {
        let day = Words.day(created)
        let found = rows > 0 ? " \(Words.count(rows)) \(rows == 1 ? "thing was" : "things were") found." : ""
        return "tried\(day.isEmpty ? "" : " on " + day) and saved, but never switched on.\(found) it is not being read."
    }
}

extension AppModel {
    /// Ask the engine what is connected, and keep what is saved but off. Asked when the sources page opens, when the
    /// add panel closes and once at launch, so it is also there after the app was quit in the middle of an add.
    func loadPending() {
        guard !Probe.on else { return }
        func take(_ reply: Any?) -> Bool {
            guard let rows = reply as? [[String: Any]] else { return false }
            pending = rows.compactMap { PendingSource($0) }
            pendingFault = pendingFault.filter { f in pending.contains { $0.id == f.key } }
            return true
        }
        engine.client.call(["cmd": "connect-list"], timeout: 20) { [weak self] reply in
            guard let self else { return }
            if take(reply) { return }
            self.engine.json(["connect", "--list"], timeout: 20) { obj in _ = take(obj) }
        }
    }

    /// The one button: `connect-enable`, then it is read like any other source.
    func switchOn(_ p: PendingSource) {
        guard !pendingBusy.contains(p.id) else { return }
        pendingBusy.insert(p.id)
        pendingFault[p.id] = nil
        engine.client.call(["cmd": "connect-enable", "source": p.id, "on": true], timeout: 60) { [weak self] reply in
            guard let self else { return }
            self.pendingBusy.remove(p.id)
            let d = reply as? [String: Any]
            if let e = d?["error"] as? String, !e.isEmpty { self.pendingFault[p.id] = e.lowercased(); return }
            guard d != nil else { self.pendingFault[p.id] = "the engine did not answer. try again."; return }
            self.pending.removeAll { $0.id == p.id }
            let id = d?["source"] as? String ?? p.id
            if !self.engine.order.contains(id) { self.engine.order.append(id) }
            self.engine.readRun.remove(id)
            self.engine.read(id, first: true)
        }
    }
}

/// One of them on the sources page: its name, what happened, and the button.
struct PendingRow: View {
    @Environment(AppModel.self) private var model
    let source: PendingSource

    var body: some View {
        let busy = model.pendingBusy.contains(source.id)
        HStack(alignment: .center, spacing: Space.m) {
            VStack(alignment: .leading, spacing: 3) {
                HStack(alignment: .firstTextBaseline, spacing: Space.s) {
                    Circle().strokeBorder(Ink.ember, lineWidth: 1.5).frame(width: 7, height: 7).offset(y: -1).accessibilityHidden(true)
                    Text(source.name).font(.system(size: Face.body, weight: .medium)).foregroundStyle(Ink.ink).lineLimit(1)
                    if !source.kind.isEmpty { Text(source.kind).font(.system(size: Face.label)).foregroundStyle(Ink.faint).lineLimit(1) }
                }
                Text(model.pendingFault[source.id] ?? source.line).font(.system(size: Face.label)).foregroundStyle(Ink.soft)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.leading, 15)
                    .probe("sources.pending.line", .text, scrolls: true)
            }
            Spacer(minLength: Space.s)
            Button(busy ? "switching on" : "switch it on") { model.switchOn(source) }
                .buttonStyle(SetButtonStyle()).disabled(busy)
                .accessibilityLabel("switch on \(source.name)")
                .probe("sources.pending.button", .button, scrolls: true)
        }
        .padding(.vertical, Space.m).padding(.horizontal, Space.l)
        .probe("sources.pending", .block, group: "sources.pending", scrolls: true)
    }
}

/// Where the add panel is: choose, a trial read, add. Said in the mono over every stage, the present one in ink
/// beside the one dot, so the order (say what, look first, then add) is never in doubt.
struct AddRail: View {
    let step: Int
    static let words = ["choose", "trial read", "add"]
    static func step(_ s: AddModel.Stage) -> Int {
        switch s {
        case .search, .note, .unavailable: return 0
        case .working: return 1
        case .result, .added: return 2
        }
    }
    var body: some View {
        HStack(spacing: 10) {
            ForEach(Array(AddRail.words.enumerated()), id: \.offset) { i, w in
                HStack(spacing: 5) {
                    if i == step { Circle().fill(Ink.ember).frame(width: 5, height: 5) }
                    Text("\(i + 1) \(w)").font(.system(size: 10.5, weight: i == step ? .medium : .regular, design: .monospaced))
                        .foregroundStyle(i == step ? Ink.ink : (i < step ? Ink.soft : Ink.faint)).lineLimit(1).fixedSize()
                }
                if i < AddRail.words.count - 1 { Rectangle().fill(Ink.line).frame(width: 18, height: 1) }
            }
            Spacer(minLength: 0)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("step \(step + 1) of 3: \(AddRail.words[step])")
        .probe("add.rail", .line)
    }
}
