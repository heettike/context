import AppKit
import Observation
import SwiftUI

/// Something from the past that bears on the paragraph being written.
struct PastNote: Identifiable, Equatable {
    let id: String
    let line: String
    let cite: Hit
}

/// The journal page's state (the tab is still called plan in the code): one plain-text page per day, saved as it is written, and the margin beside it.
@Observable final class Journal {
    let dir: URL
    var day = Calendar.current.startOfDay(for: Date())
    var text = "" { didSet { if text != oldValue, !loading { touched() } } }
    var notes: [PastNote] = []
    var relating = false
    var pending = false                 // a paragraph is long enough and will be looked up once the owner pauses
    var since = Date()                  // when the looking started
    var looking: Bool { relating || pending }
    var insert: String?                 // a quote waiting to be put in at the cursor

    @ObservationIgnored weak var engine: Engine?
    @ObservationIgnored private var loading = false
    @ObservationIgnored private var saveWork: DispatchWorkItem?
    @ObservationIgnored private var pauseWork: DispatchWorkItem?
    @ObservationIgnored private var paragraph = ""
    @ObservationIgnored private var asked = Set<Int>()     // paragraph versions already sent
    static let pause: TimeInterval = 3, minWords = 12

    init(home: URL) {
        dir = home.appendingPathComponent("journal")
        load()
    }

    private var file: URL { dir.appendingPathComponent(Words.isoDay(day) + ".md") }
    var isToday: Bool { Calendar.current.isDateInToday(day) }

    var dayWords: String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US")
        f.dateFormat = "EEEE, d MMMM"
        return (isToday ? "today  ·  " : "") + f.string(from: day).lowercased()
    }

    private func load() {
        loading = true
        text = (try? String(contentsOf: file, encoding: .utf8)) ?? ""
        loading = false
        notes = []
    }

    func save() {
        saveWork?.cancel()
        guard !Engine.debug else { return }
        if text.isEmpty, !FileManager.default.fileExists(atPath: file.path) { return }
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        try? text.write(to: file, atomically: true, encoding: .utf8)
    }

    /// Earlier or later by a day; never past today.
    func shift(_ by: Int) {
        guard let d = Calendar.current.date(byAdding: .day, value: by, to: day), d <= Calendar.current.startOfDay(for: Date()) else { return }
        save()
        day = d
        load()
    }

    private func touched() {
        saveWork?.cancel()
        let w = DispatchWorkItem { [weak self] in self?.save() }
        saveWork = w
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.8, execute: w)
    }

    /// The text view says which paragraph the cursor is in. After a three second pause on a paragraph of twelve
    /// words or more, the engine is asked what from the past bears on it: once per version of the paragraph,
    /// and never while an earlier question is still out.
    func cursor(in paragraph: String) {
        let p = paragraph.trimmingCharacters(in: .whitespacesAndNewlines)
        guard p != self.paragraph else { return }
        self.paragraph = p
        pauseWork?.cancel()
        pending = false
        guard p.split(whereSeparator: \.isWhitespace).count >= Journal.minWords, engine?.repo != nil, !asked.contains(p.hashValue) else { return }
        if !relating { since = Date() }
        pending = true                 // said at once: the three second pause and the reading are one wait to them
        let w = DispatchWorkItem { [weak self] in self?.pending = false; self?.relate(p) }
        pauseWork = w
        DispatchQueue.main.asyncAfter(deadline: .now() + Journal.pause, execute: w)
    }

    private func relate(_ p: String) {
        guard AppModel.shared.saved.relatePast, let engine, !relating, p == paragraph, !asked.contains(p.hashValue) else { return }
        asked.insert(p.hashValue)
        relating = true
        engine.json(["relate", p], timeout: 90) { [weak self] obj in
            guard let self else { return }
            self.relating = false
            guard let rows = obj?["notes"] as? [[String: Any]] else { return }     // no such command yet, or an error: stay quiet
            let found = Journal.notes(from: rows)
            if !found.isEmpty { self.notes = found }
        }
    }

    static func notes(from rows: [[String: Any]]) -> [PastNote] {
        rows.prefix(5).enumerated().compactMap { i, r in
            guard let line = r["line"] as? String, let c = r["cite"] as? [String: Any], let hit = Answer.cite(c, i) else { return nil }
            return PastNote(id: hit.id, line: line.lowercased(), cite: hit)
        }
    }

    func quote(_ n: PastNote) {
        let said = n.cite.text.replacingOccurrences(of: "\n", with: " ").prefix(280)
        let from = [n.cite.thread, Words.day(n.cite.ts)].filter { !$0.isEmpty }.joined(separator: ", ")
        insert = "\n> \(said)\n> (\(from))\n"
        notes.removeAll { $0.id == n.id }
    }

    /// "save to journal": puts a block of text at the end of today's page, with the date it was saved.
    func append(_ block: String) {
        if !isToday { save(); day = Calendar.current.startOfDay(for: Date()); load() }
        let stamp = Words.day(Words.isoDay(Date()))
        text += (text.isEmpty || text.hasSuffix("\n\n") ? "" : (text.hasSuffix("\n") ? "\n" : "\n\n")) + block + "\n(asked \(stamp))\n"
        save()
    }

    func dismiss(_ n: PastNote) { notes.removeAll { $0.id == n.id } }
}

/// A plain text view: no rich text, no chrome, and it reports the paragraph the cursor is in.
struct Writer: NSViewRepresentable {
    @Binding var text: String
    @Binding var insert: String?
    let onParagraph: (String) -> Void

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    func makeNSView(context: Context) -> NSScrollView {
        let scroll = NSTextView.scrollableTextView()
        scroll.drawsBackground = false
        scroll.hasVerticalScroller = true
        scroll.scrollerStyle = .overlay
        guard let tv = scroll.documentView as? NSTextView else { return scroll }
        tv.setAccessibilityLabel("today's journal")
        let style = NSMutableParagraphStyle()
        style.lineSpacing = 6
        style.paragraphSpacing = 10
        tv.isRichText = false
        tv.allowsUndo = true
        tv.drawsBackground = false
        tv.font = .systemFont(ofSize: 17)
        tv.textColor = .dyn(0x17181A, 0xEDECE8)
        tv.insertionPointColor = .dyn(0x17181A, 0xEDECE8)
        tv.defaultParagraphStyle = style
        tv.typingAttributes = [.font: NSFont.systemFont(ofSize: 17), .foregroundColor: NSColor.dyn(0x17181A, 0xEDECE8), .paragraphStyle: style]
        tv.textContainerInset = NSSize(width: 0, height: 2)
        tv.textContainer?.lineFragmentPadding = 0
        tv.isAutomaticQuoteSubstitutionEnabled = false
        tv.isAutomaticDashSubstitutionEnabled = false
        tv.delegate = context.coordinator
        tv.string = text
        return scroll
    }

    func updateNSView(_ scroll: NSScrollView, context: Context) {
        guard let tv = scroll.documentView as? NSTextView else { return }
        context.coordinator.parent = self
        if tv.string != text { tv.string = text }
        if let quote = insert {
            let ns = tv.string as NSString
            let end = NSMaxRange(ns.paragraphRange(for: tv.selectedRange()))     // after the paragraph being written
            tv.insertText(quote, replacementRange: NSRange(location: end, length: 0))
            DispatchQueue.main.async { self.insert = nil }
        }
    }

    final class Coordinator: NSObject, NSTextViewDelegate {
        var parent: Writer
        init(_ parent: Writer) { self.parent = parent }

        func textDidChange(_ note: Notification) {
            guard let tv = note.object as? NSTextView else { return }
            parent.text = tv.string
            report(tv)
        }
        func textViewDidChangeSelection(_ note: Notification) {
            if let tv = note.object as? NSTextView { report(tv) }
        }
        private func report(_ tv: NSTextView) {
            let ns = tv.string as NSString
            guard tv.selectedRange().location <= ns.length else { return }
            parent.onParagraph(ns.substring(with: ns.paragraphRange(for: tv.selectedRange())))
        }
    }
}

/// One calm page for today. What you already wrote, saved or decided shows up in the margin while you write.
struct PlanView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduce

    var body: some View {
        @Bindable var journal = model.journal
        HStack(alignment: .top, spacing: 28) {
            VStack(alignment: .leading, spacing: 0) {
                // the head, as the desk's: the day in the serif, its date in the mono beside it, and the two ways
                // to another day at the far end. three things, three voices, one line that is not crowded
                let day = journal.dayWords.components(separatedBy: "  ·  ")
                HStack(alignment: .firstTextBaseline, spacing: Space.m) {
                    Text(day.first ?? "").font(Face.said(26)).tracking(-0.4).foregroundStyle(Ink.ink)
                        .lineLimit(1).fixedSize().probe("plan.day", .line, group: "plan.head")
                        .accessibilityLabel(journal.dayWords).accessibilityAddTraits(.isHeader)
                    if day.count > 1 {
                        // the whole date where it fits; in a narrow page the day of the week goes, never half a word
                        let date = day.dropFirst().joined(separator: " · ")
                        ViewThatFits(in: .horizontal) {
                            Text(date).lineLimit(1).fixedSize()
                            Text(date.components(separatedBy: ", ").last ?? date).lineLimit(1).fixedSize()
                        }
                        .font(Face.meta).foregroundStyle(Ink.faint)
                        .accessibilityHidden(true)
                    }
                    Spacer(minLength: 8)
                    Button { journal.shift(-1) } label: { Image(systemName: "chevron.left").font(.system(size: 10, weight: .semibold)).frame(width: 24, height: 24).contentShape(Rectangle()) }
                        .buttonStyle(QuietButton(size: 13)).help("the day before").accessibilityLabel("earlier")
                    Button { journal.shift(1) } label: { Image(systemName: "chevron.right").font(.system(size: 10, weight: .semibold)).frame(width: 24, height: 24).contentShape(Rectangle()) }
                        .buttonStyle(QuietButton(size: 13)).disabled(journal.isToday).help("the day after").accessibilityLabel("later")
                        .opacity(journal.isToday ? 0.35 : 1)
                }
                .frame(height: 34)
                    // two ways to hold the same page: write it, or go over it paragraph by paragraph
                    // review is the engine's page of the day; with an engine that has none, there is only writing
                    if model.journalLines.known {
                        HStack(spacing: 2) {
                            ForEach([("write", false), ("review", true)], id: \.0) { word, on in
                                Button(word) { model.journalLines.review = on }
                                    .buttonStyle(.plain).font(.system(size: 10.5, weight: model.journalLines.review == on ? .semibold : .regular, design: .monospaced))
                                    .foregroundStyle(model.journalLines.review == on ? Ink.ink : Ink.soft)
                                    .padding(.horizontal, 6).frame(height: 20)
                                    .background(model.journalLines.review == on ? Ink.wash : .clear, in: RoundedRectangle(cornerRadius: Radius.chip, style: .continuous))
                                    .contentShape(Rectangle())
                                    .accessibilityLabel(on ? "review: the day as context lays it out" : "write").accessibilityAddTraits(model.journalLines.review == on ? [.isSelected] : [])
                            }
                        }
                        .probe("plan.mode", .button)
                        .padding(.top, 6)
                    }
                ZStack(alignment: .topLeading) {
                    if journal.text.isEmpty, !(model.journalLines.review && model.journalLines.known) {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("what are you doing today, and why.")
                                .font(.system(size: 17)).foregroundStyle(Ink.faint)
                            // what this page does, said once, while it is empty
                            Text("write a paragraph and pause. context looks through what you wrote, saved and decided before, and puts what bears on it in the margin.")
                                .font(.system(size: 13)).lineSpacing(3).foregroundStyle(Ink.faint.opacity(0.85))
                                .fixedSize(horizontal: false, vertical: true)
                                .frame(maxWidth: 420, alignment: .leading)
                                .probe("plan.what", .text, group: "plan.empty")
                        }
                        .padding(.top, 2).allowsHitTesting(false)
                    }
                    if model.journalLines.review, model.journalLines.known {
                        JournalReview()
                    } else {
                        Writer(text: $journal.text, insert: $journal.insert) { journal.cursor(in: $0) }
                    }
                }
                .padding(.top, 16)
                .probe("plan.page", .block, group: "plan.columns")
            }
            .frame(minWidth: 300, maxWidth: 580, maxHeight: .infinity, alignment: .topLeading)

            // the margin is one of the journal's sections: it is there unless the owner said to leave it out
            if model.rules.prefs.journalPast {
            VStack(alignment: .leading, spacing: 0) {
                HStack(spacing: 8) {
                    if journal.looking { Mark(source: Catalog.neutral, mood: .reading, size: 7) }
                    Flap(text: journal.looking ? "looking through your past" : (journal.notes.isEmpty ? "" : "from your past"),
                         font: .system(size: 10.5, weight: .medium, design: .monospaced), color: journal.looking ? Ink.soft : Ink.faint)

                    if journal.looking {
                        Color.clear.frame(width: 1, height: 1).probe("plan.looking", .block)
                        TimelineView(.periodic(from: journal.since, by: 1)) { t in
                            Text("\(max(0, Int(t.date.timeIntervalSince(journal.since)))) s")
                                .font(.system(size: 12, weight: .medium)).monospacedDigit().foregroundStyle(Ink.faint)
                        }
                    }
                }
                .frame(height: 34, alignment: .leading)
                .animation(Motion.quick(reduce), value: journal.looking)
                ScrollView {
                    VStack(alignment: .leading, spacing: 18) {
                        ForEach(journal.notes) { n in PastNoteRow(note: n) }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.top, 16).padding(.bottom, 30)
                    .animation(Motion.spring(reduce), value: journal.notes)
                }
            }
            .padding(.leading, 14)
            // the margin's own line, as beside an answer
            .overlay(alignment: .leading) { Rectangle().fill(Ink.line).frame(width: 1).padding(.top, 40) }
            .frame(width: 264)
            .frame(maxHeight: .infinity, alignment: .topLeading)
            .probe("plan.margin", .block, group: "plan.columns")
            }
        }
        .onAppear { if !Probe.on { model.journalLines.load(model.engine) } }
        .padding(.leading, Grid.edge).padding(.trailing, 36).padding(.top, 30).padding(.bottom, 24)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }
}

struct PastNoteRow: View {
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduce
    let note: PastNote

    var body: some View {
        let info = Catalog.info(note.cite.src)
        VStack(alignment: .leading, spacing: 5) {
            Text(note.line).font(.system(size: 15, weight: .regular, design: .serif)).lineSpacing(3).foregroundStyle(Ink.ink)
                .fixedSize(horizontal: false, vertical: true).probe("plan.note", .text, scrolls: true)
            HStack(spacing: 6) {
                SourceIcon(id: info.id, size: 13)
                Text([note.cite.thread, Words.day(note.cite.ts)].filter { !$0.isEmpty }.joined(separator: "  ·  "))
                    .font(.system(size: 12, weight: .medium)).foregroundStyle(Ink.faint).lineLimit(1)
            }
            HStack(spacing: 14) {
                Button("quote it") { model.journal.quote(note) }.buttonStyle(QuietButton(size: 12))
                Button("not this") { model.journal.dismiss(note) }.buttonStyle(QuietButton(size: 12))
            }
            .padding(.top, 1)
        }
        .transition(reduce ? .opacity : .asymmetric(insertion: .offset(y: 10).combined(with: .opacity), removal: .opacity))
    }
}
