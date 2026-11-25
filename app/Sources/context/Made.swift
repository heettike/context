import AppKit
import SwiftUI

// Three things that sit beside teach (DESIGN.md):
//   how things are shown ({"cmd":"prefs"}), about you edited in place ({"cmd":"wiki-edit"}), and things context
//   makes for them from the archive ({"cmd":"made-list"}, "made-get", "made-save"; "made" on an answer's done event).
// Each is hidden when the engine does not know its command.

// MARK: how things are shown

/// What the owner has said about how answers, a new chat and the journal look. Read at launch and after any rule change.
struct Prefs: Equatable {
    var citations = "on"            // on: numbers, notes, ribbon. quiet: the ribbon alone. off: clean prose
    var ribbon = true
    var startersOff = false
    var starters: [String]?         // their own, in place of the engine's
    var mode = ""                   // quick, deep, or "" for no default
    var journal: [String]?          // the sections of the journal the owner kept; nil is all of them

    init() {}
    init?(_ any: Any?) {
        guard let d = any as? [String: Any] else { return nil }
        let a = d["answers"] as? [String: Any] ?? [:]
        if let c = a["citations"] as? String, ["on", "quiet", "off"].contains(c) { citations = c }
        if let r = a["ribbon"] as? String { ribbon = r != "off" }
        let n = d["new_chat"] as? [String: Any] ?? [:]
        // the engine's settings: starters is on, off, or a list (rules.py SETTINGS); the list may stand in its place or beside it
        if let s = n["starters"] as? String { startersOff = s == "off" } else if let list = n["starters"] as? [String] { starters = list.map { $0.lowercased() } }
        if starters == nil, let list = (n["starters_list"] ?? n["list"]) as? [String], !list.isEmpty { starters = list.map { $0.lowercased() } }
        mode = n["mode"] as? String ?? ""
        journal = (d["journal"] as? [String: Any])?["sections"] as? [String]
    }

    /// the margin of the journal, "from your past", is one of its sections
    var journalPast: Bool { true }       // the engine's sections are today, waiting, promised, mind, open, notes; it applies their switch itself (ctx/journal.py)
}

private struct EvidenceKey: EnvironmentKey { static let defaultValue = "on" }
extension EnvironmentValues {
    /// how the evidence of the answer being drawn is shown: on, quiet or off
    var evidence: String {
        get { self[EvidenceKey.self] }
        set { self[EvidenceKey.self] = newValue }
    }
}

extension AppModel {
    /// The words under the input of a new chat: their own when the owner gave some, none when the owner switched them off.
    var homeChips: [AskModel.HomeChip] {
        if rules.prefs.startersOff { return [] }
        if let own = rules.prefs.starters { return own.prefix(5).map { .made($0) } }
        return ask.homeChips
    }
}

// MARK: about you, edited in place

/// One paragraph of a page as the engine names it: where their note, their pin and their removal are kept.
struct WikiPara: Equatable {
    var anchor: String
    var text: String
    var note = ""
    var pinned = false

    init?(_ d: [String: Any]) {
        guard let a = d["anchor"] as? String, !a.isEmpty else { return nil }
        anchor = a
        text = d["text"] as? String ?? ""
        note = (d["note"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        pinned = d["pinned"] as? Bool ?? false
    }
}

extension WikiText {
    /// A page set from the engine's own text, each block carrying the anchor of the paragraph it came from. The
    /// engine cuts a page into paragraphs at blank lines (wiki.py `_blocks`) and names each one that can be edited;
    /// the page is cut the same way here, and a piece takes the anchor of the paragraph whose text it is, letter for
    /// letter. Nothing is matched by likeness: a piece the engine did not name has no anchor and cannot be edited.
    static func parse(_ text: String, paras: [WikiPara], names: PeopleModel, pages: [String: String], links: WikiLinks = WikiLinks()) -> [WikiBlock] {
        guard !paras.isEmpty, !text.contains("```"), let cut = try? NSRegularExpression(pattern: "\\n[ \\t]*\\n") else { return parse(text, names: names, pages: pages, links: links) }
        var byText: [String: String] = [:]
        for p in paras { byText[p.text.trimmingCharacters(in: .whitespacesAndNewlines)] = p.anchor }
        var out: [WikiBlock] = [], last = text.startIndex
        var pieces: [String] = []
        for m in cut.matches(in: text, range: NSRange(text.startIndex..., in: text)) {
            guard let r = Range(m.range, in: text) else { continue }
            pieces.append(String(text[last..<r.lowerBound]))
            last = r.upperBound
        }
        pieces.append(String(text[last...]))
        for piece in pieces where !piece.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            let anchor = byText[piece.trimmingCharacters(in: .whitespacesAndNewlines)] ?? ""
            for (i, b) in parse(piece, names: names, pages: pages, links: links).enumerated() {
                var b = WikiBlock(id: out.count, md: b.md, text: b.text, plain: b.plain, refs: b.refs, read: b.read)
                if i == 0 { b.anchor = anchor }
                out.append(b)
            }
        }
        return out
    }
}

extension WikiModel {
    /// The engine's paragraph with this anchor on this page.
    func para(_ page: String, anchor: String) -> WikiPara? { anchor.isEmpty ? nil : paras[page]?.first { $0.anchor == anchor } }

    /// The page as the engine gives it, with their edits applied and its paragraphs named: {"text", "paras"}. From
    /// `wiki --page <id> --json` when a page opens, and from every `wiki-edit`, which answers with the same two.
    func take(_ page: String, _ any: Any?) {
        guard let d = any as? [String: Any], let rows = d["paras"] as? [[String: Any]] else { return }
        let named = rows.compactMap { WikiPara($0) }
        paras[page] = named
        guard let text = d["text"] as? String, let now = self.page, now.entry.id == page, !holding.contains(page) else { return }
        self.page = WikiPage(entry: now.entry, raw: text, blocks: WikiText.parse(text, paras: named, names: names, pages: personPages, links: links(page)))
        vouch(page, text)
    }

    /// An engine without "paras" leaves the page as the file has it, with "this is wrong" and nothing more.
    func loadParas(_ page: String) {
        guard !Probe.on, let engine else { return }
        engine.json(["wiki", "--page", page, "--json"], timeout: 20) { [weak self] obj in self?.take(page, obj) }
    }

    private func edit(_ page: String, _ anchor: String, _ action: String, text: String = "") {
        guard !Probe.on, let engine else { return }
        var req: [String: Any] = ["cmd": "wiki-edit", "page": page, "para": anchor, "action": action]
        if !text.isEmpty { req["text"] = text }
        engine.client.call(req, timeout: 30) { [weak self] reply in self?.take(page, reply) }
    }

    func pin(_ page: String, _ p: WikiPara) {
        if let i = paras[page]?.firstIndex(where: { $0.anchor == p.anchor }) { paras[page]?[i].pinned.toggle() }
        edit(page, p.anchor, p.pinned ? "unpin" : "pin")
    }

    func comment(_ page: String, _ p: WikiPara, _ text: String) {
        let t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        if let i = paras[page]?.firstIndex(where: { $0.anchor == p.anchor }) { paras[page]?[i].note = t }
        noting = nil
        noteDraft = ""
        if !t.isEmpty { edit(page, p.anchor, "comment", text: t) }
    }

    func correct(_ page: String, _ p: WikiPara) { edit(page, p.anchor, "correct") }

    /// Removed. The engine is told at once; for six seconds the page is held as it was, with one line in the
    /// paragraph's place and the way back, which is the engine's own "restore".
    func remove(_ page: String, _ p: WikiPara) {
        let key = page + "#" + p.anchor
        removed.insert(key)
        holding.insert(page)
        edit(page, p.anchor, "remove")
        guard !Probe.on else { return }
        DispatchQueue.main.asyncAfter(deadline: .now() + 6) { [weak self] in
            guard let self, self.removed.contains(key) else { return }
            self.removed.remove(key)
            self.gone.insert(key)
            if !self.removed.contains(where: { $0.hasPrefix(page + "#") }) { self.holding.remove(page); self.loadParas(page) }
        }
    }

    func undoRemove(_ page: String, _ p: WikiPara) {
        removed.remove(page + "#" + p.anchor)
        if !removed.contains(where: { $0.hasPrefix(page + "#") }) { holding.remove(page) }
        edit(page, p.anchor, "restore")
    }
}

/// Round a paragraph of about you that the engine can edit: under the pointer, four quiet words in the margin
/// (remove, this is wrong, add a note, pin); their own note under it, visibly their; a small mark when it is pinned;
/// and, removed, one line in its place with the way to take that back.
struct ParaEdit: ViewModifier {
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduce
    let page: String
    let anchor: String
    let plain: String
    @State private var hover = false
    @FocusState private var writing: Bool

    func body(content: Content) -> some View {
        let wiki = model.wiki
        if let p = wiki.para(page, anchor: anchor) {
            let key = page + "#" + p.anchor
            let still = reduce || Probe.still
            Group {
                if wiki.gone.contains(key) {
                    EmptyView()
                } else if wiki.removed.contains(key) {
                    HStack(spacing: Space.s) {
                        Text("removed from this page.").font(Face.meta).foregroundStyle(Ink.soft)
                        Button("undo") { withAnimation(Motion.unfold(still)) { wiki.undoRemove(page, p) } }.buttonStyle(QuietButton(size: Face.small))
                            .accessibilityLabel("undo: put the paragraph back")
                        Spacer(minLength: 0)
                    }
                    .padding(.vertical, 4)
                    .transition(.opacity)
                    .probe("wiki.removed", .block, scrolls: true)
                } else {
                    VStack(alignment: .leading, spacing: 6) {
                        content
                        // their own words about this paragraph: sans on a wash, as their message is in a chat, never the page's serif
                        if !p.note.isEmpty, wiki.noting != key {
                            HStack(alignment: .firstTextBaseline, spacing: Space.s) {
                                Text("your note").font(Face.meta).foregroundStyle(Ink.faint).fixedSize()
                                Text(p.note).font(.system(size: Face.label)).foregroundStyle(Ink.ink).lineSpacing(2).fixedSize(horizontal: false, vertical: true)
                            }
                            .padding(.horizontal, 10).padding(.vertical, 7)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(Ink.wash, in: RoundedRectangle(cornerRadius: Radius.row, style: .continuous))
                            .probe("wiki.note", .block, scrolls: true)
                        }
                        if wiki.noting == key {
                            @Bindable var w = wiki
                            TextField("", text: $w.noteDraft, prompt: Text("your note on this paragraph, then return").foregroundStyle(Ink.faint), axis: .vertical)
                                .textFieldStyle(.plain).font(.system(size: Face.label)).foregroundStyle(Ink.ink).tint(Ink.ember).lineLimit(1...4)
                                .focused($writing)
                                .onSubmit { wiki.comment(page, p, wiki.noteDraft) }
                                .onAppear { writing = true; model.sideTyping = true }
                                .onDisappear { model.sideTyping = false }
                                .padding(.horizontal, 10).padding(.vertical, 7)
                                .background(Ink.wash, in: RoundedRectangle(cornerRadius: Radius.row, style: .continuous))
                                .accessibilityLabel("your note on this paragraph")
                                .probe("wiki.noting", .block, scrolls: true)
                        }
                        HStack(spacing: Space.m) {
                            Spacer(minLength: 0)
                            Button("remove") { withAnimation(Motion.unfold(still)) { wiki.remove(page, p) } }.accessibilityLabel("remove this paragraph: " + String(plain.prefix(60)))
                            Button("this is wrong") { model.profile.mark(plain, on: page, wrong: true); wiki.correct(page, p) }.accessibilityLabel("this is wrong: " + String(plain.prefix(60)))
                            Button(p.note.isEmpty ? "add a note" : "change the note") { wiki.noteDraft = p.note; wiki.noting = key }.accessibilityLabel("add a note to: " + String(plain.prefix(60)))
                            Button(p.pinned ? "unpin" : "pin") { wiki.pin(page, p) }.accessibilityLabel((p.pinned ? "unpin: " : "pin: ") + String(plain.prefix(60)))
                        }
                        .buttonStyle(QuietButton(size: Face.micro))
                        .frame(height: 16)
                        .opacity(hover || (Probe.on && p.pinned) ? 1 : 0)
                        .probe("wiki.edit", .button, scrolls: true)
                    }
                    // pinned: a small mark in the margin, which stays when the page is written again
                    .overlay(alignment: .topLeading) {
                        if p.pinned {
                            Image(systemName: "pin.fill").font(.system(size: 8, weight: .medium)).foregroundStyle(Ink.ember).offset(x: -16, y: 6)
                                .accessibilityLabel("pinned").probe("wiki.pin", .block, scrolls: true)
                        }
                    }
                    .contentShape(Rectangle())
                    .onHover { hover = $0 }
                    .animation(Motion.hover, value: hover)
                }
            }
        } else {
            content
        }
    }
}

// MARK: made things

/// What an answer made: a post, a draft, a plan, a brief, a table. It is shown as a document, not as a reply.
struct Made: Equatable {
    var id: String
    var title: String
    var kind: String
    var version: Int

    init?(_ any: Any?) {
        guard let d = any as? [String: Any], let id = d["id"] as? String, !id.isEmpty else { return nil }
        self.id = id
        title = (d["title"] as? String ?? "").lowercased()
        kind = (d["kind"] as? String ?? "").lowercased()
        version = d["version"] as? Int ?? 1
    }
}

struct MadeDoc: Identifiable, Equatable {
    var id: String
    var title = ""
    var kind = ""
    var made = ""
    var version = 1
    var versions: [Version] = []
    var chat = ""                   // the chat that made it, as the engine names it
    struct Version: Equatable { var n: Int; var text: String; var made: String }

    init?(_ any: Any?) {
        guard let d = any as? [String: Any], let id = d["id"] as? String else { return nil }
        self.id = id
        title = (d["title"] as? String ?? "").lowercased()
        kind = (d["kind"] as? String ?? "").lowercased()
        made = d["made"] as? String ?? ""
        version = d["version"] as? Int ?? 1
        chat = d["chat"] as? String ?? ""
        // made-get: the newest text stands on the document itself, the ones before it under "history"
        versions = ((d["history"] as? [[String: Any]]) ?? []).compactMap { v in
            (v["text"] as? String).map { Version(n: v["version"] as? Int ?? 1, text: $0, made: v["made"] as? String ?? "") }
        }
        if let t = d["text"] as? String { versions.removeAll { $0.n == version }; versions.append(Version(n: version, text: t, made: made)) }
        versions.sort { $0.n < $1.n }
    }
}

@Observable final class MadeModel {
    var available: Bool?
    var docs: [MadeDoc] = []
    var open: String?                   // a document read on the made page, when the chat that made it is not on this mac
    var editing: String?                // the document being changed in place
    var draft = ""
    var showing: [String: Int] = [:]    // document -> the version on screen, when it is not the newest
    @ObservationIgnored weak var engine: Engine?

    var shown: Bool { available == true }

    func load(_ engine: Engine) {
        self.engine = engine
        guard !Probe.on else { return }
        engine.client.call(["cmd": "made-list"], timeout: 20) { [weak self] reply in
            guard let self else { return }
            guard let rows = reply as? [[String: Any]] else { if self.available == nil { self.available = false }; return }
            self.available = true
            let fresh = rows.compactMap { MadeDoc($0) }.sorted { $0.made > $1.made }
            self.docs = fresh.map { d in var d = d; if d.versions.isEmpty, let old = self.docs.first(where: { $0.id == d.id }) { d.versions = old.versions }; return d }
        }
    }

    func get(_ id: String) {
        guard !Probe.on, let engine else { return }
        engine.client.call(["cmd": "made-get", "doc": id], timeout: 20) { [weak self] reply in
            guard let self, let d = MadeDoc(reply) else { return }
            if let i = self.docs.firstIndex(where: { $0.id == id }) { self.docs[i] = d } else { self.docs.insert(d, at: 0) }
        }
    }

    /// Their own edit, kept as a new version.
    func save(_ id: String) {
        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        editing = nil
        guard !text.isEmpty else { return }
        if let i = docs.firstIndex(where: { $0.id == id }) {
            docs[i].version += 1
            docs[i].versions.append(MadeDoc.Version(n: docs[i].version, text: text, made: Words.isoDay(Date())))
            showing[id] = nil
        }
        guard !Probe.on, let engine else { return }
        engine.client.call(["cmd": "made-save", "doc": id, "text": text], timeout: 30) { [weak self] reply in
            // made-save answers with the document itself, or {"error"}
            guard let self else { return }
            if let d = MadeDoc(reply), !d.versions.isEmpty, let i = self.docs.firstIndex(where: { $0.id == id }) { self.docs[i] = d } else { self.get(id) }
        }
    }

    func doc(_ id: String) -> MadeDoc? { docs.first { $0.id == id } }
    /// The text on screen for a document: the version the owner picked, else the newest the app holds, else nil (the answer's own).
    func text(_ id: String) -> String? {
        guard let d = doc(id), !d.versions.isEmpty else { return nil }
        if let n = showing[id], let v = d.versions.first(where: { $0.n == n }) { return v.text }
        return d.versions.max { $0.n < $1.n }?.text
    }
    func reset() { available = nil; docs = []; open = nil; editing = nil; draft = ""; showing = [:] }
}

/// The head of a made thing, over its text: what kind it is, its name, which version.
struct MadeHead: View {
    @Environment(AppModel.self) private var model
    let made: Made
    var body: some View {
        let doc = model.made.doc(made.id)
        let newest = doc?.versions.map(\.n).max() ?? made.version
        let shown = model.made.showing[made.id] ?? newest
        VStack(alignment: .leading, spacing: 0) {
            Text([made.kind.isEmpty ? "made for you" : made.kind, "version \(shown)" + (shown == newest ? "" : " of \(newest)")].joined(separator: " · "))
                .font(Face.meta).foregroundStyle(Ink.faint).lineLimit(1)
            Text(made.title.isEmpty ? "untitled" : made.title).font(Face.said(26)).tracking(-0.4).lineSpacing(-1).foregroundStyle(Ink.ink)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.top, Space.xs)
                .accessibilityAddTraits(.isHeader)
                .probe("made.title", .text, scrolls: true)
            Rectangle().fill(Ink.line).frame(height: 1).padding(.top, Space.m)
        }
        .probe("made.head", .block, scrolls: true)
    }
}

/// Under a made thing: copy it, change it in place, and its versions as small numbers to press.
struct MadeBar: View {
    @Environment(AppModel.self) private var model
    let made: Made
    let text: String
    @State private var copied = false
    var body: some View {
        let m = model.made
        let doc = m.doc(made.id)
        let versions = (doc?.versions.map(\.n) ?? [made.version]).sorted()
        let newest = versions.last ?? made.version
        HStack(spacing: Space.l) {
            if m.editing == made.id {
                Button("save as version \(newest + 1)") { m.save(made.id) }.buttonStyle(PingButton())
                    .probe("made.save", .button, scrolls: true)
                Button("leave it") { m.editing = nil }.buttonStyle(QuietButton(size: Face.small))
            } else {
                Button(copied ? "copied" : "copy") { Clip.copy(m.text(made.id) ?? text); copied = true }.buttonStyle(QuietButton(size: Face.small))
                Button("edit") { m.draft = m.text(made.id) ?? text; m.editing = made.id }.buttonStyle(QuietButton(size: Face.small))
                    .help("change the words here. your edit is kept as a new version.")
                    .probe("made.edit", .button, scrolls: true)
                if versions.count > 1 {
                    HStack(spacing: 2) {
                        Text("versions").font(Face.meta).foregroundStyle(Ink.faint).padding(.trailing, 4)
                        ForEach(versions, id: \.self) { n in
                            let on = (m.showing[made.id] ?? newest) == n
                            Button { m.showing[made.id] = n == newest ? nil : n } label: {
                                Text("\(n)").font(.system(size: 10, weight: on ? .bold : .regular, design: .monospaced)).foregroundStyle(on ? Ink.ink : Ink.soft)
                                    .frame(width: 20, height: 20).background(on ? Ink.wash : .clear, in: RoundedRectangle(cornerRadius: Radius.chip, style: .continuous))
                                    .contentShape(Rectangle())
                            }
                            .buttonStyle(.plain).accessibilityLabel("version \(n)").accessibilityAddTraits(on ? [.isSelected] : [])
                            .probe("made.version", .block, scrolls: true)
                        }
                    }
                }
            }
            Spacer(minLength: 0)
        }
        .onAppear { if doc == nil || doc?.versions.isEmpty == true { m.get(made.id) } }
    }
}

/// The words of a made thing being changed in place.
struct MadeEditor: View {
    @Environment(AppModel.self) private var model
    var body: some View {
        @Bindable var m = model.made
        TextEditor(text: $m.draft)
            .font(.system(size: Face.read, design: .serif)).lineSpacing(5).foregroundStyle(Ink.ink).tint(Ink.ember)
            .scrollContentBackground(.hidden)
            .frame(minHeight: 180)
            .padding(8)
            .background(Ink.raised, in: RoundedRectangle(cornerRadius: Radius.card, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: Radius.card, style: .continuous).strokeBorder(Ink.ink.opacity(0.22), lineWidth: 1))
            .accessibilityLabel("the words of this document")
            .probe("made.editor", .block, scrolls: true)
    }
}

/// The made place: everything context has made for them, newest first. A row opens its document in the chat that
/// made it; when that chat is not on this mac, the document alone, here.
struct MadeView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduce

    var body: some View {
        let m = model.made
        ScrollView {
            ScrollTop()
            VStack(alignment: .leading, spacing: 0) {
                if let id = m.open, let d = m.doc(id) {
                    Button { m.open = nil } label: { HStack(spacing: 5) { Image(systemName: "chevron.left").font(.system(size: 9, weight: .bold)); Text("made") } }
                        .buttonStyle(QuietButton(size: Face.small)).accessibilityLabel("back to everything made")
                    if let made = Made(["id": d.id, "title": d.title, "kind": d.kind, "version": d.version]) {
                        MadeHead(made: made).padding(.top, Space.m)
                        if m.editing == d.id { MadeEditor().padding(.top, Space.l) }
                        else {
                            Text(m.text(d.id) ?? "").font(Face.said(Face.read)).lineSpacing(5).foregroundStyle(Ink.ink)
                                .fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
                                .padding(.top, Space.l)
                                .probe("made.text", .text, scrolls: true)
                        }
                        MadeBar(made: made, text: m.text(d.id) ?? "").padding(.top, Space.l)
                    }
                } else {
                    HStack(alignment: .firstTextBaseline, spacing: Space.m) {
                        Text("made").font(Face.said(26)).tracking(-0.4).foregroundStyle(Ink.ink).accessibilityAddTraits(.isHeader)
                            .probe("made.heading", .line, scrolls: true)
                        if !m.docs.isEmpty { Text("\(m.docs.count) thing\(m.docs.count == 1 ? "" : "s")").font(Face.meta).foregroundStyle(Ink.faint) }
                    }
                    Text("what context wrote for you out of your own history: a post, a plan, a brief, a table. ask for one in any chat.")
                        .font(.system(size: Face.label)).foregroundStyle(Ink.soft).lineSpacing(3).fixedSize(horizontal: false, vertical: true)
                        .padding(.top, Space.s)
                        .probe("made.what", .text, scrolls: true)
                    VStack(alignment: .leading, spacing: 0) {
                        ForEach(Array(m.docs.enumerated()), id: \.element.id) { i, d in MadeRow(doc: d, index: i) }
                        if !m.docs.isEmpty { Rectangle().fill(Ink.line).frame(height: 1) }
                    }
                    .padding(.top, Space.xl)
                    if m.docs.isEmpty {
                        Text("nothing made yet.").font(Face.meta).foregroundStyle(Ink.soft).padding(.top, Space.xl)
                            .probe("made.none", .line, scrolls: true)
                    }
                }
            }
            .frame(maxWidth: 620, alignment: .leading)
            .frame(maxWidth: .infinity)
            .padding(.horizontal, Grid.spinePad).padding(.top, Space.l).padding(.bottom, 48)
        }
        .onAppear { if !Probe.on { m.load(model.engine) } }
    }
}

struct MadeRow: View {
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduce
    let doc: MadeDoc
    let index: Int
    @State private var hover = false
    @State private var shown = Probe.still

    var body: some View {
        Button { open() } label: {
            VStack(alignment: .leading, spacing: 3) {
                Rectangle().fill(hover ? Ink.soft.opacity(0.6) : Ink.line).frame(height: 1).padding(.bottom, Space.s)
                Text(doc.title.isEmpty ? "untitled" : doc.title).font(Face.said(17)).foregroundStyle(Ink.ink)
                    .multilineTextAlignment(.leading).fixedSize(horizontal: false, vertical: true)
                    .probe("made.row.title", .text, scrolls: true)
                Text([doc.kind, Words.day(doc.made), doc.version > 1 ? "version \(doc.version)" : ""].filter { !$0.isEmpty }.joined(separator: " · "))
                    .font(Face.meta).foregroundStyle(Ink.soft).lineLimit(1)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.bottom, Space.m)
            .contentShape(Rectangle())
        }
        .buttonStyle(Pressable())
        .onHover { hover = $0 }
        .animation(Motion.hover, value: hover)
        .opacity(shown ? 1 : 0).offset(y: shown ? 0 : 8)
        .onAppear { if reduce || Probe.still || shown { shown = true } else { withAnimation(Motion.settle(false, index)) { shown = true } } }
        .accessibilityLabel([doc.title, doc.kind, Words.day(doc.made)].filter { !$0.isEmpty }.joined(separator: ", "))
        .accessibilityHint("opens it")
        .ring(Radius.chip, inset: 2)
        .probe("made.row", .block, group: "made.rows", scrolls: true)
    }

    private func open() {
        // the chat that made it: the one the engine names, else the one on this mac whose answer carries it
        if !doc.chat.isEmpty, model.ask.chats.contains(where: { $0.id == doc.chat }) { model.openChat(doc.chat); return }
        if let chat = model.ask.chats.first(where: { c in c.turns.contains { $0.answer?.made?.id == doc.id } }) { model.openChat(chat.id); return }
        model.made.open = doc.id
        model.made.get(doc.id)
    }
}

// MARK: in the gate

extension LayoutTest {
    /// The journal as ctx/journal.py gives it.
    static let journalFixture: [String: Any] = ["date": "2026-11-22", "removed": 2, "sections": [
        ["id": "today", "title": "worth a glance today", "lines": [
            ["anchor": "a1", "text": "ines is waiting on the deposit figure", "row": "W2", "thread": "the flat", "when": "2026-11-19T21:30:00Z", "note": "tell her by friday."]]],
        ["id": "waiting", "title": "waiting on you", "lines": [
            ["anchor": "a2", "text": "sam okafor: renewal and deposit, asked twice", "row": "W1", "thread": "sam (landlord)", "when": "2026-11-05T09:00:00Z"],
            ["anchor": "a3", "text": "the allotment committee and friends of the lower field (2026): whether you will take the water rota slot in the first week of december", "row": "T9", "thread": "", "when": "2026-11-12T18:00:00Z"]]],
        ["id": "promised", "title": "you said you would", "lines": [[String: Any]]()],
        ["id": "mind", "title": "on your mind", "lines": [["anchor": "a4", "text": "the seed swap: 41 messages, 3 notes", "row": "", "thread": "seed swap", "when": ""]]],
    ]]
    static let madeText = "The allotment society's waiting list is longer than its plots have ever been, and the committee has started to ask what a plot is for.\n\nThree things came up again and again in your notes this autumn: water, who decides, and what happens to a plot nobody tends. This draft takes them in that order."
    static func madeScreens(_ m: AppModel, main: @escaping (Tab) -> Void) -> [(String, () -> Void)] {
        func docs() -> [MadeDoc] {
            [["id": "d1", "title": "What a plot is for", "kind": "blog draft", "made": "2026-11-21", "version": 2,
              // made-get's own shape: the newest text on the document, the ones before it under "history", and the chat that made it
              "text": madeText, "chat": "c-made-up", "history": [["version": 1, "text": "The waiting list is long.", "made": "2026-11-19", "by": "context", "said": ""]]],
             ["id": "d2", "title": "A plan for the water rota, week by week, for the committee meeting in december and the two after it", "kind": "plan", "made": "2026-11-18", "version": 1],
             ["id": "d3", "title": "Who owes whom an introduction", "kind": "table", "made": "2026-11-02", "version": 1]].compactMap { MadeDoc($0) }
        }
        func answer(_ more: [String: Any]) -> Answer? { var d = lease; for (k, v) in more { d[k] = v }; return Answer(d, tag: "t0") }
        func chat(_ a: Answer?) { main(.home); m.saved.sidebar = false; m.ask.turns = [Turn(id: 0, q: question, answer: a)]; m.ask.asking = false }
        return [
            // how the owner asked for things to be shown: clean prose with one way back; the ribbon alone; a new chat with their own defaults
            ("prefs-off", { chat(answer([:])); m.rules.available = true; m.rules.prefs.citations = "off" }),
            ("prefs-quiet", { chat(answer([:])); m.rules.available = true; m.rules.prefs.citations = "quiet" }),
            ("prefs-off-shown", { chat(answer([:])); m.rules.available = true; m.rules.prefs.citations = "off"; m.ask.evidenceShown = [0] }),
            ("newchat-defaults", { main(.home); m.rules.available = true; m.rules.prefs.mode = "deep"; m.rules.prefs.starters = ["what did i promise this week", "who have i not answered"]; m.newChat() }),
            ("newchat-bare", { main(.home); m.rules.available = true; m.rules.prefs.startersOff = true; m.newChat() }),
            // about you, edited in place: their note, a pin, and a paragraph just removed with the way back
            ("wiki-edited", {
                all(m).first { $0.0 == "wiki-person" }?.1()
                guard let page = m.wiki.page else { return }
                // the page as the engine would give it: its first two paragraphs named, one with their note and a pin,
                // the second just removed. the third is below the fold in a small window, and is not built
                var blocks = page.blocks, named: [WikiPara] = []
                for i in blocks.indices where blocks[i].md.kind == .paragraph && named.count < 3 {
                    blocks[i].anchor = "a\(named.count)"
                    if let p = WikiPara(["anchor": blocks[i].anchor, "text": blocks[i].plain, "note": named.isEmpty ? "he is fair, but he was two months late with the boiler. keep that in." : "", "pinned": named.isEmpty]) { named.append(p) }
                }
                m.wiki.page = WikiPage(entry: page.entry, raw: page.raw, blocks: blocks)
                m.wiki.paras[page.entry.id] = named
                if named.count > 1 { m.wiki.removed = [page.entry.id + "#a1"] }
            }),
            // a made thing: a document with two versions; being changed; the list of what was made; all of the sidebar
            ("made-doc", { chat(answer(["made": ["id": "d1", "title": "What a plot is for", "kind": "blog draft", "version": 2], "answer": madeText + " [1]"])); m.made.available = true; m.made.docs = docs() }),
            ("made-editing", { chat(answer(["made": ["id": "d1", "title": "What a plot is for", "kind": "blog draft", "version": 2], "answer": madeText + " [1]"])); m.made.available = true; m.made.docs = docs(); m.made.draft = madeText; m.made.editing = "d1" }),
            ("made-list", { main(.made); m.made.available = true; m.made.docs = docs() }),
            ("made-none", { main(.made); m.made.available = true }),
            ("made-read", { main(.made); m.made.available = true; m.made.docs = docs(); m.made.open = "d1" }),
            // the journal's engine page: sections with lines, one with their note, one just taken out, two taken out before
            ("plan-review", {
                all(m).first { $0.0 == "plan-writing" }?.1()
                let l = m.journalLines
                l.page = JournalPage(journalFixture)
                l.review = true
                l.removed = ["a3"]
            }),
            ("plan-review-empty", { main(.plan); m.journalLines.page = JournalPage(["date": "2026-11-22", "sections": [[String: Any]](), "removed": 0]); m.journalLines.review = true }),
            // an engine with no journal command: writing only, and no word about review
            ("plan-no-review", { all(m).first { $0.0 == "plan-writing" }?.1(); m.journalLines.page = nil }),
            // first run with the extension alone (reads, cannot ask a site for an export), and with page scripting as well
            ("first-extension-only", {
                all(m).first { $0.0 == "first-on" }?.1()
                m.bridge = true
                m.exports.browser = BrowserAbility(["name": "your browser", "can_read": true, "reads_through": "extension", "can_request": false,
                                                    "request_needs": "in your browser: view, developer, allow javascript from apple events."])
            }),
            ("first-both-on", {
                all(m).first { $0.0 == "first-on" }?.1()
                m.bridge = true
                m.exports.browser = BrowserAbility(["name": "your browser", "can_read": true, "reads_through": "page scripting", "can_request": true, "request_needs": ""])
            }),
            ("sidebar-all", { main(.home); m.rules.available = true; m.made.available = true; m.now.data = NowData(nowFull) }),
        ]
    }
    private static func all(_ m: AppModel) -> [(String, () -> Void)] { scenarios(m) }

    static func madeCheck(_ screen: String, _ at: String, _ size: CGSize, _ found: [ProbeInfo]) -> [String] {
        var out: [String] = []
        func has(_ n: String) -> Bool { found.contains { $0.name == n } }
        func count(_ n: String) -> Int { found.filter { $0.name == n }.count }
        let wide = size.width - (found.first { $0.name == "side.ground" }?.frame.maxX ?? 0) >= PageMeasure.least
        switch screen {
        case "prefs-off":
            if has("ribbon.line") || has("note") || has("chat.cite") { out.append("\(at): with citations off the answer still shows a ribbon, notes or numbers") }
            if has("chat.sources") { out.append("\(at): with citations off there are two ways to the evidence under the answer, not one") }
            if !has("chat.show") { out.append("\(at): with citations off there is no way to see where the answer came from") }
        case "prefs-quiet":
            if !has("ribbon.line") || has("note") || has("chat.cite") { out.append("\(at): quiet citations are not the ribbon alone") }
        case "prefs-off-shown":
            if !has("ribbon.line") || !has("chat.cite") || (wide && !has("note")) || has("chat.show") { out.append("\(at): asked for, the evidence of this one answer is not all back") }
        case "newchat-defaults":
            if count("home.starter") != 2 { out.append("\(at): a new chat shows \(count("home.starter")) starters, not their own two") }
            if !AppModel.shared.ask.deep { out.append("\(at): a new chat does not open in the mode the owner chose") }
        case "newchat-bare":
            if count("home.starter") != 0 { out.append("\(at): starters are drawn though the owner switched them off") }
        case "wiki-edited":
            if !has("wiki.note") || !has("wiki.pin") || !has("wiki.removed") || !has("wiki.edit") { out.append("\(at): their note, the pin, the removed line or the four actions are missing (note \(has("wiki.note")), pin \(has("wiki.pin")), removed \(has("wiki.removed")), actions \(has("wiki.edit")))") }
        case "plan-review":
            if !has("plan.review") || !has("plan.note") || !has("plan.removed") || !has("plan.edit") || !has("plan.mode") || !has("plan.removed.count") { out.append("\(at): the journal gone over lacks their note, the taken-out line, the actions, the count of lines taken out or the way back to writing") }
            if count("plan.section") < 2 { out.append("\(at): the journal's sections are not drawn (\(count("plan.section")))") }
        case "plan-review-empty":
            if !has("plan.review.none") { out.append("\(at): an empty journal says nothing") }
        case "plan-no-review":
            if has("plan.mode") || has("plan.review") { out.append("\(at): review is offered though the engine has no journal") }
        case "made-doc":
            if !has("made.title") || !has("made.edit") || count("made.version") != 2 { out.append("\(at): a made thing is not a document with its name, edit and two versions") }
            if wide, !has("note") { out.append("\(at): a made thing does not show what it drew on in the margin") }
        case "made-editing":
            if !has("made.editor") || !has("made.save") { out.append("\(at): a made thing being changed has no editor or no save") }
        case "first-extension-only", "first-both-on":
            if !has("first.ask") { out.append("\(at): first run does not say whether sites can be asked for exports, apart from reading") }
        case "made-list":
            if count("made.row") != 3 { out.append("\(at): the made place lists \(count("made.row")) things, not 3") }
        case "made-none":
            if !has("made.none") { out.append("\(at): an empty made place says nothing") }
        case "made-read":
            if !has("made.title") || !has("made.text") { out.append("\(at): a document opened on the made page is not drawn") }
        case "sidebar-all":
            if found.contains(where: { $0.name == "side.ground" }) {
                let ys = ["side.made", "side.teach"].compactMap { n in found.first { $0.name == n }?.frame.minY }
                if ys.count != 2 { out.append("\(at): the sidebar does not show both teach and made") }
                if count("side.action") < 8 { out.append("\(at): the sidebar has \(count("side.action")) rows, fewer than its eight") }
            }
        default: break
        }
        return out
    }
}
