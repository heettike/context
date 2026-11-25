import AppKit
import SwiftUI

// The journal's engine side (ctx/journal.py), gone over line by line.
//   {"cmd": "journal"}                                                  -> {"result": {"date", "sections": [{"id": today|waiting|promised|mind|open|notes,
//                                                                            "title", "lines": [{"anchor", "text", "row", "thread", "when", "note"?}]}], "removed": n}}
//   {"cmd": "journal-edit", "line": anchor, "action": "remove" | "comment" | "restore", "text"?: "..."}   -> {"result": the journal as it now reads} | {"error"}
// The page is made by code from what the engine already knows; which sections show is their "show" rule, applied by the
// engine. A line can be removed (it stays out), commented on, and put back. There is no edit and no pin: what the owner
// writes themselves is their own page, in "write", and is changed there as it always was.
// An engine without `journal` answers with no result: "review" is then not offered at all.

struct JournalLine: Identifiable, Equatable {
    var anchor: String
    var text: String
    var row = ""
    var thread = ""
    var when = ""
    var note = ""
    var id: String { anchor }

    init?(_ d: [String: Any]) {
        guard let a = d["anchor"] as? String, !a.isEmpty else { return nil }
        anchor = a
        text = (d["text"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        row = d["row"] as? String ?? ""
        thread = (d["thread"] as? String ?? "").lowercased()
        when = d["when"] as? String ?? ""
        note = (d["note"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    }
}

struct JournalSection: Identifiable, Equatable {
    var id: String
    var title: String
    var lines: [JournalLine]

    init?(_ d: [String: Any]) {
        guard let id = d["id"] as? String else { return nil }
        self.id = id
        title = (d["title"] as? String ?? id).lowercased()
        lines = ((d["lines"] as? [[String: Any]]) ?? []).compactMap { JournalLine($0) }
    }
}

struct JournalPage: Equatable {
    var date = ""
    var sections: [JournalSection] = []
    var removed = 0

    init?(_ any: Any?) {
        guard let d = any as? [String: Any], let rows = d["sections"] as? [[String: Any]] else { return nil }
        date = d["date"] as? String ?? ""
        sections = rows.compactMap { JournalSection($0) }
        removed = d["removed"] as? Int ?? 0
    }
}

@Observable final class JournalLines {
    var review = false
    var page: JournalPage?              // nil until the engine has answered `journal`; stays nil with an engine that has no such command
    var noting: String?
    var noteDraft = ""
    var removed: Set<String> = []       // anchors just taken out, while they can still be put back: the page is held as it was
    var fault = ""
    @ObservationIgnored private var held: JournalPage?     // what the engine said while a removal could still be undone
    @ObservationIgnored weak var engine: Engine?

    var known: Bool { page != nil }

    private func take(_ any: Any?) {
        if let e = (any as? [String: Any])?["error"] as? String { fault = e.lowercased(); return }
        guard let p = JournalPage(any) else { return }
        fault = ""
        if removed.isEmpty { page = p } else { held = p }
    }

    /// Asked when the journal opens and after each sync.
    func load(_ engine: Engine) {
        self.engine = engine
        guard !Probe.on else { return }
        engine.client.call(["cmd": "journal"], timeout: 30) { [weak self] reply in self?.take(reply) }
    }

    private func send(_ anchor: String, _ action: String, text: String = "") {
        guard !Probe.on, let engine else { return }
        var req: [String: Any] = ["cmd": "journal-edit", "line": anchor, "action": action]
        if !text.isEmpty { req["text"] = text }
        engine.client.call(req, timeout: 30) { [weak self] reply in self?.take(reply) }
    }

    func comment(_ line: JournalLine, _ text: String) {
        let t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        noting = nil
        noteDraft = ""
        guard !t.isEmpty else { return }
        // shown at once; the engine's answer is the page as it now reads
        if let s = page?.sections.firstIndex(where: { $0.lines.contains { $0.anchor == line.anchor } }), let i = page?.sections[s].lines.firstIndex(where: { $0.anchor == line.anchor }) {
            page?.sections[s].lines[i].note = t
        }
        send(line.anchor, "comment", text: t)
    }

    /// Taken out: the engine is told at once and the line stays out for good. For six seconds the page is held as it
    /// was, with one line in its place and the way back, which is the engine's own "restore".
    func remove(_ line: JournalLine) {
        removed.insert(line.anchor)
        send(line.anchor, "remove")
        guard !Probe.on else { return }
        DispatchQueue.main.asyncAfter(deadline: .now() + 6) { [weak self] in
            guard let self, self.removed.contains(line.anchor) else { return }
            self.removed.remove(line.anchor)
            if self.removed.isEmpty { if let h = self.held { self.page = h; self.held = nil } else if let e = self.engine { self.load(e) } }
        }
    }

    func undo(_ line: JournalLine) {
        removed.remove(line.anchor)
        if removed.isEmpty { held = nil }
        send(line.anchor, "restore")
    }

    func reset() { review = false; page = nil; noting = nil; noteDraft = ""; removed = []; fault = ""; held = nil }
}

/// The day as the engine lays it out: six short sections, each a small heading and its lines. A line opens the
/// conversation it rests on; under the pointer it can be taken out or have a note put on it.
struct JournalReview: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let lines = model.journalLines
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                if let page = lines.page {
                    let shown = page.sections.filter { !$0.lines.isEmpty }
                    if shown.isEmpty {
                        Text("nothing for today yet. it fills as your archive is read.").font(.system(size: Face.label)).foregroundStyle(Ink.soft)
                            .fixedSize(horizontal: false, vertical: true)
                            .probe("plan.review.none", .text, scrolls: true)
                    }
                    ForEach(Array(shown.enumerated()), id: \.element.id) { i, s in
                        Text(s.title).font(.system(size: 10.5, weight: .medium, design: .monospaced)).foregroundStyle(Ink.faint).lineLimit(1)
                            .accessibilityAddTraits(.isHeader)
                            .padding(.top, i == 0 ? 0 : Space.xl).padding(.bottom, Space.s)
                            .probe("plan.section", .line, scrolls: true)
                        ForEach(s.lines) { JournalLineRow(line: $0) }
                    }
                    if page.removed > 0 || !lines.fault.isEmpty {
                        Text(lines.fault.isEmpty ? "\(page.removed) line\(page.removed == 1 ? "" : "s") you took out stay\(page.removed == 1 ? "s" : "") out." : lines.fault)
                            .font(Face.meta).foregroundStyle(Ink.faint).fixedSize(horizontal: false, vertical: true)
                            .padding(.top, Space.xl)
                            .probe("plan.removed.count", .text, scrolls: true)
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.bottom, 30)
        }
        .probe("plan.review", .block)
    }
}

struct JournalLineRow: View {
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduce
    let line: JournalLine
    @State private var hover = false
    @FocusState private var writing: Bool

    var body: some View {
        let lines = model.journalLines
        let still = reduce || Probe.still
        if lines.removed.contains(line.anchor) {
            HStack(spacing: Space.s) {
                Text("taken out. it will not come back.").font(Face.meta).foregroundStyle(Ink.soft)
                Button("undo") { withAnimation(Motion.unfold(still)) { lines.undo(line) } }.buttonStyle(QuietButton(size: Face.small))
                    .accessibilityLabel("undo: put the line back")
                Spacer(minLength: 0)
            }
            .padding(.vertical, 6)
            .overlay(alignment: .top) { Rectangle().fill(Ink.line).frame(height: 1) }
            .probe("plan.removed", .block, scrolls: true)
        } else {
            VStack(alignment: .leading, spacing: 5) {
                Rectangle().fill(hover ? Ink.soft.opacity(0.6) : Ink.line).frame(height: 1)
                // the line itself: pressed, it opens the conversation it rests on. one that rests on none is only said
                Button { open() } label: {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(line.text).font(.system(size: Face.body)).lineSpacing(3).foregroundStyle(Ink.ink)
                            .multilineTextAlignment(.leading).fixedSize(horizontal: false, vertical: true)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .probe("plan.line", .text, group: "plan.lines", scrolls: true)
                        let meta = [line.thread, Words.day(line.when)].filter { !$0.isEmpty }.joined(separator: " · ")
                        if !meta.isEmpty { Text(meta).font(Face.meta).foregroundStyle(Ink.faint).lineLimit(1).truncationMode(.middle) }
                    }
                    .contentShape(Rectangle())
                }
                // a line that rests on no one message is not pressed, and is not dimmed for it: it is as much said as the others
                .buttonStyle(.plain).allowsHitTesting(!line.row.isEmpty)
                .accessibilityLabel(line.text)
                .accessibilityHint(line.row.isEmpty ? "" : "opens the conversation it came from")
                if !line.note.isEmpty, lines.noting != line.anchor {
                    HStack(alignment: .firstTextBaseline, spacing: Space.s) {
                        Text("your note").font(Face.meta).foregroundStyle(Ink.faint).fixedSize()
                        Text(line.note).font(.system(size: Face.label)).foregroundStyle(Ink.ink).lineSpacing(2).fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(.horizontal, 10).padding(.vertical, 7)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Ink.wash, in: RoundedRectangle(cornerRadius: Radius.row, style: .continuous))
                    .probe("plan.note", .block, scrolls: true)
                }
                if lines.noting == line.anchor {
                    @Bindable var l = lines
                    TextField("", text: $l.noteDraft, prompt: Text("your note on this line, then return").foregroundStyle(Ink.faint), axis: .vertical)
                        .textFieldStyle(.plain).font(.system(size: Face.label)).foregroundStyle(Ink.ink).tint(Ink.ember).lineLimit(1...4)
                        .focused($writing)
                        .onSubmit { lines.comment(line, lines.noteDraft) }
                        .onAppear { writing = true; model.sideTyping = true }
                        .onDisappear { model.sideTyping = false }
                        .padding(.horizontal, 10).padding(.vertical, 7)
                        .background(Ink.wash, in: RoundedRectangle(cornerRadius: Radius.row, style: .continuous))
                        .accessibilityLabel("your note on this line")
                        .probe("plan.noting", .block, scrolls: true)
                }
                HStack(spacing: Space.m) {
                    Button("remove") { withAnimation(Motion.unfold(still)) { lines.remove(line) } }.accessibilityLabel("remove: " + String(line.text.prefix(60)))
                        .help("takes it out of the journal for good. you have a few seconds to put it back.")
                    Button(line.note.isEmpty ? "add a note" : "change the note") { lines.noteDraft = line.note; lines.noting = line.anchor }.accessibilityLabel("add a note to: " + String(line.text.prefix(60)))
                    Spacer(minLength: 0)
                }
                .buttonStyle(QuietButton(size: Face.micro))
                .frame(height: 16)
                .opacity(hover || (Probe.on && !line.note.isEmpty) ? 1 : 0)
                .probe("plan.edit", .button, scrolls: true)
            }
            .contentShape(Rectangle())
            .onHover { hover = $0 }
            .animation(Motion.hover, value: hover)
            .teachMenu(thread: line.thread)
        }
    }

    private func open() {
        guard !line.row.isEmpty else { return }
        let hit = Hit(id: "journal:0:" + line.row, src: "", kind: "message", ts: line.when, thread: line.thread, threadID: "", who: "", sender: "", text: line.text, url: "", offset: 0)
        model.ask.peekThread(hit, turn: -9, model.engine)
    }
}
