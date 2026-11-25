import AppKit
import SwiftUI

// MARK: what the frame does

extension AppModel {
    /// The word in the middle of the title-bar row: the chat's title, or the page.
    var barTitle: String {
        switch tab {
        case .home: return ask.exact ? "exact words" : (ask.current?.title ?? "")
        case .plan: return "journal"
        case .sources: return "sources"
        case .settings: return "settings"
        case .profile: return "about you"
        case .teach: return "teach"
        case .made: return "made"
        }
    }

    /// The fold button and shift-cmd-S. They act on what the owner sees, not on the setting behind it: a sidebar that is
    /// folded only because the sources panel took its room, or because the window is narrow, is shown by this, and
    /// stays their choice. Only a sidebar that is showing is put away.
    func toggleSidebar() {
        let width = frameWidth
        let showing = sidebarShown(width: width, panel: panelShown(width: width))
        if showing {
            saved.sidebar = false
            sideOver = false
            chatSearch = nil; renaming = nil; sideTyping = false
        } else {
            saved.sidebar = true
            // no room beside the panel: the panel gives way
            if panelShown(width: width) > 0, width - Grid.sidebar - panelShown(width: width) < 420 { people.close(); ask.closePanel() }
            if width < Grid.narrow { sideOver = true }
        }
        persist()
    }

    /// Home, ready for a question that starts a new conversation.
    func newChat() {
        guard saved.onboarded else { return }
        dismissOverlays()
        tab = .home
        ask.newChat()
        // a new chat opens the way the owner asked for one to: their own mode, when the owner chose one
        if rules.prefs.mode == "deep" { ask.homeDeep = true } else if rules.prefs.mode == "quick" { ask.homeDeep = false }
        ask.query = ""
        chatSearch = nil
        focusAsk += 1
    }

    func go(_ to: Tab) {
        guard saved.onboarded else { return }
        dismissOverlays()           // also when the owner presses the page the owner is on
        tab = to
        if to == .home { focusAsk += 1 }
    }

    func openChat(_ id: String) {
        dismissOverlays()
        tab = .home
        ask.open(id)
        focusAsk += 1
    }

    /// cmd-K: the list of chats, with the cursor in its search field.
    func searchChats() {
        guard saved.onboarded else { return }
        if !saved.sidebar { saved.sidebar = true; persist() }
        dismissOverlays()
        // the list has to be seen to be searched: with no room beside the sources panel, the panel gives way
        let panel = panelShown(width: frameWidth)
        if panel > 0, frameWidth - Grid.sidebar - panel < 420 { ask.closePanel() }
        if chatSearch == nil { chatSearch = "" }
        focusSearch += 1
    }

    func endSearch() {
        chatSearch = nil
        sideTyping = false
        focusAsk += 1
    }

    /// cmd-[ and cmd-]: the chat above or below in the list.
    func stepChat(_ by: Int) {
        guard saved.onboarded else { return }
        tab = .home
        ask.step(by)
        focusAsk += 1
    }

    /// Whether the sidebar is drawn at this window width: the owner wants it, and there is room for it beside what is open.
    func sidebarShown(width: CGFloat, panel: CGFloat) -> Bool {
        guard saved.sidebar else { return false }
        if chatSearch != nil || sideOver, panel == 0 { return true }
        return width >= Grid.narrow && width - Grid.sidebar - panel >= 420
    }

    /// How wide the panel on the right is at this window width, or 0 when nothing is open in it.
    func panelShown(width: CGFloat) -> CGFloat {
        if tab == .teach || tab == .made { return 0 }
        if tab == .plan { return ask.thread != nil ? min(panelWidth, max(300, width - 420)) : 0 }     // a line of the journal, opened in its conversation
        if people.open != nil, tab == .home && !ask.exact || tab == .profile { return min(panelWidth, max(300, width - 420)) }
        // a paragraph of the wiki opened to what it rests on: the message in its conversation, or the conversation's card
        if tab == .profile, ask.thread != nil || wiki.card != nil { return min(panelWidth, max(300, width - 420)) }
        // a message unfolded from a margin note shows in the margin: it does not open the panel
        // ... while there is a margin: in a window too narrow for one it is in the panel, like any other
        let margin = ask.threadInMargin && width - (saved.sidebar && width >= Grid.narrow && !sideOver ? Grid.sidebar : 0) >= PageMeasure.least
        guard tab == .home, !ask.exact, ask.sourcesFor != nil || (ask.thread != nil && !margin) else { return 0 }
        return min(panelWidth, max(300, width - 420))
    }

    /// "123,456 things from 22 sources  ·  synced 4 min ago"
    var sourcesLine: String {
        let e = engine
        guard e.totalRows > 0 else { return "nothing read yet. open sources to start." }
        return "\(Words.count(e.totalRows)) things from \(e.readCount) source\(e.readCount == 1 ? "" : "s")" + (e.lastSync == nil ? "" : "  ·  synced \(Words.since(e.lastSync))")
    }

    /// The sources with the most in them, for the row of icons beside that line.
    var topSources: [String] {
        engine.order.filter { engine.state($0).rows > 0 }.sorted { engine.state($0).rows > engine.state($1).rows }.prefix(5).map { $0 }
    }

    /// How many things on the sources page wait on them.
    var waitingCount: Int { (shelf.first { $0.name == "waiting on you" }?.items.count ?? 0) + pending.count }
}

// MARK: the sidebar

/// A small arc that turns while something is being read.
struct Spinner: View {
    var size: CGFloat = 11
    @Environment(\.accessibilityReduceMotion) private var reduce
    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 30, paused: Probe.on || reduce)) { t in
            Circle().trim(from: 0.08, to: 0.78).stroke(Ink.soft, style: StrokeStyle(lineWidth: 1.6, lineCap: .round))
                .rotationEffect(.degrees(Probe.on || reduce ? 0 : t.date.timeIntervalSinceReferenceDate.truncatingRemainder(dividingBy: 0.9) / 0.9 * 360))
                .frame(width: size, height: size)
        }
        .accessibilityLabel("reading")
    }
}

/// The left of the window: the mark, a new chat, the search, every past chat by day, and at the foot the doors to
/// sources, about you, the journal and settings; and, only when it is in trouble, the plan the answers run on.
struct Sidebar: View {
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduce
    @Environment(\.controlActiveState) private var active
    @FocusState private var searching: Bool

    var body: some View {
        let ask = model.ask
        let sections = ask.sections(matching: model.chatSearch ?? "")
        VStack(alignment: .leading, spacing: 0) {
            // the row of the traffic lights: the mark after them, the fold at the far end
            HStack(alignment: .center, spacing: 0) {
                LogoMark(size: TopBar.mark, coloured: active != .inactive)
                    .opacity(active == .inactive ? 0.38 : 1)
                    .probe("bar.item", .block)
                Spacer(minLength: 8)
                BarButton(symbol: "sidebar.left", help: "hide the list of chats  ⇧⌘S", label: "hide sidebar") { model.toggleSidebar() }
                    .probe("bar.item", .block)
            }
            .padding(.leading, model.lights.x + 12).padding(.trailing, 10)
            .frame(height: model.lights.y * 2)

            VStack(spacing: 1) {
                SideAction(symbol: "square.and.pencil", word: "new chat", key: "⌘N", on: model.tab == .home && ask.currentID == nil && !ask.exact) { model.newChat() }
                if model.chatSearch != nil {
                    searchField
                } else {
                    SideAction(symbol: "magnifyingglass", word: "search chats", key: "⌘K", on: false) { model.searchChats() }
                }
            }
            .padding(.horizontal, 8).padding(.top, 2)

            ScrollView(showsIndicators: false) {
                VStack(alignment: .leading, spacing: 0) {
                    if sections.isEmpty {
                        Text(model.chatSearch?.isEmpty == false ? "no chat has those words." : "your chats will be listed here.")
                            .font(.system(size: 12)).foregroundStyle(Ink.soft)
                            .fixedSize(horizontal: false, vertical: true)
                            .padding(.horizontal, 10).padding(.top, 18)
                            .probe("side.empty", .text, scrolls: true)
                    }
                    ForEach(sections, id: \.name) { section in
                        Text(section.name).font(Face.heading).foregroundStyle(Ink.soft)
                            .lineLimit(1).fixedSize()
                            .padding(.leading, 10).padding(.top, 16).padding(.bottom, 5)
                            .probe("side.head", .line, scrolls: true)
                        ForEach(section.chats) { chat in
                            ChatRow(info: ChatRow.Info(id: chat.id, title: chat.title, pinned: chat.pinned, unread: chat.unread,
                                                       busy: ask.busy.contains(chat.id), selected: model.tab == .home && ask.currentID == chat.id,
                                                       first: chat.id == sections.first?.chats.first?.id))
                        }
                    }
                }
                .padding(.horizontal, 8).padding(.bottom, 12)
            }
            .frame(maxHeight: .infinity)

            Rectangle().fill(Ink.line).frame(height: 1)
            VStack(spacing: 1) {
                // three groups, a small gap between them: what is their (the journal the owner writes, the things made for them),
                // what context holds and how it treats it (about you, sources, teach), and settings
                SideAction(symbol: "text.alignleft", word: "journal", on: model.tab == .plan) { model.go(.plan) }
                    .help("a page a day: what you are doing and why, with what bears on it from your past in the margin")
                if model.made.shown {
                    SideAction(symbol: "doc.text", word: "made", detail: model.made.docs.isEmpty ? "" : "\(model.made.docs.count)", on: model.tab == .made) { model.made.open = nil; model.go(.made) }
                        .help("what context wrote for you out of your own history: posts, plans, briefs, tables")
                        .probe("side.made", .block)
                }
                Color.clear.frame(height: 7)
                SideAction(symbol: "person.text.rectangle", word: "about you", on: model.tab == .profile) { model.go(.profile) }
                    .help("what context knows about you")
                TimelineView(.periodic(from: .now, by: 20)) { t in
                    let doing = model.engine.doing(at: t.date)
                    // the count stands at its value and runs only from one real total to the next: it never climbs from nothing
                    SideAction(symbol: "tray.full", word: "sources", detail: doing ?? sourcesDetail, figure: doing == nil && model.engine.totalRows > 0 ? model.engine.totalRows : nil,
                               busy: doing != nil, on: model.tab == .sources) { model.go(.sources) }
                }
                if model.rules.shown {
                    SideAction(symbol: "scalemass", word: "teach", on: model.tab == .teach) { model.go(.teach) }
                        .help("tell context how to treat your data: what counts more, what to leave out, how to answer")
                        .probe("side.teach", .block)
                }
                Color.clear.frame(height: 7)
                SideAction(symbol: "gearshape", word: "settings", key: "⌘,", on: model.tab == .settings) { model.go(.settings) }
                // the plan the answers run on is said here only when something is wrong with it
                if let trouble = model.planTrouble { planWarning(trouble) }
            }
            .padding(.horizontal, 8).padding(.top, 8).padding(.bottom, 10)
        }
        .frame(width: Grid.sidebar)
        .frame(maxHeight: .infinity)
        .background(Ink.side.probe("side.ground", .block))
        .overlay(alignment: .trailing) { Rectangle().fill(Ink.line).frame(width: 1) }
        .onChange(of: model.focusSearch) { _, _ in searching = true }
        .onChange(of: searching) { _, on in model.sideTyping = on || model.renaming != nil }
        .onAppear { if model.chatSearch != nil, !Probe.on { searching = true } }
    }

    private var sourcesDetail: String {
        let e = model.engine
        guard e.totalRows > 0 else { return "nothing read" }
        return Words.count(e.totalRows)
    }

    private var searchField: some View {
        @Bindable var model = model
        return HStack(spacing: 8) {
            Image(systemName: "magnifyingglass").font(.system(size: 12, weight: .medium)).foregroundStyle(Ink.soft).frame(width: 18)
            TextField("", text: Binding(get: { model.chatSearch ?? "" }, set: { model.chatSearch = $0 }),
                      prompt: Text("search chats").foregroundStyle(Ink.soft))
                .textFieldStyle(.plain).font(.system(size: 13, weight: .medium)).foregroundStyle(Ink.ink).tint(Ink.ember)
                .focused($searching)
                .onSubmit {
                    if let first = model.ask.sections(matching: model.chatSearch ?? "").first?.chats.first { model.openChat(first.id); model.endSearch() }
                }
            Button { model.endSearch() } label: {
                Image(systemName: "xmark").font(.system(size: 9, weight: .bold)).foregroundStyle(Ink.soft).frame(width: 20, height: 20).contentShape(Rectangle())
            }
            .buttonStyle(.plain).help("esc").accessibilityLabel("close the search")
        }
        .padding(.leading, 10).padding(.trailing, 5).frame(height: 30)
        .background(Ink.paper, in: RoundedRectangle(cornerRadius: Radius.row, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: Radius.row, style: .continuous).strokeBorder(Ink.line, lineWidth: 1))
        .probe("side.search", .block, group: "side.top")
    }

    /// Trouble with the plan the answers run on: signed out, or at its limit. It opens settings at models.
    private func planWarning(_ trouble: String) -> some View {
        Button { model.openSettings(.models) } label: {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Circle().fill(Ink.ember).frame(width: 6, height: 6).frame(width: 18).offset(y: -1)
                Text(trouble).font(.system(size: 11, weight: .medium)).foregroundStyle(Ink.ink).lineSpacing(1)
                    .fixedSize(horizontal: false, vertical: true)
                    .probe("side.plan.word", .text)
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 10).padding(.vertical, 6).contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(trouble).accessibilityHint("opens settings, models")
        .ring(Radius.row, inset: 0)
        .help("answers run on your own ai plan. open settings to see what it needs.")
        .probe("side.plan", .block, group: "side.actions")
    }
}

/// One row of the sidebar that does something: a symbol, a word, and at the right a key or a quiet figure.
struct SideAction: View {
    let symbol: String
    let word: String
    var key = ""
    var detail = ""
    var figure: Int? = nil      // when the detail is a count: drawn as a figure that settles
    var busy = false
    let on: Bool
    let action: () -> Void
    @State private var hover = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: 8) {
                Image(systemName: symbol).font(.system(size: Face.small, weight: .regular)).foregroundStyle(on || hover ? Ink.ink : Ink.soft).frame(width: 18)
                Text(word).font(.system(size: Face.label, weight: on ? .medium : .regular)).foregroundStyle(Ink.ink).lineLimit(1).fixedSize()
                    .probe("side.word", .line)
                Spacer(minLength: 6)
                if busy { Spinner(size: 10) }
                if let figure {
                    Figure(target: figure).font(.system(size: Face.micro)).foregroundStyle(Ink.soft).lineLimit(1).fixedSize()
                } else if !detail.isEmpty {
                    Text(detail).font(.system(size: Face.micro)).monospacedDigit().foregroundStyle(Ink.soft).lineLimit(1).truncationMode(.tail)
                } else if !key.isEmpty, hover || Probe.on {
                    Text(key).font(.system(size: 11, weight: .medium)).foregroundStyle(Ink.soft).fixedSize()
                }
            }
            .padding(.horizontal, 10).frame(height: 30)
            .background(Ink.ink.opacity(on ? 0.075 : (hover ? 0.04 : 0)), in: RoundedRectangle(cornerRadius: Radius.row, style: .continuous))
            .contentShape(Rectangle())
        }
        .buttonStyle(Pressable())
        .onHover { hover = $0 }
        .accessibilityLabel(word + (detail.isEmpty ? "" : ", " + detail))
        .ring(Radius.row, inset: 0)
        .animation(Motion.hover, value: hover)
        .probe("side.action", .block, group: "side.actions")
    }
}

/// One chat in the list: its title; a spinner while it is being answered, then a dot until the owner has looked;
/// under the pointer, pin, rename and delete.
struct ChatRow: View {
    struct Info: Equatable {
        let id: String, title: String
        let pinned: Bool, unread: Bool, busy: Bool, selected: Bool, first: Bool
    }
    @Environment(AppModel.self) private var model
    let info: Info
    @State private var hover = false
    @State private var name = ""
    @FocusState private var naming: Bool

    var body: some View {
        let renaming = model.renaming == info.id
        let tools = (hover || Probe.on && info.first && !info.busy && !info.unread) && !renaming
        HStack(spacing: 4) {
            if renaming {
                TextField("", text: $name)
                    .textFieldStyle(.plain).font(.system(size: 13, weight: .medium)).foregroundStyle(Ink.ink).tint(Ink.ember)
                    .focused($naming)
                    .onSubmit { commit() }
                    .onAppear { name = info.title; naming = true }
                    .onChange(of: naming) { _, on in if !on, model.renaming == info.id { commit() } }
            } else {
                Text(info.title.isEmpty ? "new chat" : info.title)
                    .font(.system(size: Face.label, weight: info.selected ? .medium : .regular)).foregroundStyle(Ink.ink)
                    .lineLimit(1).truncationMode(.tail)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            if tools {
                HStack(spacing: 0) {
                    tool(info.pinned ? "pin.slash" : "pin", info.pinned ? "unpin" : "pin to the top") { model.ask.pin(info.id) }
                    tool("pencil", "rename") { model.renaming = info.id; model.sideTyping = true }
                    tool("trash", "delete. the file goes to the trash") { model.ask.delete(info.id) }
                }
                .probe("side.tools", .button, scrolls: true)
            } else if info.busy {
                Spinner(size: 10).frame(width: 16).probe("side.busy", .block, scrolls: true)
            } else if info.unread {
                Circle().fill(Ink.ember).frame(width: 6, height: 6).frame(width: 16)
                    .accessibilityLabel("unread")
                    .probe("side.unread", .block, scrolls: true)
            } else if info.pinned, !renaming {
                Image(systemName: "pin.fill").font(.system(size: 8.5, weight: .medium)).foregroundStyle(Ink.soft).frame(width: 16)
            }
        }
        .padding(.leading, 10).padding(.trailing, 5).frame(height: 30)
        .background(Ink.ink.opacity(info.selected ? 0.075 : (hover ? 0.04 : 0)), in: RoundedRectangle(cornerRadius: Radius.row, style: .continuous))
        .contentShape(Rectangle())
        .onTapGesture { if !renaming { model.openChat(info.id) } }
        .onHover { hover = $0 }
        .contextMenu {
            Button(info.pinned ? "Unpin" : "Pin") { model.ask.pin(info.id) }
            Button("Rename") { model.renaming = info.id; model.sideTyping = true }
            Button("Delete") { model.ask.delete(info.id) }
        }
        .help(info.title)
        // the list is walked with tab or the arrows' own keys (cmd-[ and cmd-]); return or space opens the chat the keyboard is on
        .focusable(!renaming)
        .onKeyPress(.return) { model.openChat(info.id); return .handled }
        .onKeyPress(.space) { model.openChat(info.id); return .handled }
        .ring(Radius.row, inset: 0)
        .accessibilityElement(children: .combine)
        .accessibilityLabel((info.title.isEmpty ? "new chat" : info.title) + (info.busy ? ", being answered" : "") + (info.unread ? ", unread" : "") + (info.pinned ? ", pinned" : ""))
        .accessibilityAddTraits(info.selected ? [.isButton, .isSelected] : .isButton)
        .accessibilityAction(named: info.pinned ? "unpin" : "pin") { model.ask.pin(info.id) }
        .accessibilityAction(named: "rename") { model.renaming = info.id; model.sideTyping = true }
        .accessibilityAction(named: "delete") { model.ask.delete(info.id) }
        .probe("side.row", .block, group: "side.rows", scrolls: true)
    }

    private func commit() {
        model.ask.rename(info.id, to: name)
        model.renaming = nil
        model.sideTyping = false
    }

    private func tool(_ symbol: String, _ help: String, _ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: symbol).font(.system(size: 10, weight: .medium)).foregroundStyle(Ink.soft)
                .frame(width: 22, height: 22).contentShape(Rectangle())
        }
        .buttonStyle(.plain).help(help).accessibilityLabel(help.components(separatedBy: ".").first ?? help)
    }
}
