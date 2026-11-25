import AppKit
import SwiftUI

extension AskModel {
    /// The panel on the right, for one answer: opens it, or closes it when it is already showing that answer's list.
    func toggleSources(_ turn: Int) {
        if sourcesFor == turn, thread == nil { sourcesFor = nil } else { closeThread(); sourcesFor = turn }
    }

    func closePanel() {
        closeThread()
        sourcesFor = nil
        flash = nil
    }
}

/// The right of the window, when an answer's sources are open: each row it rests on, with its icon; a click shows
/// the message in its conversation, here; under them, what might be related, to keep or drop. Esc closes it.
struct SourcesPanel: View {
    @Environment(AppModel.self) private var model
    let width: CGFloat
    @State private var dragFrom: CGFloat?
    @State private var overHandle = false

    var body: some View {
        let ask = model.ask
        let turn = ask.sourcesFor.flatMap { id in ask.turns.first { $0.id == id } }
        let answer = turn.flatMap { ($0.showFirst ? $0.first : nil) ?? $0.answer ?? $0.live?.partial(tag: "t\($0.id)") }
        let cites = answer?.cites ?? turn?.live?.cites ?? []
        let person = model.people.open
        let under = model.tab == .home && (ask.thread != nil || turn != nil)      // something to go back to under a person
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .center, spacing: 6) {
                if person != nil ? under : (ask.thread != nil && turn != nil) {
                    BarButton(symbol: "chevron.left", help: person != nil ? "back" : "back to the sources", size: 12) { if person != nil { model.people.close() } else { ask.closeThread() } }
                        .probe("bar.item", .block)
                }
                Text(person != nil ? "person" : (ask.thread != nil ? "in its conversation" : (model.tab == .profile && model.wiki.card != nil ? "conversation" : "sources  ·  \(cites.count)")))
                    .font(.system(size: 13, weight: .semibold)).foregroundStyle(Ink.ink).lineLimit(1).fixedSize()
                    .probe("refs.title", .line)
                    .offset(y: -TopBar.rise(TopBar.tabFont))
                Spacer(minLength: 8)
                BarButton(symbol: "xmark", help: "close  esc", size: 11) { model.people.close(); ask.closePanel(); model.wiki.card = nil }
                    .probe("bar.item", .block)
            }
            .padding(.leading, (person != nil ? under : (ask.thread != nil && turn != nil)) ? 8 : 16).padding(.trailing, 10)
            .frame(height: model.lights.y * 2)
            Rectangle().fill(Ink.line).frame(height: 1)
            if let person {
                PersonPane(page: person)
            } else if let peek = ask.thread {
                GeometryReader { geo in
                    ThreadCard(peek: peek, maxHeight: max(120, geo.size.height - 84), flat: true)
                }
            } else if model.tab == .profile, let card = model.wiki.card {
                WikiCardPane(card: card)
            } else if let turn, let answer {
                ScrollView {
                    VStack(alignment: .leading, spacing: 0) {
                        ForEach(Array(cites.enumerated()), id: \.element.id) { i, hit in
                            RefRow(number: i + 1, hit: hit, turn: turn)
                        }
                        if cites.isEmpty {
                            Text("this answer rests on no rows.").font(.system(size: 13)).foregroundStyle(Ink.soft)
                                .padding(.horizontal, 16).padding(.vertical, 14)
                        }
                        if !answer.maybe.isEmpty {
                            head("might be related  ·  \(answer.maybe.count)")
                            ForEach(answer.maybe) { hit in MaybeRow(hit: hit, turn: turn) }
                        }
                        if !answer.searched.isEmpty || answer.found > 0 {
                            head("how it searched")
                            HowText(answer: answer).padding(.horizontal, 16).padding(.top, 2)
                        }
                    }
                    .padding(.bottom, 20)
                }
            } else {
                Spacer(minLength: 0)
            }
        }
        .frame(width: width)
        .frame(maxHeight: .infinity, alignment: .top)
        .background(Ink.raised)
        .overlay(alignment: .leading) { Rectangle().fill(Ink.line).frame(width: 1) }
        // the left edge drags: the panel is as wide as the owner wants it, within reason
        .overlay(alignment: .leading) {
            Color.clear.frame(width: 8).contentShape(Rectangle())
                .onHover { on in
                    if on, !overHandle { NSCursor.resizeLeftRight.push(); overHandle = true } else if !on, overHandle { NSCursor.pop(); overHandle = false }
                }
                .gesture(DragGesture(minimumDistance: 1, coordinateSpace: .global)
                    .onChanged { g in
                        let from = dragFrom ?? model.panelWidth
                        dragFrom = from
                        model.panelWidth = min(560, max(300, from - g.translation.width))
                    }
                    .onEnded { _ in dragFrom = nil })
                .offset(x: -4)
        }
        .probe("refs.panel", .block)
    }

    private func head(_ text: String) -> some View {
        Text(text).font(.system(size: 11, weight: .semibold)).foregroundStyle(Ink.soft).lineLimit(1).fixedSize()
            .padding(.leading, 16).padding(.top, 22).padding(.bottom, 6)
            .probe("refs.head", .line, scrolls: true)
    }
}

/// A source's number, as it stands in the answer.
struct RefNumber: View {
    let number: Int
    var lit = false
    var body: some View {
        Text("\(number)")
            .font(.system(size: 9.5, weight: .bold, design: .rounded)).monospacedDigit()
            .foregroundStyle(lit ? Ink.paper : Ink.soft)
            .frame(width: Chip.width(number), height: 14)
            .background(lit ? Ink.ink : Ink.wash, in: RoundedRectangle(cornerRadius: Radius.chip, style: .continuous))
    }
}

/// One row an answer rests on: its number, where it came from, a few lines of it, the day. A click shows it in its conversation.
struct RefRow: View {
    @Environment(AppModel.self) private var model
    let number: Int
    let hit: Hit
    let turn: Turn
    @State private var hover = false

    var body: some View {
        let lit = model.ask.flash == hit.id
        HStack(alignment: .top, spacing: 10) {
            RefNumber(number: number, lit: lit).padding(.top, 2)
            SourceIcon(id: hit.src, size: 18)
            VStack(alignment: .leading, spacing: 4) {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text(Cite.title(hit)).font(.system(size: 13, weight: .semibold)).foregroundStyle(Ink.ink).lineLimit(1).truncationMode(.tail)
                    Spacer(minLength: 4)
                    Text(Words.day(hit.ts)).font(.system(size: 11, weight: .medium)).monospacedDigit().foregroundStyle(Ink.faint).lineLimit(1).fixedSize()
                        .probe("refs.date", .line, scrolls: true)
                }
                Text(hit.snippet).font(.system(size: 12)).lineSpacing(2.5).foregroundStyle(Ink.soft)
                    .lineLimit(3).fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: .infinity, alignment: .leading)
                HStack(spacing: 12) {
                    if let name = Cite.from(hit) {
                        HStack(spacing: 0) {
                            Text("from ").foregroundStyle(Ink.faint)
                            Button((model.people.resolve(name) ?? name).lowercased()) { model.showPerson(model.people.resolve(name) ?? name) }
                                .buttonStyle(.plain).foregroundStyle(Ink.soft).underline(true, pattern: .dot, color: Ink.faint)
                                .help("open \(name)")
                                .accessibilityLabel("from \(name)").accessibilityHint("opens this person")
                                .probe("refs.from", .line, scrolls: true)
                            Text("  ·  " + Catalog.info(hit.src).name).foregroundStyle(Ink.faint)
                        }
                        .font(.system(size: 11, weight: .medium)).lineLimit(1)
                    } else {
                        Text(Cite.by(hit)).font(.system(size: 11, weight: .medium)).foregroundStyle(Ink.faint).lineLimit(1)
                    }
                    Spacer(minLength: 4)
                    if let url = Cite.link(hit) {
                        Button("open") { if !Probe.on { NSWorkspace.shared.open(url) } }.buttonStyle(QuietButton(size: 11)).help(hit.url)
                            .probe("refs.open", .button, scrolls: true)
                    }
                }
            }
        }
        .padding(.horizontal, 16).padding(.vertical, 11)
        .background(lit ? Ink.wash : (hover ? Ink.wash.opacity(0.5) : .clear))
        .overlay(alignment: .bottom) { Rectangle().fill(Ink.line).frame(height: 1).padding(.leading, 16) }
        .contentShape(Rectangle())
        .onTapGesture { model.ask.peekThread(hit, turn: turn.id, model.engine) }
        .onHover { hover = $0 }
        .focusable()
        .onKeyPress(.return) { model.ask.peekThread(hit, turn: turn.id, model.engine); return .handled }
        .onKeyPress(.space) { model.ask.peekThread(hit, turn: turn.id, model.engine); return .handled }
        .ring(6, inset: -3)
        .accessibilityElement(children: .contain)
        .accessibilityLabel("source \(number), \(Cite.title(hit)), \(Words.day(hit.ts))")
        .accessibilityAddTraits(.isButton)
        .accessibilityHint("shows the message in its conversation")
        .animation(.easeOut(duration: 0.14), value: hover)
        .animation(.easeOut(duration: 0.3), value: lit)
        .teachMenu(thread: Cite.title(hit))
        .probe("refs.row", .block, group: "refs.rows", scrolls: true)
    }
}

/// A row related by meaning that the answer does not rest on: the owner says whether it belongs, once.
struct MaybeRow: View {
    @Environment(AppModel.self) private var model
    let hit: Hit
    let turn: Turn

    var body: some View {
        let said = model.ask.judged[hit.id]
        HStack(alignment: .top, spacing: 10) {
            SourceIcon(id: hit.src, size: 18)
            VStack(alignment: .leading, spacing: 4) {
                Text(Cite.title(hit) + "  ·  " + Words.ago(hit.ts)).font(.system(size: 12, weight: .semibold)).foregroundStyle(Ink.ink)
                    .lineLimit(1).truncationMode(.tail)
                Text(hit.snippet).font(.system(size: 12)).lineSpacing(2.5).foregroundStyle(Ink.soft)
                    .lineLimit(3).fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: .infinity, alignment: .leading)
                HStack(spacing: 14) {
                    if let said {
                        Text(said ? "kept" : "dropped").font(.system(size: 11, weight: .medium)).foregroundStyle(Ink.faint).fixedSize()
                            .probe("refs.said", .line, scrolls: true)
                    } else {
                        Button("yes, relevant") { model.ask.judge(hit, yes: true, question: turn.q, model.engine) }.buttonStyle(QuietButton(size: 11))
                            .probe("refs.yes", .button, scrolls: true)
                        Button("not this") { model.ask.judge(hit, yes: false, question: turn.q, model.engine) }.buttonStyle(QuietButton(size: 11))
                    }
                    Spacer(minLength: 0)
                }
                .frame(height: 18)
            }
        }
        .padding(.horizontal, 16).padding(.vertical, 10)
        .overlay(alignment: .bottom) { Rectangle().fill(Ink.line).frame(height: 1).padding(.leading, 16) }
        .probe("refs.maybe", .block, group: "refs.maybes", scrolls: true)
    }
}
