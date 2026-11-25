import AppKit
import SwiftUI

/// Home is the empty state: one line said to them, the input in the middle of the window, a few starters under it,
/// and the whole archive as one quiet line at the foot. The first question sends the input to the bottom.
struct HomeView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduce

    static func greeting(at date: Date = Date()) -> String {
        switch Calendar.current.component(.hour, from: date) {
        case 5..<12: return "good morning."
        case 12..<18: return "good afternoon."
        case 18..<23: return "good evening."
        default: return "still up."
        }
    }

    static func short(_ q: String, max: Int = 52) -> String {
        guard q.count > max else { return q }
        let cut = q.prefix(max)
        return String(cut[..<(cut.lastIndex(of: " ") ?? cut.endIndex)]) + "…"
    }

    var body: some View {
        Group {
            // the desk when the engine has said how the month stands; with an older engine, or before it has
            // answered, the greeting and the input, as before. never an error
            if let now = model.now.data { DeskView(now: now) } else { plain }
        }
        .onAppear { model.now.load(model.engine) }
    }

    private var plain: some View {
        VStack(spacing: 0) {
            Spacer(minLength: 12)
            VStack(alignment: .leading, spacing: 0) {
                Text(HomeView.greeting())
                    .font(Face.said(Face.title)).tracking(-0.5).foregroundStyle(Ink.ink)
                    .lineLimit(1).fixedSize()
                    .frame(maxWidth: .infinity, alignment: .center)
                    .probe("home.greeting", .line, group: "home.column")
                    .reveal(0)
                Composer(home: true).padding(.top, Space.xl)
                Flow(spacing: Space.s, lineSpacing: Space.s, centred: true) {
                    // two questions made from their own profile, when the engine has them; then the ready-made ones
                    // each once: the lenses, two questions made from their own profile when the engine has them, then plan
                    ForEach(Array(model.homeChips.enumerated()), id: \.offset) { i, chip in
                        switch chip {
                        case .lens(let l):
                            Button(l.title) { model.ask.run(l, model.engine) }
                                .buttonStyle(Starter()).help(l.about.isEmpty ? l.title : l.about)
                                .probe("home.starter", .block, group: "home.starters")
                                .reveal(i + 1)
                        case .made(let q):
                            // a chip is one short line: a long question is cut at a word, and the pointer shows all of it
                            Button(HomeView.short(q.lowercased())) { _ = model.ask.ask(model.engine, q) }
                                .buttonStyle(Starter()).help(q)
                                .accessibilityLabel("ask: " + q)
                                .probe("home.starter", .block, group: "home.starters")
                                .probe("home.made", .block)
                                .reveal(i + 1)
                        case .plan:
                            Button("journal") { model.go(.plan) }
                                .buttonStyle(Starter(quiet: true)).help("today's page")
                                .probe("home.starter", .block, group: "home.starters")
                                .reveal(i + 1)
                        }
                    }
                }
                .padding(.top, Space.l)
                .frame(maxWidth: .infinity)
                .probe("home.starters", .block, group: "home.column")
                if let card = model.card {
                    MorningCard(card: card).padding(.top, 18)
                        .transition(.opacity.combined(with: .offset(y: 8)))
                }
            }
            .frame(maxWidth: Grid.column - 60)
            .padding(.horizontal, Grid.spinePad)
            Spacer(minLength: 12)
            // the archive, as one line: what it holds and when it was last read. a click opens the sources
            Button { model.go(.sources) } label: {
                HStack(spacing: 9) {
                    if !model.topSources.isEmpty { IconStack(srcs: model.topSources, ground: Ink.paper) }
                    TimelineView(.periodic(from: .now, by: 30)) { _ in
                        Text(model.sourcesLine).monospacedDigit()
                    }
                    let n = model.waitingCount
                    if n > 0 { Text("·  \(n) need\(n == 1 ? "s" : "") you").foregroundStyle(Ink.ink) }
                }
                .frame(height: 24)
            }
            .buttonStyle(QuietButton(size: 12))
            .probe("home.sources", .button)
            .padding(.bottom, 16)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .animation(Motion.tray(reduce), value: model.card)
    }
}

/// Exact-word search, asked for by name (cmd-F): lines that hold these very words, by source, and the row opened beside them.
struct ExactView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduce
    @FocusState private var focused: Bool

    var body: some View {
        @Bindable var ask = model.ask
        HStack(spacing: 0) {
            VStack(alignment: .leading, spacing: 0) {
                TextField("", text: $ask.query, prompt: Text("search exact words").foregroundStyle(Ink.faint), axis: .vertical)
                    .lineLimit(1...3)
                    .textFieldStyle(.plain)
                    .font(.system(size: 28, weight: .bold)).tracking(-0.9)
                    .foregroundStyle(Ink.ink)
                    .focused($focused)
                    .fixedSize(horizontal: false, vertical: true)
                    .background(alignment: .topLeading) {
                        Text(ask.query.isEmpty ? "search exact words" : ask.query)
                            .font(.system(size: 28, weight: .bold)).tracking(-0.9)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .probe("home.question", .text, group: "home.column").hidden()
                    }
                    .tint(Ink.ember)
                    .padding(.leading, Grid.edge).padding(.trailing, Grid.trailing).padding(.top, 14)
                HStack(alignment: .firstTextBaseline, spacing: 14) {
                    Flap(text: statusLine, font: .system(size: 13, weight: .medium))
                        .probe("home.status", .line, group: "home.column")
                    Spacer(minLength: 8)
                    Button("back to asking") { ask.exact = false; ask.query = ""; model.focusAsk += 1 }.buttonStyle(QuietButton(size: 13))
                    KeyHint(key: "esc")
                }
                .padding(.leading, Grid.edge).padding(.trailing, Grid.trailing).padding(.top, 8).padding(.bottom, 12)
                .fixedSize(horizontal: false, vertical: true)
                results
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)

            if let hit = ask.opened {
                Rectangle().fill(Ink.line).frame(width: 1).padding(.vertical, 20)
                ThreadPane(hit: hit, rows: ask.context, words: ask.words)
                    .frame(width: 340)
                    .transition(reduce ? .opacity : .opacity.combined(with: .offset(x: 24)))
            }
        }
        .animation(Motion.quick(reduce), value: ask.opened)
        .onAppear { focused = true }
        .onChange(of: model.focusAsk) { _, _ in focused = true }
    }

    private var statusLine: String {
        let ask = model.ask
        let typed = ask.query.trimmingCharacters(in: .whitespaces)
        if typed.count < 2 { return "whole words only. small words like \u{201C}to\u{201D} and \u{201C}my\u{201D} are left out." }
        if ask.searching && ask.groups.isEmpty { return "looking" }
        let total = ask.groups.reduce(0) { $0 + $1.total }
        let terms = ask.words.joined(separator: ", ")
        if total == 0 { return "no line has \(terms) as whole words." }
        let more = ask.groups.contains { $0.more }
        return "\(Words.count(total))\(more ? "+" : "") with \(terms), in \(ask.groups.count) source\(ask.groups.count == 1 ? "" : "s"). return opens one."
    }

    private var results: some View {
        ScrollViewReader { proxy in
            ScrollView {
                ScrollTop()
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(model.ask.groups) { group in
                        let info = Catalog.info(group.src)
                        HStack(spacing: 8) {
                            SourceIcon(id: group.src, size: 14)
                            Text(info.name).font(.system(size: 13, weight: .semibold)).foregroundStyle(Ink.ink)
                            Text(Words.count(group.total) + (group.more ? "+" : ""))
                                .font(.system(size: 12, weight: .medium)).monospacedDigit().foregroundStyle(Ink.faint)
                        }
                        .padding(.horizontal, 14).padding(.top, 18).padding(.bottom, 6)
                        ForEach(group.hits) { hit in
                            HitRow(hit: hit, words: model.ask.words, tint: info.color, selected: model.ask.selected == hit.id)
                                .id(hit.id)
                                .onTapGesture { model.ask.open(hit) }
                        }
                        if group.total > group.hits.count {
                            Text("\(Words.count(group.total - group.hits.count)) older. add a word to narrow it.")
                                .font(.system(size: 12)).foregroundStyle(Ink.faint)
                                .padding(.horizontal, 14).padding(.top, 4)
                        }
                    }
                    Color.clear.frame(height: 1).id("end")
                }
                .padding(.leading, Grid.edge - 14).padding(.trailing, Grid.trailing - 14).padding(.bottom, 40)
            }
            .onChange(of: model.ask.selected) { _, id in
                if let id { withAnimation(reduce ? nil : .easeOut(duration: 0.12)) { proxy.scrollTo(id) } }
            }
        }
    }
}

// MARK: checks for the smaller things: made starters, a stretch of months, a draft, the sync pill

extension LayoutTest {
    static func lastScreens(_ m: AppModel, main: @escaping (Tab) -> Void, lenses: [LensInfo]) -> [(String, () -> Void)] {
        func chat(_ d: [String: Any], q: String, _ after: () -> Void = {}) {
            main(.home)
            m.ask.turns = [Turn(id: 0, q: q, answer: Answer(d, tag: "t0"))]
            m.ask.asking = false
            after()
        }
        return [
            ("home-starters", {                 // the lenses, then two questions made from their profile, one of them long
                main(.home)
                m.ask.lenses = lenses
                m.ask.starters = ["What did Sam and I leave open about the lease?", "Which of the things I told the allotment committee I would do this autumn have I still not done?", "a third that is not shown"]
            }),
            ("home-starters-engine", {          // the engine's own reply holds the four lenses as well: each still shows once
                main(.home)
                m.ask.lenses = lenses
                let fromLenses: [[String: Any]] = lenses.map { ["q": $0.title, "lens": $0.id] }
                let own: [[String: Any]] = [["q": "What did Sam and I leave open about the lease?", "about": "people"], ["q": "Tasks I owe", "about": "a repeat of a lens"],
                                            ["q": "Where did the pricing page get to?", "about": "projects"]]
                m.ask.take(starters: fromLenses + own)
            }),
            ("chat-months", {                   // a stretch picked by month, shown as one chip
                chat(lease, q: question) { var s = Scope(); s.after = "2024-03-01"; s.before = "2025-07-01"; m.ask.scope = s }
            }),
            ("chat-draft", {                    // a reply written in their voice: it can be copied, and nothing else
                chat(["answer": "Hi Sam,\n\nSorry for the slow reply. We would like to stay another year. Can the deposit carry over to the new term? Ines is fine with the same rent.\n\nR.C.",
                      "draft": true, "cites": [source(1, "whatsapp", "sam (landlord)", "them", "the lease renewal is due on the first.")]], q: "draft a reply to sam about the lease, in my voice")
            }),
            ("frame-collapsed-sync", {          // the list of chats folded away while something is read: the pill in the bar says so
                main(.home)
                m.ask.lenses = lenses
                m.saved.sidebar = false
                m.engine.states["whatsapp"] = .reading
                m.engine.states["email"] = .reading
            }),
        ]
    }
}
