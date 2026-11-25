import AppKit
import SwiftUI

/// A conversation: one centred column that reads top to bottom. Their message is a soft bubble on the right, the
/// answer plain text on the left, the newest turn at the top of the window. The input stays at the bottom.
struct ChatView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduce

    static let column = Grid.column

    var body: some View {
        let ask = model.ask
        VStack(spacing: 0) {
            GeometryReader { geo in
                // wide enough for a margin, an answer is a page with its evidence beside it; narrower, numbered chips and the panel
                let page = PageMeasure.fit(geo.size.width)
                ScrollViewReader { proxy in
                    ScrollView {
                        ScrollTop()
                        VStack(alignment: .leading, spacing: 0) {
                            ForEach(ask.turns) { turn in
                                let last = turn.id == ask.turns.last?.id
                                VStack(alignment: .leading, spacing: 0) {
                                    ChatTurn(turn: turn)
                                    if last, turn.answer == nil {
                                        // the foot of an answer being written: where it is says whether its last line has gone under the input
                                        Color.clear.frame(height: 1).id("tail")
                                            .background(GeometryReader { g in Color.clear.preference(key: TailKey.self, value: g.frame(in: .named("chat.scroll")).maxY) })
                                    }
                                    if last {
                                        // sent while this one was being read: each waits here and goes by itself when its turn comes
                                        ForEach(Array(ask.queue.enumerated()), id: \.offset) { i, q in Queued(index: i, text: q) }
                                    }
                                }
                                // the newest turn can always rise to the top of the window, however short it is
                                .frame(minHeight: last && ask.turns.count > 1 ? geo.size.height : nil, alignment: .top)
                                .id("turn\(turn.id)")
                                .transition(.opacity)
                            }
                        }
                        .frame(maxWidth: page?.total ?? ChatView.column, alignment: .leading)
                        .frame(maxWidth: .infinity)
                        .padding(.horizontal, Grid.spinePad)
                        .environment(\.page, page)
                        // another conversation: this one is cut and that one arrives, never one read through the other
                        .arrives(on: ask.currentID)
                    }
                    .coordinateSpace(name: "chat.scroll")
                    // an answer being written keeps its last line in view, above the input: when the foot of it goes
                    // below the fold the page follows. the owner scrolls up to read back and it stops; back at the foot, it follows again
                    .onPreferenceChange(TailKey.self) { y in
                        guard let y else { return }
                        if y <= geo.size.height + 2 { if !ask.follow { ask.follow = true }; return }
                        guard ask.follow else { return }
                        DispatchQueue.main.async { proxy.scrollTo("tail", anchor: .bottom) }
                    }
                    .onAppear {
                        ask.onScreen = true
                        if let id = ask.currentID { ask.open(id) }
                        if let id = ask.goTo { ask.goTo = nil; DispatchQueue.main.async { proxy.scrollTo("turn\(id)", anchor: .top) } } else { jump(proxy, animated: false) }
                    }
                    .onDisappear { ask.onScreen = false }
                    .onChange(of: ask.goTo) { _, id in
                        if let id { ask.goTo = nil; DispatchQueue.main.async { proxy.scrollTo("turn\(id)", anchor: .top) } }
                    }
                    .onChange(of: ask.currentID) { _, _ in if ask.goTo == nil { jump(proxy, animated: false) } }
                    .onChange(of: ask.turns.count) { _, _ in jump(proxy, animated: true) }
                    .onChange(of: ask.askedAt) { _, _ in ask.follow = true; jump(proxy, animated: true) }
                }
            }
            Composer()
                .frame(maxWidth: ChatView.column + 28)
                .padding(.horizontal, Grid.spinePad - 14).padding(.top, 8).padding(.bottom, 16)
        }
        .overlayPreferenceValue(PeekKey.self) { found in
            GeometryReader { geo in
                if let found, let hit = found.hit(in: ask.turns) {
                    // the card opens out of the number it belongs to (raycast's menu: .97 to 1 with the fade), and is cut when it goes
                    let r = geo[found.anchor]
                    PeekCard.placed(hit: hit, number: found.number, at: r, in: geo.size)
                        .transition(reduce ? .opacity : .asymmetric(
                            insertion: .scale(scale: 0.97, anchor: UnitPoint(x: r.midX / max(1, geo.size.width), y: r.midY / max(1, geo.size.height))).combined(with: .opacity),
                            removal: .opacity))
                        .id(found.key)
                }
            }
            .allowsHitTesting(false)
            .animation(reduce ? .easeOut(duration: 0.05) : Motion.enter, value: found?.key)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func jump(_ proxy: ScrollViewProxy, animated: Bool) {
        guard let last = model.ask.turns.last else { return }
        DispatchQueue.main.async {
            withAnimation(animated && !reduce ? Motion.snap(false, 0.5) : nil) { proxy.scrollTo("turn\(last.id)", anchor: .top) }
        }
    }
}

/// Where the foot of the answer being written is, from the top of the conversation's own window.
struct TailKey: PreferenceKey {
    static let defaultValue: CGFloat? = nil
    static func reduce(value: inout CGFloat?, nextValue: () -> CGFloat?) { value = nextValue() ?? value }
}

// MARK: one turn

struct ChatTurn: View {
    /// The status line takes this long to leave, and the answer waits exactly that long before it starts to arrive.
    static let statusOut = 0.14, answerIn = 0.4
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduce
    let turn: Turn
    @Environment(\.page) private var page
    @State private var ys: [Int: CGFloat] = [:]       // where each citation's number stands in the text, from the top of the answer

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            // their own words: a soft bubble, on the right
            HStack(alignment: .top, spacing: 0) {
                Spacer(minLength: 64)
                Text(turn.q)
                    .font(.system(size: 15)).lineSpacing(3)
                    .foregroundStyle(Ink.ink)
                    .fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
                    .probe("chat.question", .text, group: "chat.turn\(turn.id)", scrolls: true)
                    .padding(.horizontal, 15).padding(.vertical, 10)
                    .background(Ink.wash, in: RoundedRectangle(cornerRadius: Radius.field, style: .continuous))
                    // the one being changed: the live edge
                    .overlay { if model.ask.editing == turn.id { RoundedRectangle(cornerRadius: Radius.field, style: .continuous).strokeBorder(Ink.ember, lineWidth: 1) } }
                    .probe("chat.bubble", .block, scrolls: true)
                    .modifier(Lift(on: turn.answer == nil && turn.live == nil))
            }
            // the answer, or as much of it as has been written so far
            if let a = (turn.showFirst ? turn.first : nil) ?? turn.answer ?? turn.live?.partial(tag: "t\(turn.id)") {
                let done = turn.answer != nil
                // how the owner asked for evidence to be shown, unless the owner asked to see it for this one answer
                let prefs = model.rules.prefs
                let evidence = model.ask.evidenceShown.contains(turn.id) ? "on" : prefs.citations
                let ribbon = evidence != "off" && (prefs.ribbon || model.ask.evidenceShown.contains(turn.id))
                let made = done ? a.made : nil
                HStack(alignment: .top, spacing: PageMeasure.gap) {
                VStack(alignment: .leading, spacing: 0) {
                    if a.text.isEmpty {
                        Failure(turn: turn, sentence: a.error)
                    } else {
                        // the days this answer rests on: a dot a message, drawn as each is found
                        // a thing made for them is a document: what kind it is and its name stand over it
                        if let made { MadeHead(made: made).padding(.top, 14) }
                        if ribbon, !a.cites.isEmpty || !done { Ribbon(turn: turn.id, cites: a.cites, live: !done || turn.streamed).padding(.top, 10) }
                        StepsLine(turn: turn).padding(.top, 14)
                        if let made, model.made.editing == made.id {
                            MadeEditor().padding(.top, 12)
                        } else {
                            AnswerText(turn: turn, answer: made.flatMap { m in model.made.showing[m.id].flatMap { _ in model.made.text(m.id) } }.map { t in var b = a; b.text = t; return b } ?? a, writing: !done)
                                .padding(.top, done && a.secs < 1 && a.steps.isEmpty ? 4 : 12)
                        }
                        if let made { MadeBar(made: made, text: a.plainText).padding(.top, 12) }
                        if done, evidence != "on", !a.cites.isEmpty {
                            Button("show where this came from") { model.ask.evidenceShown.insert(turn.id) }
                                .buttonStyle(QuietButton(size: Face.small)).padding(.top, 10)
                                .help("the numbers, the notes and the days this answer rests on, for this answer")
                                .probe("chat.show", .button, scrolls: true)
                        }
                        if done {
                            if a.stopped { Aside(text: "stopped before it finished.").padding(.top, 10) }
                            else if a.strength == "weak", turn.dig == nil, !a.deep { Aside(text: "not sure this is what you meant.").padding(.top, 10) }
                            if !a.fallback.isEmpty { Aside(text: a.fallback).padding(.top, 10) }
                            // their own rules had a hand in this: said in one quiet line, which opens them with those lit
                            if !a.rules.isEmpty, model.rules.shown {
                                Button(a.rules.count == 1 ? "1 of your rules shaped this" : "\(a.rules.count) of your rules shaped this") { model.openTeach(lit: a.rules) }
                                    .buttonStyle(QuietButton(size: Face.small)).padding(.top, 10)
                                    .help("opens teach with those rules lit")
                                    .probe("chat.rules", .button, scrolls: true)
                            }
                            DeepLine(turn: turn, showing: a)
                            if !turn.items.isEmpty { LensItems(turn: turn).padding(.top, 14) }
                            if !a.links.isEmpty { LinkList(turn: turn, links: a.links).padding(.top, 14) }
                            ActionRow(turn: turn, answer: a).padding(.top, 10)
                                .transition(reduce || Probe.on ? .opacity : .opacity.combined(with: .offset(y: 8)))
                        }
                    }
                }
                .frame(maxWidth: page?.text ?? .infinity, alignment: .leading)
                .overlayPreferenceValue(NoteAnchorKey.self) { anchors in
                    GeometryReader { geo in
                        Color.clear.preference(key: NoteYKey.self, value: Dictionary(anchors.map { ($0.n, geo[$0.anchor].minY) }, uniquingKeysWith: min))
                    }
                    .allowsHitTesting(false)
                }
                // the evidence, in the margin: each note level with the sentence it supports
                if let page, evidence == "on", !a.cites.isEmpty, !a.text.isEmpty {
                    MarginNotes(turn: turn, cites: a.cites, ys: ys).frame(width: page.notes, alignment: .topLeading)
                }
                }
                .onPreferenceChange(NoteYKey.self) { new in if new != ys { ys = new } }
                .environment(\.streaming, !done)
                .environment(\.evidence, evidence)
                // an answer that was written on screen as it came does not arrive a second time
                .transition(turn.streamed || !done ? .identity : .asymmetric(
                    insertion: (reduce || Probe.on ? AnyTransition.opacity : AnyTransition.opacity.combined(with: .offset(y: 8)))
                        .animation(.easeOut(duration: reduce ? 0.1 : ChatTurn.answerIn).delay(ChatTurn.statusOut)),
                    removal: .identity))
                .animation(Motion.snap(reduce, 0.2), value: done)
            } else {
                Ribbon(turn: turn.id, cites: turn.live?.cites ?? [], live: true).padding(.top, 10)
                    .frame(maxWidth: page?.text ?? .infinity, alignment: .leading)
                StepsLine(turn: turn).padding(.top, 14)
                    .transition(.asymmetric(insertion: .opacity, removal: .opacity.animation(.easeOut(duration: ChatTurn.statusOut))))
            }
        }
        .padding(.top, 24).padding(.bottom, 18)
        .animation(.easeOut(duration: ChatTurn.statusOut), value: turn.answer != nil)
    }
}

/// Under an answer: copy it, say whether it was right, ask it again, save it, and at the end the door to its sources.
struct ActionRow: View {
    @Environment(AppModel.self) private var model
    let turn: Turn
    let answer: Answer
    @Environment(\.evidence) private var evidence
    @State private var copied = false
    @State private var marked = false
    @State private var saved = false

    var body: some View {
        let ask = model.ask
        let draft = answer.isDraft(for: turn.q)
        HStack(spacing: 0) {
            // a draft in their own voice is copied as it stands, the words alone: context never sends anything anywhere
            act(copied ? "checkmark" : "doc.on.doc", copied ? "copied" : (draft ? "copy the draft" : "copy")) { Clip.copy(draft ? answer.plainText : AskModel.plain(turn)); copied = true; marked = false }
                .probe("chat.act", .button, group: "chat.acts\(turn.id)", scrolls: true)
            if !draft {
                act(marked ? "checkmark" : "number", marked ? "copied as markdown" : "copy as markdown") { Clip.copy(AskModel.markdown(turn)); marked = true; copied = false }
                    .probe("chat.act", .button, group: "chat.acts\(turn.id)", scrolls: true)
            }
            if !answer.cites.isEmpty, !answer.stopped, !draft {
                if turn.rated != false {
                    act(turn.rated == true ? "hand.thumbsup.fill" : "hand.thumbsup", turn.rated == true ? "noted: good answer" : "good answer") { ask.rate(turn, ok: true, model.engine) }
                        .probe("chat.act", .button, group: "chat.acts\(turn.id)", scrolls: true)
                }
                if turn.rated != true {
                    act(turn.rated == false ? "hand.thumbsdown.fill" : "hand.thumbsdown",
                        turn.rated == false ? "noted: not right. later searches will lean away from these rows" : "not right") { ask.rate(turn, ok: false, model.engine) }
                        .probe("chat.act", .button, group: "chat.acts\(turn.id)", scrolls: true)
                }
            }
            if !draft {
                BarButton(symbol: "arrow.clockwise", help: "ask it again", size: 12, label: "ask again") { ask.again(turn, model.engine) }
                    .probe("chat.act", .button, group: "chat.acts\(turn.id)", scrolls: true)
                act(saved ? "checkmark" : "text.badge.plus", saved ? "saved to today's journal" : "save to journal") {
                    if !saved { model.journal.append(AskModel.plain(turn)); saved = true }
                }
                .probe("chat.act", .button, group: "chat.acts\(turn.id)", scrolls: true)
            }
            if evidence == "on" || answer.cites.isEmpty, !answer.cites.isEmpty || !answer.maybe.isEmpty || !answer.searched.isEmpty {
                let on = ask.sourcesFor == turn.id
                Button { ask.toggleSources(turn.id) } label: {
                    HStack(spacing: 7) {
                        if !answer.cites.isEmpty { IconStack(srcs: answer.cites.map(\.src), ground: on ? Ink.wash : Ink.paper) }
                        Text(answer.cites.isEmpty ? "how it searched" : "sources  ·  \(answer.cites.count)")
                            .font(.system(size: 12, weight: .medium)).foregroundStyle(on ? Ink.ink : Ink.soft).lineLimit(1).fixedSize()
                    }
                    .padding(.horizontal, 9).frame(height: 26)
                    .background(on ? Ink.wash : .clear, in: Capsule())
                    .contentShape(Capsule())
                }
                .buttonStyle(.plain)
                .accessibilityLabel(answer.cites.isEmpty ? "how it searched" : "\(answer.cites.count) sources").accessibilityHint("opens them beside the answer")
                .ring(13, inset: 0)
                .padding(.leading, 6)
                .probe("chat.sources", .button, group: "chat.turn\(turn.id)", scrolls: true)
            }
            Spacer(minLength: 0)
        }
        .padding(.leading, -7)          // the first symbol stands on the answer's left edge
        .onChange(of: turn.at) { _, _ in copied = false; marked = false; saved = false }
    }

    private func act(_ symbol: String, _ help: String, _ action: @escaping () -> Void) -> some View {
        BarButton(symbol: symbol, help: help, size: 12, action: action)
    }
}

/// What a lens found, to work down: each line says whether it is still open, who it concerns and when.
/// The pointer over one offers "done", "not real" and the row it came from.
struct LensItems: View {
    @Environment(AppModel.self) private var model
    let turn: Turn

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Rectangle().fill(Ink.line).frame(height: 1)
            ForEach(turn.items) { item in LensLine(item: item, turn: turn) }
        }
    }
}

struct LensLine: View {
    @Environment(AppModel.self) private var model
    let item: LensItem
    let turn: Turn
    @State private var hover = false

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 11) {
            // empty is open, full is done, a ring with a dot is unclear
            ZStack {
                Circle().strokeBorder(item.status == "done" ? Ink.soft : Ink.faint, lineWidth: 1.5)
                Circle().fill(Ink.soft).padding(item.status == "done" ? 0 : 4).opacity(item.status == "open" ? 0 : 1)
            }
            .frame(width: 13, height: 13).alignmentGuide(.firstTextBaseline) { $0[.bottom] - 2 }
            VStack(alignment: .leading, spacing: 5) {
                Text(item.what).font(.system(size: 15, weight: .medium)).lineSpacing(2)
                    .foregroundStyle(item.status == "done" ? Ink.soft : Ink.ink)
                    .strikethrough(item.status == "done", color: Ink.faint)
                    .fixedSize(horizontal: false, vertical: true)
                    .probe("lens.what", .text, scrolls: true)
                if hover || Probe.on && item.id == turn.items.first?.id {
                    HStack(spacing: 16) {
                        if item.status != "done" { Button("done") { model.ask.score(item, ok: true, in: turn.id) }.buttonStyle(QuietButton(size: 12)) }
                        Button("not real") { model.ask.score(item, ok: false, in: turn.id) }.buttonStyle(QuietButton(size: 12))
                        if let c = item.cite { Button("show the row") { model.ask.show(c, in: turn.id) }.buttonStyle(QuietButton(size: 12)) }
                    }
                    .transition(.opacity)
                }
            }
            Spacer(minLength: 8)
            VStack(alignment: .trailing, spacing: 3) {
                Text(item.who).font(.system(size: 13, weight: .medium)).foregroundStyle(Ink.soft).lineLimit(1)
                Text(Words.day(item.when)).font(.system(size: 12, weight: .medium)).monospacedDigit().foregroundStyle(Ink.faint).lineLimit(1)
            }
            .frame(width: 100, alignment: .trailing)
        }
        .padding(.vertical, 10)
        .overlay(alignment: .bottom) { Rectangle().fill(Ink.line).frame(height: 1) }
        .contentShape(Rectangle())
        .onHover { hover = $0 }
        .probe("lens.row", .block, group: "lens.rows\(turn.id)", scrolls: true)
        .animation(.easeOut(duration: 0.12), value: hover)
    }
}

/// A question waiting its turn: their words, quieter, marked "next", with a way to take it back.
struct Queued: View {
    @Environment(AppModel.self) private var model
    let index: Int
    let text: String

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Text(index == 0 ? "next" : "then").font(.system(size: 11, weight: .bold, design: .rounded)).foregroundStyle(Ink.soft)
                .padding(.horizontal, 6).frame(height: 17)
                .background(Ink.wash, in: RoundedRectangle(cornerRadius: Radius.chip, style: .continuous))
                .fixedSize()
            Text(text).font(.system(size: 17, weight: .semibold)).tracking(-0.25).lineSpacing(3).foregroundStyle(Ink.faint)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
                .probe("chat.queued", .text, group: "chat.queue", scrolls: true)
            Button("take back") {
                if model.ask.queue.indices.contains(index) { model.ask.draft = model.ask.queue.remove(at: index) }
            }
            .buttonStyle(QuietButton(size: 12))
        }
        .padding(.top, 14).padding(.bottom, 6)
    }
}

/// One line while the engine reads: what it is doing, for how long, and the key that stops it.
struct Reading: View {
    let since: Date

    var body: some View {
        TimelineView(.periodic(from: since, by: 1)) { t in
            let s = max(0, Int(t.date.timeIntervalSince(since)))
            HStack(alignment: .firstTextBaseline, spacing: 9) {
                Mark(source: Catalog.neutral, mood: .reading, size: 7).alignmentGuide(.firstTextBaseline) { $0[.bottom] - 1 }
                Text(s < 45 ? "reading your history. about a quarter of a minute." : "still reading. a long one can take a minute or two.")
                    .font(.system(size: 15, weight: .regular, design: .serif)).foregroundStyle(Ink.soft).lineLimit(1)
                    .probe("chat.status", .line, scrolls: true)
                Text("\(s) s").font(.system(size: 12, weight: .medium)).monospacedDigit().foregroundStyle(Ink.faint)
                    .contentTransition(.numericText())
                Spacer(minLength: 8)
            }
        }
    }
}

/// While an answer is on its way and nothing is written yet: the step the engine says it is on, and how long it has been.
struct Waiting: View {
    @Environment(\.accessibilityReduceMotion) private var reduce
    let turn: Turn

    var body: some View {
        TimelineView(.periodic(from: turn.at, by: 1)) { t in
            let s = max(0, Int(t.date.timeIntervalSince(turn.at)))
            let line = turn.live?.line ?? (s < 45 ? "reading your history. about a quarter of a minute." : "still reading. a long one can take a minute or two.")
            HStack(alignment: .firstTextBaseline, spacing: 9) {
                Mark(source: Catalog.neutral, mood: .reading, size: 7).alignmentGuide(.firstTextBaseline) { $0[.bottom] - 1 }
                Text(line)
                    .font(.system(size: 15, weight: .regular, design: .serif)).foregroundStyle(Ink.soft)
                    .fixedSize(horizontal: false, vertical: true)
                    .probe("chat.status", .text, scrolls: true)
                    .id(line).transition(.opacity)
                Text("\(s) s").font(.system(size: 12, weight: .medium)).monospacedDigit().foregroundStyle(Ink.faint)
                    .contentTransition(.numericText()).fixedSize()
                Spacer(minLength: 8)
            }
            .animation(reduce ? nil : .easeOut(duration: 0.16), value: line)
        }
    }
}

/// Under an answer that is still being written: how long it has been. The live edge is the caret at the end of its last line.
struct WritingEdge: View {
    let since: Date
    var body: some View {
        TimelineView(.periodic(from: since, by: 1)) { t in
            HStack(alignment: .center, spacing: 8) {
                Text("writing").font(.system(size: 12, weight: .medium)).foregroundStyle(Ink.soft).fixedSize()
                    .probe("chat.writing", .line, scrolls: true)
                Text("\(max(0, Int(t.date.timeIntervalSince(since)))) s").font(.system(size: 12, weight: .medium)).monospacedDigit().foregroundStyle(Ink.faint)
                    .contentTransition(.numericText()).fixedSize()
            }
        }
    }
}

/// Under an answer that was not strong: the deeper search while it runs, then what it did and the way back to the first answer.
struct DeepLine: View {
    @Environment(AppModel.self) private var model
    let turn: Turn
    let showing: Answer

    var body: some View {
        if let doing = turn.dig, showing.strength != "strong" {
            HStack(alignment: .firstTextBaseline, spacing: 9) {
                Mark(source: Catalog.neutral, mood: .reading, size: 7).alignmentGuide(.firstTextBaseline) { $0[.bottom] - 1 }
                Text(doing.isEmpty ? "looking deeper…" : "looking deeper… " + doing).font(.system(size: 14, weight: .regular, design: .serif)).foregroundStyle(Ink.soft)
                    .fixedSize(horizontal: false, vertical: true)
                    .probe("chat.dig", .text, scrolls: true)
                    .id(doing).transition(.opacity)
                Spacer(minLength: 8)
            }
            .padding(.top, 12)
            .animation(.easeOut(duration: 0.16), value: doing)
        } else if turn.first != nil {
            HStack(alignment: .firstTextBaseline, spacing: 14) {
                Aside(text: turn.showFirst ? "this is the first answer." : (turn.answer?.trail ?? ""))
                Button(turn.showFirst ? "deeper answer" : "first answer") {
                    if let i = model.ask.turns.firstIndex(where: { $0.id == turn.id }) { model.ask.turns[i].showFirst.toggle() }
                }
                .buttonStyle(QuietButton(size: 12)).fixedSize()
                .probe("chat.first", .button, scrolls: true)
                Spacer(minLength: 0)
            }
            .padding(.top, 10)
        }
    }
}

/// One quiet sentence about the answer above it.
struct Aside: View {
    let text: String
    var body: some View {
        Text(text).font(.system(size: 13, weight: .regular, design: .serif)).italic().foregroundStyle(Ink.faint)
            .fixedSize(horizontal: false, vertical: true)
            .probe("chat.aside", .text, scrolls: true)
    }
}

/// Anything that is not an answer: one plain sentence, and the way to ask again.
struct Failure: View {
    @Environment(AppModel.self) private var model
    let turn: Turn
    let sentence: String

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(sentence)
                .font(.system(size: 16, weight: .regular, design: .serif)).lineSpacing(4).foregroundStyle(Ink.soft)
                .fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
                .probe("chat.error", .text, group: "chat.turn\(turn.id)", scrolls: true)
            Button("try again") { model.ask.again(turn, model.engine) }
                .buttonStyle(Starter())
                .probe("chat.again", .button, group: "chat.turn\(turn.id)", scrolls: true)
        }
        .padding(.top, 12)
    }
}

// MARK: the answer, with its citations set in the line

enum Typeset {
    private static var cache: [CGFloat: CGFloat] = [:]
    /// The width of a space in the serif face at this size, so words set one by one sit as they would in a paragraph.
    static func space(_ size: CGFloat) -> CGFloat {
        if let w = cache[size] { return w }
        let base = NSFont.systemFont(ofSize: size)
        let font = base.fontDescriptor.withDesign(.serif).flatMap { NSFont(descriptor: $0, size: size) } ?? base
        let w = (" " as NSString).size(withAttributes: [.font: font]).width
        cache[size] = w
        return w
    }
}

/// An address, shown cut in the middle. A click opens it in the default browser; the pointer over it offers a copy.
struct LinkWord: View {
    let url: URL
    var size: CGFloat = 16
    var design: Font.Design = .serif
    @State private var hover = false
    @State private var copied = false

    var body: some View {
        Text(Answer.short(url.absoluteString))
            .font(.system(size: size, weight: .regular, design: design)).underline(true, color: hover ? Ink.ink : Ink.faint)
            .foregroundStyle(Ink.ink).lineLimit(1)
            .contentShape(Rectangle())
            .onTapGesture { if !Probe.on { NSWorkspace.shared.open(url) } }
            .onHover { hover = $0; if !$0 { copied = false } }
            .overlay(alignment: .topTrailing) {
                if hover {
                    Button(copied ? "copied" : "copy") { Clip.copy(url.absoluteString); copied = true }
                        .buttonStyle(.plain)
                        .font(.system(size: 10, weight: .bold, design: .rounded)).foregroundStyle(Ink.paper)
                        .padding(.horizontal, 6).frame(height: 16)
                        .background(Ink.ink, in: RoundedRectangle(cornerRadius: Radius.chip, style: .continuous))
                        .fixedSize().offset(x: 6, y: -15)
                        .transition(.opacity)
                }
            }
            .help(url.absoluteString)
            .animation(.easeOut(duration: 0.1), value: hover)
            .accessibilityAddTraits(.isLink)
    }
}

enum Clip {
    static func copy(_ s: String) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(s, forType: .string)
    }
}

/// The addresses an answer hands over, most likely first: what each is, where it came from, when. A click opens one.
struct LinkList: View {
    let turn: Turn
    let links: [LinkRef]

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            ForEach(links.prefix(5)) { l in LinkCard(link: l).probe("chat.link", .block, group: "chat.links\(turn.id)", scrolls: true) }
        }
    }
}

struct LinkCard: View {
    let link: LinkRef
    @State private var hover = false
    @State private var copied = false

    var body: some View {
        HStack(alignment: .center, spacing: 11) {
            SourceIcon(id: link.src.isEmpty ? "_window" : link.src, size: 22)
            VStack(alignment: .leading, spacing: 2) {
                Text(link.what.isEmpty ? Answer.short(link.url, max: 60) : link.what)
                    .font(.system(size: 14, weight: .semibold)).foregroundStyle(Ink.ink).lineLimit(1)
                // the address at the length the card has room for: shortened further in a narrow page, never cut mid-way
                ViewThatFits(in: .horizontal) {
                    Text(Answer.short(link.url, max: 30)).lineLimit(1).fixedSize()
                    Text(Answer.short(link.url, max: 20)).lineLimit(1).fixedSize()
                    Text(Answer.short(link.url, max: 12)).lineLimit(1)
                }
                .font(.system(size: 12)).foregroundStyle(Ink.soft)
                .probe("chat.link.url", .block, scrolls: true)
            }
            Spacer(minLength: 8)
            if hover {
                Button(copied ? "copied" : "copy") { Clip.copy(link.url); copied = true }.buttonStyle(QuietButton(size: 12))
            }
            Text(Words.day(link.ts)).font(.system(size: 12, weight: .medium)).monospacedDigit().foregroundStyle(Ink.faint).lineLimit(1).fixedSize()
            Image(systemName: "arrow.up.right").font(.system(size: 10, weight: .bold)).foregroundStyle(hover ? Ink.ink : Ink.faint)
        }
        .padding(.horizontal, 12).frame(height: 50)
        .background(Ink.wash.opacity(hover ? 1 : 0.55), in: RoundedRectangle(cornerRadius: Radius.card, style: .continuous))
        .contentShape(Rectangle())
        .onTapGesture { if !Probe.on, let u = Answer.web(link.url) { NSWorkspace.shared.open(u) } }
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isLink)
        .onHover { hover = $0; if !$0 { copied = false } }
        .help(link.url)
        .animation(.easeOut(duration: 0.12), value: hover)
    }
}

/// A citation: a small raised number. The pointer over it shows the row; a click goes to it in the sources.
struct Chip: View {
    @Environment(AppModel.self) private var model
    let number: Int
    let hit: Hit
    let turn: Int
    let key: String
    @State private var hover = false
    @Environment(\.page) private var page

    static func width(_ n: Int) -> CGFloat { n < 10 ? 14 : 19 }

    var body: some View {
        let me = Pick(turn: turn, n: number)
        let on = hover || model.ask.peek == key || model.ask.flash == hit.id || model.ask.chosen == me
        let margin = page != nil
        Text("\(number)")
            // beside a margin of notes the number is only a small raised figure: the note carries the rest
            .font(margin ? .system(size: 9.5, weight: on ? .bold : .medium, design: .monospaced) : .system(size: 9.5, weight: .bold, design: .rounded)).monospacedDigit()
            .foregroundStyle(margin ? (on ? Ink.ink : Ink.soft) : (on ? Ink.paper : Ink.soft))
            .frame(width: Chip.width(number), height: 14)
            .background(margin ? Color.clear : (on ? Ink.ink : Ink.wash), in: RoundedRectangle(cornerRadius: Radius.chip, style: .continuous))
            .contentShape(Rectangle())
            .onHover { inside in
                hover = inside
                if inside { model.ask.hoverPick = me } else if model.ask.hoverPick == me { model.ask.hoverPick = nil }
                guard !margin else { return }
                if inside { model.ask.peek = key; model.ask.hovered = (hit, turn) } else if model.ask.peek == key { model.ask.peek = nil }
            }
            .onTapGesture {
                model.ask.pinned = me
                if margin { model.ask.peekThread(hit, turn: turn, model.engine, margin: true) } else { model.ask.peekThread(hit, turn: turn, model.engine) }
            }
            .anchorPreference(key: NoteAnchorKey.self, value: .bounds) { [NoteAnchor(n: number, anchor: $0)] }
            .probe("chat.cite", .block, scrolls: true)
            .accessibilityAddTraits(.isButton)
            .accessibilityHint("opens the message in its conversation")
            .anchorPreference(key: PeekKey.self, value: .bounds) { model.ask.peek == key ? Peek(key: key, number: number, turn: turn, anchor: $0) : nil }
            .scaleEffect(on ? 1.12 : 1)
            .animation(Motion.pop(false), value: on)
            .accessibilityLabel("source \(number)")
    }
}

struct Peek {
    let key: String
    let number: Int
    let turn: Int
    let anchor: Anchor<CGRect>

    func hit(in turns: [Turn]) -> Hit? {
        guard let cites = turns.first(where: { $0.id == turn })?.answer?.cites, number >= 1, number <= cites.count else { return nil }
        return cites[number - 1]
    }
}

struct PeekKey: PreferenceKey {
    static var defaultValue: Peek? = nil
    static func reduce(value: inout Peek?, nextValue: () -> Peek?) { value = value ?? nextValue() }
}

/// The card under a citation: where the row came from, when, and about three lines of it.
struct PeekCard: View {
    let hit: Hit
    let number: Int
    static let width: CGFloat = 320

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack(alignment: .center, spacing: 8) {
                CiteIcon(src: hit.src, size: 16)
                Text(Cite.title(hit)).font(.system(size: 13, weight: .semibold)).foregroundStyle(Ink.ink).lineLimit(1)
                Spacer(minLength: 8)
                Text(Words.day(hit.ts)).font(.system(size: 11, weight: .medium)).monospacedDigit().foregroundStyle(Ink.faint)
                    .lineLimit(1).fixedSize()
                    .probe("chat.peek.date", .line)
            }
            Text(hit.snippet)
                .font(.system(size: 13)).lineSpacing(2.5).foregroundStyle(Ink.soft)
                .lineLimit(3).fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
            Text(Cite.by(hit)).font(.system(size: 11, weight: .medium)).foregroundStyle(Ink.faint).lineLimit(1)
        }
        .padding(.horizontal, 14).padding(.vertical, 12)
        .frame(width: PeekCard.width, alignment: .leading)
        .background(Ink.raised, in: RoundedRectangle(cornerRadius: Radius.card, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: Radius.card, style: .continuous).strokeBorder(Ink.line, lineWidth: 1))
        .shadow(color: .black.opacity(0.10), radius: 16, y: 6)
        .probe("chat.peek", .block)
    }

    /// Under the number when there is room, else above it; never past a side of the window.
    @ViewBuilder static func placed(hit: Hit, number: Int, at r: CGRect, in size: CGSize) -> some View {
        let x = max(16, min(r.midX - 40, size.width - width - 16))
        let below = r.maxY + 150 < size.height - 70
        PeekCard(hit: hit, number: number)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: below ? .topLeading : .bottomLeading)
            .offset(x: x, y: below ? r.maxY + 6 : -(size.height - r.minY + 6))
    }
}

/// Words for a cited row.
enum Cite {
    static func title(_ h: Hit) -> String {
        let t = h.thread.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return t.isEmpty ? Catalog.info(h.src).name : t
    }

    /// "you wrote this · whatsapp"
    static func by(_ h: Hit) -> String {
        let who = h.who == "me" ? "you wrote this" : (h.who == "saved" ? "you saved this" : "written to you")
        let name = Catalog.info(h.src).name
        return name.isEmpty ? who : who + "  ·  " + name
    }

    /// The person a row was written by, when it was written to them: its sender, or the name of a one-to-one conversation.
    static func from(_ h: Hit) -> String? {
        guard h.who != "me", h.who != "saved" else { return nil }
        // the engine names the writer in "sender", or in "who" when that is not just me or them
        for one in [h.sender, h.who] {
            let s = one.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
            if !s.isEmpty, !["them", "me", "you", "saved"].contains(s) { return s }
        }
        let t = h.thread.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return AppModel.shared.people.resolve(t) != nil ? t : nil
    }

    static func link(_ h: Hit) -> URL? {
        guard let u = URL(string: h.url), let s = u.scheme?.lowercased(), s == "http" || s == "https" else { return nil }
        return u
    }
}

/// A source's icon at the size of a line of text: the shelf's own icon, so a source looks the same everywhere.
struct CiteIcon: View {
    let src: String
    var size: CGFloat = 16
    var body: some View { SourceIcon(id: src, size: size) }
}

/// Sets its children like words: left to right on one baseline, wrapping at the column.
struct WordFlow: Layout {
    var space: CGFloat
    var lineSpacing: CGFloat

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let rows = arrange(proposal.width ?? .infinity, subviews)
        let height = rows.reduce(0) { $0 + $1.height } + CGFloat(max(0, rows.count - 1)) * lineSpacing
        let widest = rows.map(\.width).max() ?? 0
        return CGSize(width: proposal.width.map { $0.isFinite ? max(min($0, widest), 0) : widest } ?? widest, height: height)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var y = bounds.minY
        for row in arrange(bounds.width, subviews) {
            var x = bounds.minX
            for (k, (i, size)) in row.items.enumerated() {
                if k > 0 { x += subviews[i][Glue.self] ? 0 : space }
                subviews[i].place(at: CGPoint(x: x, y: y + row.height - size.height), anchor: .topLeading, proposal: ProposedViewSize(size))
                x += size.width
            }
            y += row.height + lineSpacing
        }
    }

    private func arrange(_ width: CGFloat, _ subviews: Subviews) -> [(items: [(Int, CGSize)], width: CGFloat, height: CGFloat)] {
        var rows: [(items: [(Int, CGSize)], width: CGFloat, height: CGFloat)] = []
        var cur: [(Int, CGSize)] = [], w: CGFloat = 0, h: CGFloat = 0
        for i in subviews.indices {
            var size = subviews[i].sizeThatFits(.unspecified)
            if size.width > width { size = subviews[i].sizeThatFits(ProposedViewSize(width: width, height: nil)) }   // one very long word wraps in itself
            // a word that sits tight against the one before (a comma after bold, the end of a link) never starts a line alone
            let gap = subviews[i][Glue.self] ? 0 : space
            if !cur.isEmpty, gap > 0, w + gap + size.width > width + 0.5 {
                rows.append((cur, w, h))
                cur = []; w = 0; h = 0
            }
            w += (cur.isEmpty ? 0 : gap) + size.width
            h = max(h, size.height)
            cur.append((i, size))
        }
        if !cur.isEmpty { rows.append((cur, w, h)) }
        return rows
    }
}

// MARK: sources

/// Under an answer: one quiet row that says how many rows it rests on. Unfolded, a numbered list of them,
/// and how the engine searched.
struct SourcesBlock: View {
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduce
    let turn: Turn
    let answer: Answer
    @State private var saved = false
    @State private var copied = false

    var body: some View {
        let ask = model.ask
        let open = ask.openSources.contains(turn.id)
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 16) {
                Button {
                    if open { ask.openSources.remove(turn.id) } else { ask.openSources.insert(turn.id) }
                } label: {
                    HStack(spacing: 8) {
                        if !answer.cites.isEmpty { IconStack(srcs: answer.cites.map(\.src)) }
                        Text(answer.cites.isEmpty ? "how it searched" : "\(answer.cites.count) source\(answer.cites.count == 1 ? "" : "s")")
                        Image(systemName: "chevron.down").font(.system(size: 8.5, weight: .bold))
                            .rotationEffect(.degrees(open ? 180 : 0))
                    }
                    .frame(height: 30)
                }
                .buttonStyle(QuietButton(size: 13))
                .probe("chat.sources", .button, group: "chat.turn\(turn.id)", scrolls: true)
                Spacer(minLength: 8)
                Button(copied ? "copied" : "copy") {
                    Clip.copy(AskModel.plain(turn))
                    copied = true
                }
                .buttonStyle(QuietButton(size: 12))
                Button(saved ? "saved to today's journal" : "save to journal") {
                    if !saved { model.journal.append(AskModel.plain(turn)); saved = true }
                }
                .buttonStyle(QuietButton(size: 12))
            }
            if open {
                VStack(alignment: .leading, spacing: 0) {
                    Rectangle().fill(Ink.line).frame(height: 1)
                    ForEach(Array(answer.cites.enumerated()), id: \.element.id) { i, hit in
                        SourceLine(number: i + 1, hit: hit, open: ask.openCite == hit.id, lit: ask.flash == hit.id)
                            .id(hit.id)
                    }
                    if !answer.searched.isEmpty || answer.found > 0 {
                        if answer.cites.isEmpty { how.padding(.top, 10) } else { HowLine(turn: turn, answer: answer) }
                    }
                }
                .padding(.top, 4)
                .transition(.opacity)
            }
        }
        .animation(Motion.snap(reduce, 0.3), value: open)
        .animation(Motion.snap(reduce, 0.3), value: ask.openCite)
    }

    private var how: some View { HowText(answer: answer) }
}

/// The sources' own icons, overlapped, each once.
struct IconStack: View {
    let srcs: [String]
    var ground = Ink.paper
    var body: some View {
        let unique = srcs.reduce(into: [String]()) { if !$0.contains($1) { $0.append($1) } }
        HStack(spacing: -6) {
            ForEach(Array(unique.prefix(4).enumerated()), id: \.element) { i, s in
                CiteIcon(src: s, size: 15)
                    .padding(2.5).background(ground, in: Circle())
                    .zIndex(Double(10 - i))
            }
        }
    }
}

/// One source: its number, where it came from, a line of it, the day. A click unfolds the whole row.
struct SourceLine: View {
    @Environment(AppModel.self) private var model
    let number: Int
    let hit: Hit
    let open: Bool
    let lit: Bool
    @State private var hover = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .center, spacing: 10) {
                Text("\(number)").font(.system(size: 11, weight: .bold, design: .rounded)).monospacedDigit()
                    .foregroundStyle(lit ? Ink.ink : Ink.faint).frame(width: 14, alignment: .leading)
                CiteIcon(src: hit.src, size: 16)
                Text(Cite.title(hit)).font(.system(size: 13, weight: .semibold)).foregroundStyle(Ink.ink)
                    .lineLimit(1).truncationMode(.tail)
                    .frame(width: 150, alignment: .leading)
                Text(open ? Cite.by(hit) : hit.snippet).font(.system(size: 13)).foregroundStyle(open ? Ink.faint : Ink.soft)
                    .lineLimit(1).truncationMode(.tail)
                    .frame(maxWidth: .infinity, alignment: .leading)
                if let url = Cite.link(hit) {
                    Button("open") { if !Probe.on { NSWorkspace.shared.open(url) } }.buttonStyle(QuietButton(size: 12)).help(hit.url)
                        .probe("chat.source.open", .button, scrolls: true)
                }
                Text(Words.day(hit.ts)).font(.system(size: 12, weight: .medium)).monospacedDigit().foregroundStyle(Ink.faint)
                    .lineLimit(1).fixedSize()
                    .probe("chat.source.date", .line, scrolls: true)
            }
            .frame(height: 36)
            .contentShape(Rectangle())
            .onTapGesture { model.ask.openCite = open ? nil : hit.id }
            .accessibilityElement(children: .combine)
            .accessibilityAddTraits(.isButton)
            .accessibilityHint("shows the whole message")
            if open {
                VStack(alignment: .leading, spacing: 10) {
                    Text(String(hit.text.trimmingCharacters(in: .whitespacesAndNewlines).prefix(1200)))
                        .font(.system(size: 14)).lineSpacing(3.5).foregroundStyle(Ink.ink)
                        .fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .probe("chat.source.text", .text, scrolls: true)
                    if let url = Cite.link(hit) { LinkWord(url: url, size: 13, design: .default) }
                }
                .padding(.leading, 50).padding(.trailing, 4).padding(.top, 2).padding(.bottom, 14)
                .transition(.opacity)
            }
        }
        .padding(.horizontal, 8)
        .background((lit ? Ink.wash : (hover && !open ? Ink.wash.opacity(0.55) : .clear)), in: RoundedRectangle(cornerRadius: Radius.row, style: .continuous))
        .padding(.horizontal, -8)
        .overlay(alignment: .bottom) { Rectangle().fill(Ink.line).frame(height: 1) }
        .onHover { hover = $0 }
        .animation(.easeOut(duration: 0.14), value: hover)
        .animation(.easeOut(duration: 0.3), value: lit)
        .probe("chat.source", .block, group: "chat.sources", scrolls: true)
    }
}

/// The last line of the sources: a quiet word that unfolds what the engine looked for and how much matched.
struct HowLine: View {
    @Environment(AppModel.self) private var model
    let turn: Turn
    let answer: Answer

    var body: some View {
        let ask = model.ask
        let open = ask.openHow.contains(turn.id)
        VStack(alignment: .leading, spacing: 6) {
            Button {
                if open { ask.openHow.remove(turn.id) } else { ask.openHow.insert(turn.id) }
            } label: {
                HStack(spacing: 7) {
                    Text("how it searched")
                    Image(systemName: "chevron.down").font(.system(size: 8, weight: .bold)).rotationEffect(.degrees(open ? 180 : 0))
                }
                .frame(height: 30)
            }
            .buttonStyle(QuietButton(size: 12))
            if open { HowText(answer: answer).padding(.bottom, 6).transition(.opacity) }
        }
    }
}

/// What it looked for, each search whole, and how many lines matched.
struct HowText: View {
    let answer: Answer

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            if !answer.searched.isEmpty {
                // a search is never broken across two lines: its own spaces do not wrap, only the gaps between searches do
                Text("looked for  " + answer.searched.map { $0.replacingOccurrences(of: " ", with: "\u{00A0}") }.joined(separator: "  ·  "))
                    .font(.system(size: 13)).lineSpacing(3).foregroundStyle(Ink.soft)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .probe("chat.how", .text, scrolls: true)
            }
            Text(count).font(.system(size: 12, weight: .medium)).monospacedDigit().foregroundStyle(Ink.faint)
                .probe("chat.how.count", .line, scrolls: true)
        }
    }

    private var count: String {
        let lines = answer.found == 0 ? "no lines matched" : "\(Words.count(answer.found)) line\(answer.found == 1 ? "" : "s") matched"
        return answer.secs >= 1 ? lines + "  ·  read in \(Int(answer.secs.rounded())) s" : lines
    }
}

// MARK: the input

/// The input: in the middle of home, at the foot of a chat. It grows to eight lines. Return sends, shift-return is a
/// new line, and while an answer is being written the button stops it. "+" narrows what is asked; the narrowing shows
/// as chips that can be taken off. "quick · deep" says how far the engine searches.
struct Composer: View {
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduce
    @Environment(\.askSpace) private var space
    @FocusState private var focused: Bool
    @FocusState private var naming: Bool
    var home = false
    var hotkey = false          // on the desk: the key that asks from anywhere is shown in the field
    @State private var person: String?
    @State private var tall: CGFloat = 0        // the height of what is typed, which the field follows on a spring

    var body: some View {
        @Bindable var ask = model.ask
        let empty = ask.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        let prompt = ask.editing != nil ? "change your message" : (home ? "ask your history" : "ask a follow-up")
        let shape = RoundedRectangle(cornerRadius: Radius.field, style: .continuous)
        VStack(alignment: .leading, spacing: 7) {
            VStack(alignment: .leading, spacing: 9) {
                if ask.editing != nil {
                    HStack(spacing: 8) {
                        RoundedRectangle(cornerRadius: 1).fill(Ink.ember).frame(width: 2, height: 12)
                        Text("changing your last message. it is asked again in its place.").font(.system(size: 12, weight: .medium)).foregroundStyle(Ink.soft).lineLimit(1)
                        Spacer(minLength: 6)
                        KeyHint(key: "esc")
                    }
                    .probe("chat.editing", .block)
                }
                TextField("", text: $ask.draft, prompt: Text(prompt).foregroundStyle(Ink.faint), axis: .vertical)
                    .tint(Ink.ember)
                    .lineLimit(1...8)
                    .textFieldStyle(.plain)
                    .font(.system(size: 15))
                    .foregroundStyle(Ink.ink)
                    .focused($focused)
                    .fixedSize(horizontal: false, vertical: true)
                    // the field's own height, which the box follows on a spring: a new line is room made, not a jump,
                    // and the box and whatever stands round it move together
                    .background(GeometryReader { g in
                        Color.clear
                            .onAppear { tall = g.size.height }
                            .onChange(of: g.size.height) { _, h in
                                if Probe.still || abs(h - tall) < 2 { tall = h } else { withAnimation(Motion.tray(reduce)) { tall = h } }
                            }
                    })
                    .background(alignment: .topLeading) {
                        // the same words laid out as plain text: the check that no line of what the owner typed is cut
                        Text(ask.draft.isEmpty ? prompt : ask.draft)
                            .font(.system(size: 15)).lineLimit(8)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .probe("chat.input.text", .text, group: "chat.bottom").hidden()
                    }
                    .frame(minHeight: 20)
                    .frame(height: tall > 0 ? max(20, tall) : nil, alignment: .top).clipped()
                    .padding(.horizontal, 3)
                if !ask.scope.isAll || person != nil { chips }
                HStack(alignment: .center, spacing: 8) {
                    scopeMenu
                    Spacer(minLength: 8)
                    if hotkey, !HotKey.keys(model.liveKey).isEmpty {
                        HStack(spacing: 3) { ForEach(HotKey.keys(model.liveKey), id: \.self) { KeyHint(key: $0) } }
                            .help("ask from anywhere").accessibilityLabel("ask from anywhere: " + HotKey.keys(model.liveKey).joined(separator: " "))
                            .probe("desk.key", .button, group: "chat.controls")
                    }
                    ModelMenu()
                    ModeSwitch(deep: $ask.deep).probe("chat.mode", .button, group: "chat.controls")
                    if ask.asking && empty {
                        Button { ask.stop() } label: { round("stop.fill", 9, on: true) }
                            .buttonStyle(.plain).help("stop  esc").accessibilityLabel("stop").ring(15)
                            .probe("chat.send", .button, group: "chat.controls")
                    } else {
                        Button { ask.send(model.engine); focused = true } label: { round("arrow.up", 12, on: !empty) }
                            .buttonStyle(.plain).disabled(empty).help(ask.asking ? "send next  return" : "send  return").accessibilityLabel("send").ring(15)
                            .probe("chat.send", .button, group: "chat.controls")
                    }
                }
                .frame(height: 28)
            }
            .padding(.horizontal, 12).padding(.top, 13).padding(.bottom, 10)
            .background(Ink.raised, in: shape)
            .overlay(shape.strokeBorder(focused ? Ink.ink.opacity(0.22) : Ink.ink.opacity(0.11), lineWidth: 1))
            .shadow(color: .black.opacity(Probe.on ? 0 : 0.05), radius: 12, y: 4)
            .contentShape(shape)
            .onTapGesture { focused = true }
            .probe("chat.input", .block, group: home ? "home.column" : "")
            .travels("ask.input", in: space)
            if !ask.notice.isEmpty {
                Text(ask.notice).font(.system(size: 12, weight: .medium)).foregroundStyle(Ink.soft).lineLimit(1)
                    .padding(.leading, 15)
                    .probe("chat.notice", .line)
                    .transition(.opacity)
            }
        }
        .animation(Motion.quick(reduce), value: ask.notice)
        .animation(Motion.quick(reduce), value: ask.asking)
        .animation(Motion.quick(reduce), value: ask.scope)
        .onAppear { if !Probe.on { focused = true } }
        .onChange(of: model.focusAsk) { _, _ in focused = true }
        .onChange(of: ask.currentID) { _, _ in focused = true; person = nil }
        .onChange(of: ask.draft) { _, _ in if !ask.notice.isEmpty, !ask.asking { ask.notice = "" } }
        .onChange(of: naming) { _, on in model.sideTyping = on }
    }

    private func round(_ symbol: String, _ size: CGFloat, on: Bool) -> some View {
        Image(systemName: symbol).font(.system(size: size, weight: .bold)).foregroundStyle(Ink.paper)
            .frame(width: 28, height: 28)
            .background(Ink.ink.opacity(on ? 1 : 0.28), in: Circle())
            .contentShape(Circle())
    }

    // MARK: scope

    /// "+": all sources, some of them, a stretch of time, a person.
    private var scopeMenu: some View {
        let ask = model.ask
        let read = model.engine.order.filter { model.engine.state($0).rows > 0 }.sorted { model.engine.state($0).rows > model.engine.state($1).rows }
        return Menu {
            Button("all sources") { ask.scope = Scope(); person = nil }.disabled(ask.scope.isAll)
            Menu("pick sources") {
                ForEach(read, id: \.self) { id in
                    Toggle(Catalog.info(id).name, isOn: Binding(get: { ask.scope.sources.contains(id) }, set: { on in
                        var s = ask.scope
                        if on { if !s.sources.contains(id) { s.sources.append(id) } } else { s.sources.removeAll { $0 == id } }
                        ask.scope = s
                    }))
                }
            }
            Menu("date range") {
                ForEach(Composer.ranges(), id: \.name) { r in
                    Button(r.name) { var s = ask.scope; s.after = r.after; s.before = r.before; ask.scope = s }
                }
                Divider()
                // any stretch of their own: a month to start from and a month to end with
                monthMenu("from…") { y, m in var s = ask.scope; s.after = Composer.month(y, m); if !s.before.isEmpty, s.before <= s.after { s.before = "" }; ask.scope = s }
                monthMenu("until the end of…") { y, m in var s = ask.scope; s.before = Composer.month(y, m + 1); if !s.after.isEmpty, s.after >= s.before { s.after = "" }; ask.scope = s }
                if !ask.scope.after.isEmpty || !ask.scope.before.isEmpty {
                    Divider()
                    Button("any time") { var s = ask.scope; s.after = ""; s.before = ""; ask.scope = s }
                }
            }
            Button("a person…") { person = ""; naming = true }
        } label: {
            Image(systemName: "plus").font(.system(size: 13, weight: .medium)).foregroundStyle(Ink.soft)
                .frame(width: 28, height: 28)
                .background(Ink.wash.opacity(0.9), in: Circle())
                .contentShape(Circle())
        }
        .menuStyle(.borderlessButton).menuIndicator(.hidden).fixedSize()
        .help("ask only part of your history: some sources, a stretch of time, a person")
        .accessibilityLabel("add scope").accessibilityHint("limit the question: sources, dates, a person")
        .probe("chat.scope", .button, group: "chat.controls")
    }

    /// A year, then a month of it: every year the archive reaches back to, newest first.
    private func monthMenu(_ title: String, pick: @escaping (Int, Int) -> Void) -> some View {
        let now = Calendar.current.dateComponents([.year, .month], from: Date())
        let thisYear = now.year ?? 2026
        let first = min(thisYear, model.engine.spans.values.compactMap { Words.parts($0.first)?.y }.min() ?? thisYear - 5)
        return Menu(title) {
            ForEach(Array(stride(from: thisYear, through: max(first, thisYear - 40), by: -1)), id: \.self) { y in
                Menu(String(y)) {
                    ForEach(1...(y == thisYear ? (now.month ?? 12) : 12), id: \.self) { m in
                        Button(Words.monthsLong[m - 1]) { pick(y, m) }
                    }
                }
            }
        }
    }

    /// The first day of a month as an iso day; month 13 is january of the next year.
    static func month(_ y: Int, _ m: Int) -> String { String(format: "%04d-%02d-01", m > 12 ? y + 1 : y, m > 12 ? 1 : m) }

    /// "mar 2024": the month a day falls in, or for an end that is the first of a month, the month before it.
    static func monthWord(_ iso: String, end: Bool) -> String? {
        guard let p = Words.parts(iso), p.d == 1 else { return nil }
        if !end { return "\(Words.months[p.m - 1]) \(p.y)" }
        return p.m == 1 ? "dec \(p.y - 1)" : "\(Words.months[p.m - 2]) \(p.y)"
    }

    /// The stretches of time on offer, as iso days.
    static func ranges(now: Date = Date()) -> [(name: String, after: String, before: String)] {
        let cal = Calendar.current
        func back(_ days: Int) -> String { Words.isoDay(cal.date(byAdding: .day, value: -days, to: now) ?? now) }
        let y = cal.component(.year, from: now)
        return [("last 7 days", back(7), ""), ("last 30 days", back(30), ""), ("last 12 months", back(365), ""),
                ("this year", "\(y)-01-01", ""), ("last year", "\(y - 1)-01-01", "\(y)-01-01"), ("before last year", "", "\(y - 1)-01-01")]
    }

    /// "since 13 nov", "2025", "before 2025"
    static func rangeWord(_ s: Scope) -> String {
        if let r = ranges().first(where: { $0.after == s.after && $0.before == s.before }) { return r.name }
        // a stretch picked by month reads in months: "mar 2024 to jun 2025", "since mar 2024", "until jun 2025"
        let a = monthWord(s.after, end: false), b = monthWord(s.before, end: true)
        if !s.after.isEmpty, !s.before.isEmpty {
            if let a, let b { return a == b ? a : "\(a) to \(b)" }
            return "\(Words.day(s.after)) to \(Words.day(s.before))"
        }
        if s.after.isEmpty { return b.map { "until \($0)" } ?? "before \(Words.day(s.before))" }
        return a.map { "since \($0)" } ?? "since \(Words.day(s.after))"
    }

    private var chips: some View {
        let ask = model.ask
        return Flow(spacing: 6, lineSpacing: 6) {
            ForEach(ask.scope.sources, id: \.self) { id in
                ScopeChip(icon: id, word: Catalog.info(id).name) { var s = ask.scope; s.sources.removeAll { $0 == id }; ask.scope = s }
            }
            if !ask.scope.after.isEmpty || !ask.scope.before.isEmpty {
                ScopeChip(symbol: "calendar", word: Composer.rangeWord(ask.scope)) { var s = ask.scope; s.after = ""; s.before = ""; ask.scope = s }
            }
            ForEach(ask.scope.people, id: \.self) { name in
                ScopeChip(symbol: "person", word: name) { var s = ask.scope; s.people.removeAll { $0 == name }; ask.scope = s }
            }
            if person != nil {
                HStack(spacing: 6) {
                    Image(systemName: "person").font(.system(size: 10, weight: .medium)).foregroundStyle(Ink.soft)
                    TextField("", text: Binding(get: { person ?? "" }, set: { person = $0 }), prompt: Text("a name, then return").foregroundStyle(Ink.soft))
                        .textFieldStyle(.plain).font(.system(size: 12, weight: .medium)).foregroundStyle(Ink.ink).tint(Ink.ember)
                        .focused($naming)
                        .frame(width: 130)
                        .onSubmit {
                            let name = (person ?? "").trimmingCharacters(in: .whitespaces)
                            if !name.isEmpty { var s = ask.scope; if !s.people.contains(name) { s.people.append(name) }; ask.scope = s }
                            person = nil
                            focused = true
                        }
                }
                .padding(.horizontal, 9).frame(height: 24)
                .background(Ink.wash, in: Capsule())
                .probe("chat.chip", .block, group: "chat.chips")
            }
        }
        .padding(.horizontal, 1)
    }
}

/// One narrowing of the question, with the way to take it off.
struct ScopeChip: View {
    var icon = ""
    var symbol = ""
    let word: String
    let remove: () -> Void
    @State private var hover = false

    var body: some View {
        HStack(spacing: 6) {
            if !icon.isEmpty { SourceIcon(id: icon, size: 13) } else { Image(systemName: symbol).font(.system(size: 10, weight: .medium)).foregroundStyle(Ink.soft) }
            Text(word).font(.system(size: 12, weight: .medium)).foregroundStyle(Ink.ink).lineLimit(1).fixedSize()
                .probe("chat.chip.word", .line)
            Button(action: remove) {
                Image(systemName: "xmark").font(.system(size: 7.5, weight: .bold)).foregroundStyle(hover ? Ink.ink : Ink.soft)
                    .frame(width: 14, height: 14).contentShape(Rectangle())
            }
            .buttonStyle(.plain).help("take it off").accessibilityLabel("remove \(word)")
        }
        .padding(.leading, 9).padding(.trailing, 5).frame(height: 24)
        .background(Ink.wash, in: Capsule())
        .onHover { hover = $0 }
        .probe("chat.chip", .block, group: "chat.chips")
    }
}

/// "quick · deep": how far the engine searches. Quick answers from the first search and digs only when the answer is
/// weak; deep digs from the start.
struct ModeSwitch: View {
    @Binding var deep: Bool
    var body: some View {
        HStack(spacing: 0) {
            word("quick", on: !deep) { deep = false }
            word("deep", on: deep) { deep = true }
        }
        .padding(2)
        .background(Ink.wash.opacity(0.9), in: Capsule())
        .help(deep ? "deep: searches several ways and reads whole threads before it answers. slower." : Answer.quickHelp(lookDeeper: AppModel.shared.saved.lookDeeper))
        .animation(.easeOut(duration: 0.12), value: deep)
    }

    private func word(_ w: String, on: Bool, _ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(w).font(.system(size: 12, weight: on ? .semibold : .medium)).foregroundStyle(on ? Ink.ink : Ink.soft)
                .lineLimit(1).fixedSize()
                .padding(.horizontal, 10).frame(height: 24)
                .background(on ? Ink.raised : .clear, in: Capsule())
                .contentShape(Capsule())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(w + " search").accessibilityAddTraits(on ? [.isSelected] : [])
        .ring(13, inset: 0)
    }
}
