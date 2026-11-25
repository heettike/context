import AppKit
import Observation
import SwiftUI

/// One of the pages the read-through writes about them: plain markdown under CTX_HOME/memory.
struct ProfilePage: Identifiable, Equatable {
    let id: String              // core, people, projects, timeline, voice
    var text: String
    var rebuilt: Date?          // when the engine last wrote the file
    var blocks: [MDBlock]

    init(id: String, text: String, rebuilt: Date?) {
        self.id = id
        self.text = text
        self.rebuilt = rebuilt
        blocks = MD.parse(text, cites: 0)
    }

    static let order = ["core", "people", "projects", "timeline", "voice"]
    static let words = ["core": "you", "people": "people", "projects": "projects", "timeline": "timeline", "voice": "voice"]
    var word: String { ProfilePage.words[id] ?? id.replacingOccurrences(of: "_", with: " ") }
}

/// What context knows about them: the pages, how many conversations they were written from, and what the owner has said
/// is wrong. The pages are the engine's files, read as they are; nothing here writes to them.
@Observable final class ProfileModel {
    let home: URL
    @ObservationIgnored weak var engine: Engine?
    var pages: [ProfilePage] = []
    var cards = 0                       // conversations and projects the pages were written from
    var loaded = false
    var page = "core"
    var wrong: [String: Set<String>] = [:]      // page -> the lines the owner said are wrong
    var rebuilding = false
    var progress: (n: Int, of: Int)?
    var said = ""                       // the last thing the read-through said: what it is reading, or why it stopped
    var cost: (left: Int, calls: Int, units: Int)?
    @ObservationIgnored private var runner: Process?

    init(home: URL) { self.home = home }

    private var memory: URL { home.appendingPathComponent("memory", isDirectory: true) }
    private var marksFile: URL { home.appendingPathComponent("app-corrections.json") }

    var current: ProfilePage? { pages.first { $0.id == page } ?? pages.first }

    /// Reads the pages from disk, off the main thread. A render or a test is given its pages and reads nothing.
    func load() {
        guard !Engine.debug else { loaded = true; return }
        let dir = memory, marks = marksFile
        DispatchQueue.global(qos: .userInitiated).async {
            let fm = FileManager.default
            let names = ((try? fm.contentsOfDirectory(atPath: dir.path)) ?? []).filter { $0.hasSuffix(".md") }.map { String($0.dropLast(3)) }
            let ordered = ProfilePage.order.filter(names.contains) + names.filter { !ProfilePage.order.contains($0) }.sorted()
            let pages: [ProfilePage] = ordered.compactMap { n in
                let u = dir.appendingPathComponent(n + ".md")
                guard let text = try? String(contentsOf: u, encoding: .utf8), !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
                let when = (try? fm.attributesOfItem(atPath: u.path)[.modificationDate]) as? Date
                return ProfilePage(id: n, text: text, rebuilt: when)
            }
            let cards = ((try? fm.contentsOfDirectory(atPath: dir.appendingPathComponent("cards").path)) ?? []).filter { $0.hasSuffix(".json") }.count
            var wrong: [String: Set<String>] = [:]
            if let d = try? Data(contentsOf: marks), let list = (try? JSONSerialization.jsonObject(with: d)) as? [[String: Any]] {
                for m in list { if let p = m["page"] as? String, let l = m["line"] as? String { wrong[p, default: []].insert(l) } }
            }
            DispatchQueue.main.async {
                self.pages = pages
                self.cards = cards
                self.wrong = wrong
                self.loaded = true
                AppModel.shared.people.load(pages: pages)
                if !pages.contains(where: { $0.id == self.page }) { self.page = pages.first?.id ?? "core" }
            }
        }
        if pages.isEmpty || cost == nil { loadCost() }
    }

    /// `understand --status`: how much there is to read through, and about how many calls on their plan that is.
    func loadCost() {
        func take(_ obj: [String: Any]?) -> Bool {
            guard let obj, let left = (obj["left"] ?? obj["unread"] ?? obj["conversations"]) as? Int else { return false }
            cost = (left, (obj["calls"] ?? obj["calls_left_about"] ?? obj["model_calls"]) as? Int ?? 0, obj["units"] as? Int ?? left)
            return true
        }
        // the engine's estimate when it has one; otherwise the read-through's own status
        engine?.client.call(["cmd": "understand-estimate"], timeout: 60) { [weak self] reply in
            if take(reply as? [String: Any]) { return }
            self?.engine?.json(["understand", "--status"], timeout: 60) { _ = take($0) }
        }
    }

    func isWrong(_ line: String, on page: String) -> Bool { wrong[page]?.contains(line) == true }

    /// The owner said a line is wrong. It is kept on this mac and told to the engine, which so far takes it as a rating of
    /// that line; a command that rewrites the page from it is the engine's to add.
    func mark(_ line: String, on page: String, wrong isWrong: Bool) {
        if isWrong { wrong[page, default: []].insert(line) } else { wrong[page]?.remove(line) }
        guard !Engine.debug else { return }
        engine?.client.correct(page: page, line: line, wrong: isWrong) { [weak self] applied in if applied { self?.load() } }
        let list: [[String: Any]] = wrong.flatMap { p, lines in lines.sorted().map { ["page": p, "line": $0] } }
        if let d = try? JSONSerialization.data(withJSONObject: list, options: [.prettyPrinted, .sortedKeys]) { try? d.write(to: marksFile, options: .atomic) }
    }

    /// "rebuild now": `python3 -m ctx understand`, which reads what has no current card and writes the pages again.
    /// Its own progress lines say how far it is.
    func rebuild() {
        guard !rebuilding, let engine, !Engine.debug else { return }
        rebuilding = true
        progress = nil
        said = ""
        runner = engine.stream(["understand"], line: { [weak self] line in
            guard let self, let (src, s) = Engine.progress(line), src == "understand" else { return }
            if !s.phase.isEmpty { self.said = s.phase.lowercased() }
            if let d = (try? JSONSerialization.jsonObject(with: Data(line.dropFirst().utf8))) as? [String: Any], let of = d["of"] as? Int, of > 0 {
                self.progress = (s.rows, of)
            }
        }, done: { [weak self] in
            self?.rebuilding = false
            self?.runner = nil
            self?.progress = nil
            self?.load()
            self?.loadCost()
        })
        if runner == nil { rebuilding = false; said = "the reading half of context is missing." }
    }

    func stop() { runner?.terminate() }

    /// "rebuilt 14 nov from 214 conversations"
    func meta(_ p: ProfilePage) -> String {
        let when = p.rebuilt.map { "rebuilt " + Words.day(Words.isoDay($0)) } ?? "rebuilt"
        return cards > 0 ? "\(when) from \(Words.count(cards)) conversation\(cards == 1 ? "" : "s")" : when
    }

    /// What the read-through costs, in the engine's own figures when it has given them, and what running it switches on.
    var costLine: String {
        let night = ProfileModel.nightLine.isEmpty ? "" : " " + ProfileModel.nightLine
        guard let c = cost, c.left > 0 else { return "it runs on your own ai plan, a short call or two for each conversation. nothing extra is charged, and it can be stopped and picked up again." + night }
        return "\(Words.count(c.left)) conversation\(c.left == 1 ? "" : "s") to read, about \(Words.count(max(c.calls, 1))) call\(c.calls == 1 ? "" : "s") on your own ai plan. nothing extra is charged, and it can be stopped and picked up again." + night
    }

    /// One line for every button that starts the read-through: once it has run, the engine's nightly catch-up runs too
    /// (ctx/catchup.py), on the plan, up to nightly_calls a night (40 unless set). Empty when the catch-up is switched off.
    static var nightLine: String {
        let n = AppModel.shared.exports.catchup?.nightly ?? 40
        return n <= 0 ? "" : "running it also turns on the nightly catch-up: up to \(Words.count(n)) calls a night on your plan, until you switch it off in settings."
    }
}

extension EngineClient {
    /// A line of a profile page the owner said is wrong: {"cmd": "correct", "page": "people", "line": "<the line>", "wrong": true}.
    /// The engine changes the page at once; `wrong: false` takes it back. An engine without the command is sent a
    /// rating of the line instead (kind "profile").
    func correct(page: String, line: String, wrong: Bool, done: @escaping (Bool) -> Void = { _ in }) {
        call(["cmd": "correct", "page": page, "line": line, "wrong": wrong], timeout: 30) { [weak self] reply in
            done(reply != nil)
            if reply == nil { self?.request(["rate", "--question", "profile:" + page, "--id", line, wrong ? "--no" : "--yes", "--kind", "profile"], timeout: 15) { _ in } }
        }
    }
}

// MARK: the page

/// "what context knows about you": the five pages as documents to read, each line with a quiet way to say it is wrong.
struct ProfileView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        Group {
            if model.wiki.exists, !model.wiki.briefing { WikiReader() } else { BriefingView() }
        }
        .onAppear { model.wiki.load(); if !Probe.on { model.wikiBuild.load() } }
    }
}

/// The five short pages every answer starts from. Before the wiki is written they are all of "about you"; after,
/// they are kept under "briefing".
struct BriefingView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduce

    var body: some View {
        let pm = model.profile
        Group {
            if pm.pages.isEmpty {
                ProfileEmpty()
            } else if let page = pm.current {
                ScrollView {
                    ScrollTop()
                    VStack(alignment: .leading, spacing: 0) {
                        if model.wiki.exists {
                            Button { model.wiki.briefing = false } label: {
                                HStack(spacing: 5) {
                                    Image(systemName: "chevron.left").font(.system(size: 9, weight: .bold))
                                    Text("the wiki")
                                }
                            }
                            .buttonStyle(QuietButton(size: 12))
                            .accessibilityLabel("back to the wiki")
                            .probe("wiki.back", .button, scrolls: true)
                            .padding(.bottom, 14)
                        }
                        Text(model.wiki.exists ? "briefing: what the model reads first" : "what context knows about you")
                            .font(.system(size: 26, weight: .regular, design: .serif)).tracking(-0.3).foregroundStyle(Ink.ink)
                            .fixedSize(horizontal: false, vertical: true)
                            .probe("profile.heading", .text, group: "profile.head", scrolls: true)
                            .accessibilityAddTraits(.isHeader)
                        Text("written on your own ai plan from what you wrote, and kept on this mac. every answer starts from these pages. point at a line that is wrong to say so.")
                            .font(.system(size: 13)).foregroundStyle(Ink.soft).lineSpacing(2)
                            .fixedSize(horizontal: false, vertical: true)
                            .probe("profile.about", .text, group: "profile.head", scrolls: true)
                            .padding(.top, 8)
                        // before the wiki is written, this is where it is offered: what it is, what it would take, and its one button
                        if !model.wiki.exists {
                            VStack(alignment: .leading, spacing: 8) {
                                HStack(alignment: .firstTextBaseline, spacing: 8) {
                                    SetText.title("the wiki")
                                    Pill(text: model.wikiBuild.pill.0, tone: model.wikiBuild.pill.1)
                                }
                                SetText.about("longer pages, written from your archive: one for each person who matters, each project, each year. these five short pages are then made from it.")
                                WikiBuildBlock()
                            }
                            .padding(14)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(Ink.raised, in: RoundedRectangle(cornerRadius: Radius.card, style: .continuous))
                            .overlay(RoundedRectangle(cornerRadius: Radius.card, style: .continuous).strokeBorder(Ink.line, lineWidth: 1))
                            .probe("profile.wiki", .block, group: "profile.head", scrolls: true)
                            .padding(.top, 16)
                        }
                        // beside a person's page in a narrow window the row has no room: the words then scroll, and the action goes under
                        ViewThatFits(in: .horizontal) {
                            HStack(alignment: .center, spacing: 12) {
                                PageSwitch(pages: pm.pages, on: page.id) { pm.page = $0 }
                                Spacer(minLength: 8)
                                rebuild(pm)
                            }
                            VStack(alignment: .leading, spacing: 10) {
                                ScrollView(.horizontal, showsIndicators: false) { PageSwitch(pages: pm.pages, on: page.id) { pm.page = $0 } }
                                rebuild(pm)
                            }
                        }
                        .padding(.top, 18)
                        Text(pm.rebuilding ? rebuildingLine(pm) : pm.meta(page))
                            .font(.system(size: 12, weight: .medium)).monospacedDigit().foregroundStyle(Ink.soft).lineLimit(1).truncationMode(.tail)
                            .probe("profile.meta", .block, group: "profile.head", scrolls: true)
                            .padding(.top, 12)
                        ZStack(alignment: .bottom) {
                            Rectangle().fill(Ink.line).frame(height: 1)
                            if pm.rebuilding { Sweep().frame(height: 1.5) }
                        }
                        .padding(.top, 10).padding(.bottom, 22)
                        ProfileDocument(page: page)
                            .id(page.id)
                    }
                    .frame(maxWidth: Grid.column, alignment: .leading)
                    .padding(.horizontal, 28).padding(.top, 22).padding(.bottom, 48)
                    .frame(maxWidth: .infinity)
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .onAppear { pm.load() }
        .animation(reduce ? nil : .easeOut(duration: 0.14), value: pm.page)
    }

    private func rebuildingLine(_ pm: ProfileModel) -> String {
        if let p = pm.progress { return "reading it through again: \(Words.count(p.n)) of \(Words.count(p.of))" + (pm.said.isEmpty ? "" : "  ·  " + pm.said) }
        return pm.said.isEmpty ? "reading it through again" : pm.said
    }

    @ViewBuilder private func rebuild(_ pm: ProfileModel) -> some View {
        if pm.rebuilding {
            Button("stop") { pm.stop() }.buttonStyle(QuietButton(size: 12))
                .help("what has been read so far is kept")
                .probe("profile.rebuild", .button, scrolls: true)
        } else {
            Button("rebuild now") { pm.rebuild() }.buttonStyle(QuietButton(size: 12))
                .help("reads what is new through once more and writes these pages again. " + pm.costLine)
                .probe("profile.rebuild", .button, scrolls: true)
        }
    }
}

/// The pages as one row of words, the one showing on a raised chip: the same control as quick · deep.
struct PageSwitch: View {
    let pages: [ProfilePage]
    let on: String
    let pick: (String) -> Void

    var body: some View {
        HStack(spacing: 2) {
            ForEach(pages) { p in
                Button { pick(p.id) } label: {
                    Text(p.word).font(.system(size: Face.small, weight: p.id == on ? .medium : .regular))
                        .foregroundStyle(p.id == on ? Ink.ink : Ink.soft).lineLimit(1).fixedSize()
                        .padding(.horizontal, 11).frame(height: 26)
                        .background(p.id == on ? Ink.paper : Color.clear, in: Capsule())
                        .contentShape(Capsule())
                }
                .buttonStyle(.plain)
                .ring(13, inset: 0)
                .accessibilityLabel(p.word + " page")
                .accessibilityAddTraits(p.id == on ? [.isSelected] : [])
                .probe("profile.tab", .button, group: "profile.tabs", scrolls: true)
            }
        }
        .padding(2)
        .background(Ink.wash, in: Capsule())
    }
}

/// One page, set as a document. A paragraph, a list line or a quote can be said to be wrong; a heading, a table and
/// code cannot.
struct ProfileDocument: View {
    @Environment(AppModel.self) private var model
    let page: ProfilePage

    var body: some View {
        let blocks = page.blocks
        // an address is a link under the rule answers and the wiki follow (WikiText.gate): only one a row the owner wrote
        // or saved holds, or any with links from others on. these pages cite no rows, so with it off each is its site's name
        let links = WikiLinks(widen: model.linksFromOthers)
        VStack(alignment: .leading, spacing: 0) {
            ForEach(Array(blocks.enumerated()), id: \.element.id) { n, block in
                ProfileLine(page: page.id, block: block, shown: WikiText.gate(block, links), first: n == blocks.firstIndex { $0.kind == .paragraph || $0.kind == .item })
                    .padding(.top, n == 0 ? 0 : MDBlockView.gap(before: block, after: blocks[n - 1]))
            }
        }
    }
}

struct ProfileLine: View {
    @Environment(AppModel.self) private var model
    let page: String
    let block: MDBlock          // the line as the page has it: what "this is wrong" names
    var shown: MDBlock? = nil   // the line as it is drawn, its addresses under the rule
    var first = false
    @State private var hover = false
    @FocusState private var focused: Bool
    static let margin: CGFloat = 104
    private static let turn = Turn(id: -7, q: "")
    private static let answer = Answer(["answer": "profile"], tag: "profile")!

    private var judged: Bool { block.kind == .paragraph || block.kind == .item || block.kind == .quote }

    var body: some View {
        let line = block.plain.trimmingCharacters(in: .whitespaces)
        let wrong = judged && model.profile.isWrong(line, on: page)
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            content.opacity(wrong ? 0.5 : 1)
                .frame(maxWidth: .infinity, alignment: .leading)
            Group {
                if !judged {
                    Color.clear.frame(height: 1)
                } else if wrong {
                    Button("wrong · undo") { model.profile.mark(line, on: page, wrong: false) }
                        .buttonStyle(QuietButton(size: 11))
                        .help("context will stop leaning on this line. undo takes the mark off.")
                        .accessibilityLabel("marked wrong. undo")
                        .probe("profile.wrong", .button, scrolls: true)
                } else {
                    Button("this is wrong") { model.profile.mark(line, on: page, wrong: true) }
                        .buttonStyle(QuietButton(size: 11))
                        .focused($focused)
                        .opacity(hover || focused || (Probe.on && first) ? 1 : 0)
                        .help("say this line is wrong. it is kept on this mac and the next rebuild leaves it out.")
                        .accessibilityLabel("this is wrong: " + String(line.prefix(80)))
                        .probe("profile.wrong", .button, scrolls: true)
                }
            }
            .frame(width: ProfileLine.margin, alignment: .trailing)
        }
        .contentShape(Rectangle())
        .onHover { hover = $0 }
        .probe("profile.line", .block, group: "profile.lines", scrolls: true)
    }

    @ViewBuilder private var content: some View {
        let t = ProfileLine.turn, a = ProfileLine.answer, key = "profile/\(page)/\(block.id)", block = shown ?? self.block
        switch block.kind {
        case .heading:
            InlineFlow(bits: block.bits, size: [20, 20, 17, 15, 15][min(block.level, 4)], weight: .medium, color: Ink.ink, turn: t, answer: a, key: key)
                .probe("profile.text", .text, scrolls: true)
                .accessibilityAddTraits(.isHeader)
        case .paragraph:
            InlineFlow(bits: block.bits, size: 15, color: Ink.ink.opacity(0.9), turn: t, answer: a, key: key)
                .probe("profile.text", .text, scrolls: true)
        case .item:
            HStack(alignment: .firstTextBaseline, spacing: 9) {
                Text(block.marker).font(.system(size: 15, weight: .regular, design: .serif)).monospacedDigit().foregroundStyle(Ink.faint)
                    .frame(minWidth: 12, alignment: .trailing)
                    .accessibilityHidden(true)
                InlineFlow(bits: block.bits, size: 15, color: Ink.ink.opacity(0.9), turn: t, answer: a, key: key)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .probe("profile.text", .text, scrolls: true)
            }
            .padding(.leading, CGFloat(block.level) * 20)
        case .quote:
            InlineFlow(bits: block.bits, size: 15, italic: true, color: Ink.soft, turn: t, answer: a, key: key)
                .probe("profile.text", .text, scrolls: true)
                .padding(.leading, 14)
                .overlay(alignment: .leading) { RoundedRectangle(cornerRadius: 1).fill(Ink.line).frame(width: 2) }
        case .code:
            CodeBlock(code: block.code, lang: block.lang)
        case .table:
            TableBlock(block: block, turn: t, answer: a, key: key)
        case .rule:
            Rectangle().fill(Ink.line).frame(height: 1).padding(.vertical, 4)
        }
    }
}

/// Before the read-through has run: what it is, what it costs, and the one button.
struct ProfileEmpty: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let pm = model.profile
        let ready = model.plan?.ready ?? true
        VStack(spacing: 0) {
            Spacer(minLength: 12)
            VStack(alignment: .leading, spacing: 0) {
                Text("context has not read your history through yet.")
                    .font(.system(size: 26, weight: .regular, design: .serif)).tracking(-0.3).foregroundStyle(Ink.ink)
                    .fixedSize(horizontal: false, vertical: true)
                    .probe("profile.heading", .text, group: "profile.head")
                    .accessibilityAddTraits(.isHeader)
                Text("the read-through goes through each conversation once and writes five pages about you: who you are, your people, your projects, your timeline and how you write. every answer then starts from them, and you can read and correct each line here.")
                    .font(.system(size: 13)).foregroundStyle(Ink.soft).lineSpacing(2)
                    .fixedSize(horizontal: false, vertical: true)
                    .probe("profile.about", .text, group: "profile.head")
                    .padding(.top, 10)
                Text(ready ? pm.costLine : (model.plan?.line ?? "sign in to an ai plan first: the read-through runs on your own."))
                    .font(.system(size: 13)).foregroundStyle(Ink.soft).lineSpacing(2)
                    .fixedSize(horizontal: false, vertical: true)
                    .probe("profile.cost", .text, group: "profile.head")
                    .padding(.top, 8)
                HStack(spacing: 16) {
                    if pm.rebuilding {
                        Button("stop") { pm.stop() }.buttonStyle(PrimaryButton(hint: nil))
                        Text(pm.progress.map { "read \(Words.count($0.n)) of \(Words.count($0.of))" + (pm.said.isEmpty ? "" : "  ·  " + pm.said) } ?? (pm.said.isEmpty ? "starting" : pm.said))
                            .font(.system(size: 12, weight: .medium)).monospacedDigit().foregroundStyle(Ink.soft).lineLimit(1).truncationMode(.tail)
                    } else if ready {
                        Button("read it through") { pm.rebuild() }.buttonStyle(PrimaryButton(hint: nil)).ring(22)
                        if !pm.said.isEmpty {
                            Text(pm.said).font(.system(size: 12, weight: .medium)).foregroundStyle(Ink.soft).lineLimit(2)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    } else {
                        Button("open settings") { model.go(.settings) }.buttonStyle(PrimaryButton(hint: nil))
                    }
                    Spacer(minLength: 0)
                }
                .padding(.top, 22)
                .probe("profile.start", .block, group: "profile.head")
            }
            .frame(maxWidth: Grid.column - 60, alignment: .leading)
            .padding(.horizontal, 28)
            Spacer(minLength: 12)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

// MARK: checks

extension LayoutTest {
    /// Made-up pages in the engine's shape: headings, paragraphs, lists two deep, a quote and a table.
    static let profilePages: [String: String] = [
        "core": """
        # who you are

        You run a two-person studio that builds small tools for allotment societies, and you have lived in the flat on Marsh Lane since 2019. You write most mornings before nine and answer messages in batches after lunch.

        ## what matters to you

        - Keeping the studio small: you have turned down two offers to grow it.
        - The lower field, where you have had a plot since 2021.
          - You are on the committee, and you chair it every other year.
        - Being asked directly. You go quiet when a request is hinted at, \(longName) included.

        ## how you decide

        You decide slowly and then do not go back. *Money* decisions wait for the weekend; **people** decisions wait for a walk.

        > i would rather be late than wrong about this one
        """,
        "people": """
        # people

        ## Sam Okafor

        Your landlord since 2019. Plain and fair with you; he asks twice before he chases. The lease renewal is open between you.

        ## Ines Marchetti

        You share the flat. She would rather not move in January, and she pays the heating.

        ## Maya Lindqvist

        Design partner at the studio since 2022. You owe her the pricing page.

        | who | where you talk | last |
        | --- | --- | --- |
        | Sam Okafor | whatsapp, mail | 11 nov |
        | Ines Marchetti | imessage | 9 nov |
        """,
        "projects": "# projects\n\n## the plot planner\n\nA booking tool for shared tools and water slots. Shipped in march; forty societies use it.\n\n1. Pricing page: yearly on by default.\n2. The checkout bug: verify the signature on the raw body.\n",
        "timeline": "# timeline\n\n- 2019: moved to Marsh Lane.\n- 2021: took the plot on the lower field.\n- 2022: started the studio with Maya.\n- 2026: the plot planner shipped.\n",
        "voice": "# how you write\n\nFull sentences, with capitals and a greeting, and you sign off with your initials. To family you write in Portuguese, longer and warmer; to clients in English, three lines and a date.\n\n```\nI will check with the others and come back to you on Friday.\nR.C.\n```\n",
    ]

    static func profileScreens(_ m: AppModel, main: @escaping (Tab) -> Void) -> [(String, () -> Void)] {
        // a fixed day, so no check depends on the hour it runs at
        let day = Calendar.current.date(from: DateComponents(year: 2026, month: 11, day: 14, hour: 12)) ?? Date(timeIntervalSince1970: 1_794_000_000)
        func pages() {
            m.profile.pages = ProfilePage.order.compactMap { id in profilePages[id].map { ProfilePage(id: id, text: $0, rebuilt: day) } }
            m.profile.cards = 1_000
        }
        return [
            ("profile-core", { main(.profile); pages() }),
            ("profile-people", {
                main(.profile)
                pages()
                m.profile.page = "people"
                m.profile.wrong = ["people": ["You share the flat. She would rather not move in January, and she pays the heating."]]
            }),
            ("profile-rebuilding", {
                main(.profile)
                pages()
                m.profile.page = "voice"
                m.profile.rebuilding = true
                m.profile.progress = (450, 1_600)
                m.profile.said = longName
            }),
            ("profile-empty", { main(.profile); m.profile.cost = (1_600, 250, 1_600) }),
            ("profile-empty-no-plan", {
                main(.profile)
                m.plan = ModelPlan(["using": "none", "fix": "sign in once: open claude code and type /login"])
            }),
            ("profile-empty-reading", {
                main(.profile)
                m.profile.rebuilding = true
                m.profile.progress = (12, 1_600)
                m.profile.said = "sam (landlord)"
            }),
        ]
    }
}
