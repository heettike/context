import AppKit
import Carbon.HIToolbox
import SwiftUI

/// The panel: one key from anywhere opens a field over whatever the owner is doing. The window is the library; this is the product.
/// A tray in one width whose height follows its state: the field, then the answer. Nothing is looked up while the owner types.

// MARK: the key

/// A system-wide key, registered with Carbon. It needs no permission from macos.
final class HotKey {
    /// In the order they are tried. Option-space is last: the claude and chatgpt apps, and raycast, usually hold it.
    static let choices: [(id: String, word: String, keys: [String], mods: Int)] = [
        ("control-option", "control option space", ["⌃", "⌥", "space"], controlKey | optionKey),
        ("command-shift", "command shift space", ["⌘", "⇧", "space"], cmdKey | shiftKey),
        ("control-shift", "control shift space", ["⌃", "⇧", "space"], controlKey | shiftKey),
        ("option", "option space", ["⌥", "space"], optionKey),
        ("off", "off", [], 0),
    ]
    static func word(_ id: String) -> String { choices.first { $0.id == id }?.word ?? "off" }
    static func keys(_ id: String) -> [String] { choices.first { $0.id == id }?.keys ?? [] }
    /// "⌃⌥space", for a line of text.
    static func glyphs(_ id: String) -> String { keys(id).joined() }

    private static var fire: (() -> Void)?
    private static var handler: EventHandlerRef?
    private static var ref: EventHotKeyRef?
    /// The key that is really registered now: the one asked for, or the next one macos would give us. "off" when none.
    private(set) static var live = "off"

    /// Registers the wanted key. If macos refuses it, the next in the list is tried, and `live` says which one took:
    /// the app then says so in plain words, and never takes a key without saying.
    static func set(_ want: String, _ action: @escaping () -> Void) {
        fire = action
        if let ref { UnregisterEventHotKey(ref) }
        ref = nil
        live = "off"
        guard want != "off", !Engine.debug else { return }
        if handler == nil {
            var spec = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
            InstallEventHandler(GetApplicationEventTarget(), { _, _, _ in
                DispatchQueue.main.async { HotKey.fire?() }
                return noErr
            }, 1, &spec, nil, &handler)
        }
        let real = choices.filter { $0.mods != 0 }
        let order = real.filter { $0.id == want } + real.filter { $0.id != want }
        for c in order {
            let hid = EventHotKeyID(signature: OSType(0x63747870), id: 1)      // 'ctxp'
            if RegisterEventHotKey(UInt32(kVK_Space), UInt32(c.mods), hid, GetApplicationEventTarget(), 0, &ref) == noErr {
                live = c.id
                return
            }
            ref = nil
        }
    }
}

// MARK: state

@Observable final class PanelModel {
    enum Stage: Equatable { case empty, typing, asked, answered }

    var text = "" { didSet { if text != oldValue { typed() } } }
    var cite: Int?                 // the cited row the arrow keys are on, under an answer
    var pick: Int?                 // the earlier question the arrow keys are on, before the owner has typed
    var turnID: Int?               // the question this panel is showing, in the app's conversation
    var shown = false              // drives the arrival and the leaving
    var focus = 0
    var stale = false              // an answer from a moment ago is showing: the next letter starts a new question
    var closedAt = Date.distantPast

    func stage(_ ask: AskModel) -> Stage {
        if let turnID, let t = ask.turns.first(where: { $0.id == turnID }) { return t.answer == nil ? .asked : .answered }
        return text.trimmingCharacters(in: .whitespaces).isEmpty ? .empty : .typing
    }

    func turn(_ ask: AskModel) -> Turn? { turnID.flatMap { id in ask.turns.first { $0.id == id } } }

    /// Typing looks nothing up. It only puts away an answer that was showing.
    private func typed() {
        if turnID != nil { turnID = nil }
        stale = false
        pick = nil
        cite = nil
    }

    func move(_ by: Int, of count: Int) {
        guard count > 0 else { return }
        let next = (pick ?? -1) + by
        pick = next < 0 ? nil : min(next, count - 1)
    }

    func reset() {
        text = ""
        pick = nil
        turnID = nil
        stale = false
    }
}

// MARK: the window

/// A panel that takes keys without bringing the app forward, so the app the owner was in stays the app the owner is in.
final class AskPanel: NSPanel {
    var onEscape: () -> Void = {}
    var onResign: () -> Void = {}
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }
    override func cancelOperation(_ sender: Any?) { onEscape() }
    override func resignKey() { super.resignKey(); onResign() }
}

final class PanelController {
    static let width: CGFloat = 680, margin: CGFloat = 60, top: CGFloat = 24
    let model: AppModel
    let panel: AskPanel
    let state = PanelModel()
    private var monitor: Any?
    private let showWindow: () -> Void

    init(model: AppModel, showWindow: @escaping () -> Void) {
        self.model = model
        self.showWindow = showWindow
        panel = AskPanel(contentRect: NSRect(x: 0, y: 0, width: PanelController.width + PanelController.margin * 2, height: 600),
                         styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        panel.level = .modalPanel
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = false                    // the tray draws its own, so the shadow follows the spring
        panel.hidesOnDeactivate = false
        panel.isReleasedWhenClosed = false
        panel.isMovable = false
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .transient]
        panel.animationBehavior = .none
        panel.onEscape = { [weak self] in self?.back() }
        panel.onResign = { [weak self] in self?.hide() }
        panel.contentView = NSHostingView(rootView: PanelStage(panel: state, act: { [weak self] in self?.act(window: false) },
                                                               dismiss: { [weak self] in self?.hide() })
            .environment(model))
        monitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] e in
            guard let self, e.window === self.panel else { return e }
            if self.model.ask.thread != nil { return self.model.ask.threadKey(e, self.model.engine, modal: true) ? nil : e }
            return self.key(e) ? nil : e
        }
    }

    var isShown: Bool { panel.isVisible && state.shown }

    func toggle() { if isShown { hide() } else { show() } }

    /// Always the same place: on the screen the pointer is on, the field a little above the middle.
    func show() {
        guard model.saved.onboarded else { showWindow(); return }
        let mouse = NSEvent.mouseLocation
        let screen = NSScreen.screens.first { $0.frame.contains(mouse) } ?? NSScreen.main
        guard let v = screen?.visibleFrame else { return }
        // an answer from the last minute and a half is still there; older than that, the owner starts clean
        if Date().timeIntervalSince(state.closedAt) > 90 { state.reset() } else if state.turnID != nil { state.stale = true }
        let h = max(420, (v.height * 0.62).rounded()) + PanelController.top + PanelController.margin
        let w = PanelController.width + PanelController.margin * 2
        let trayTop = v.maxY - (v.height * 0.22).rounded()
        panel.setFrame(NSRect(x: (v.midX - w / 2).rounded(), y: trayTop + PanelController.top - h, width: w, height: h), display: true)
        model.pinger.seen()
        panel.makeKeyAndOrderFront(nil)
        state.focus += 1
        withAnimation(Motion.enter) { state.shown = true }
    }

    func hide() {
        guard state.shown else { return }
        state.closedAt = Date()
        withAnimation(Motion.exit) { state.shown = false }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { [weak self] in
            guard let self, !self.state.shown else { return }
            self.panel.orderOut(nil)
        }
    }

    /// Esc steps back one state, and from the empty field it leaves.
    func back() {
        if state.cite != nil { state.cite = nil; model.ask.flash = nil; return }
        switch state.stage(model.ask) {
        case .empty: if state.pick != nil { state.pick = nil } else { hide() }
        case .typing: state.text = ""
        case .asked: model.ask.stop(); state.turnID = nil
        case .answered: state.turnID = nil; state.stale = false
        }
    }

    /// Return: open the match the arrows are on, or ask. With command held, carry on in the window.
    func act(window: Bool) {
        let ask = model.ask
        let stage = state.stage(ask)
        if window, stage == .asked || stage == .answered {
            hide()
            model.tab = .home
            showWindow()
            return
        }
        // before the owner has typed: an earlier question, picked with the arrows, comes back with its answer
        if stage == .empty, let i = state.pick, ask.recent.indices.contains(i) {
            let t = ask.recent[i]
            ask.reopen(t.id)
            state.text = t.q
            state.turnID = t.id
            state.pick = nil
            if window { hide(); model.tab = .home; showWindow() }
            return
        }
        guard stage == .typing else { return }
        ask.ask(model.engine, state.text)
        state.turnID = ask.turns.last?.id
        if window { hide(); model.tab = .home; showWindow() }
    }

    private func key(_ e: NSEvent) -> Bool {
        let cmd = e.modifierFlags.contains(.command)
        switch Int(e.keyCode) {
        case kVK_Escape: back(); return true
        case kVK_DownArrow where state.stage(model.ask) == .answered, kVK_UpArrow where state.stage(model.ask) == .answered:
            // the arrows walk the rows the answer cites; return or space opens the one they are on
            guard let cites = state.turn(model.ask)?.answer?.cites, !cites.isEmpty else { return false }
            let next = (state.cite ?? -1) + (Int(e.keyCode) == kVK_DownArrow ? 1 : -1)
            state.cite = next < 0 ? nil : min(next, cites.count - 1)
            model.ask.flash = state.cite.map { cites[$0].id }
            return true
        case kVK_Space where state.cite != nil, kVK_Return where state.cite != nil && !cmd:
            if let t = state.turn(model.ask), let c = state.cite, let cites = t.answer?.cites, cites.indices.contains(c) {
                model.ask.peekThread(cites[c], turn: t.id, model.engine)
            }
            return true
        case kVK_DownArrow: guard state.stage(model.ask) == .empty else { return false }; state.move(1, of: min(3, model.ask.recent.count)); return true
        case kVK_UpArrow: guard state.stage(model.ask) == .empty else { return false }; state.move(-1, of: min(3, model.ask.recent.count)); return true
        case kVK_Return, kVK_ANSI_KeypadEnter: act(window: cmd); return true
        default:
            // an answer the owner came back to: the first letter the owner types begins the next question
            if state.stale, !cmd, let c = e.characters, c.unicodeScalars.contains(where: { $0.value >= 32 && $0.value != 127 }) {
                state.text = ""
            }
            return false
        }
    }
}

// MARK: views

/// The material behind the tray: the desktop shows through, blurred. A render draws plain paper, since blur does not draw unseen.
struct Glass: NSViewRepresentable {
    func makeNSView(context: Context) -> NSVisualEffectView {
        let v = NSVisualEffectView()
        v.material = .popover
        v.blendingMode = .behindWindow
        v.state = .active
        return v
    }
    func updateNSView(_ v: NSVisualEffectView, context: Context) {}
}

/// The whole of the panel's see-through window: the tray at the top, and clear space the tray grows into.
struct PanelStage: View {
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduce
    @Bindable var panel: PanelModel
    let act: () -> Void
    let dismiss: () -> Void

    var body: some View {
        VStack(spacing: 0) {
            PanelTray(panel: panel, act: act)
                .scaleEffect(panel.shown || reduce ? 1 : 0.98, anchor: .top)
                .opacity(panel.shown ? 1 : 0)
            Spacer(minLength: 0)
        }
        .padding(.top, PanelController.top).padding(.horizontal, PanelController.margin).padding(.bottom, PanelController.margin)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .background { Color.clear.contentShape(Rectangle()).onTapGesture(perform: dismiss) }
    }
}

struct PanelTray: View {
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduce
    @Environment(\.colorScheme) private var scheme
    @Bindable var panel: PanelModel
    let act: () -> Void
    @FocusState private var focused: Bool
    static let radius: CGFloat = Radius.field

    var body: some View {
        let stage = panel.stage(model.ask)
        let shape = RoundedRectangle(cornerRadius: PanelTray.radius, style: .continuous)
        VStack(alignment: .leading, spacing: 0) {
            field(stage)
            switch stage {
            case .empty:
                // this morning's card, as one line, until it has been read
                if let c = model.card, c.state == "unread" {
                    rule
                    HStack(alignment: .firstTextBaseline, spacing: 10) {
                        RoundedRectangle(cornerRadius: 1).fill(Ink.ember).frame(width: 2, height: 12)
                        Text(c.line).font(.system(size: 14, weight: .regular, design: .serif)).foregroundStyle(Ink.soft).lineLimit(2)
                            .fixedSize(horizontal: false, vertical: true)
                            .probe("panel.card", .text)
                    }
                    .padding(.horizontal, 22).padding(.vertical, 12)
                }
                if !earlier.isEmpty { rule; recent.transition(.opacity) }
            case .typing: EmptyView()
            case .asked:
                rule
                if let t = panel.turn(model.ask) {
                    // the steps it is taking, then the words as they are written
                    if let part = t.live?.partial(tag: "t\(t.id)") { answer(t, part, done: false) }
                    else { Waiting(turn: t).padding(.horizontal, 22).padding(.vertical, 12).frame(minHeight: 44).transition(.opacity) }
                }
            case .answered:
                rule
                // a cited row opened in its conversation takes the answer's place, and esc gives the answer back
                if let peek = model.ask.thread, peek.turn == panel.turnID { ThreadCard(peek: peek, maxHeight: 360, flat: true).transition(.opacity) }
                else if let t = panel.turn(model.ask), let a = t.answer { answer(t, a, done: true) }
            }
            if model.ask.thread == nil || stage != .answered { rule; footer(stage) }
        }
        .frame(width: PanelController.width, alignment: .leading)
        .background {
            if Probe.on { Ink.paper } else { ZStack { Glass(); Ink.paper.opacity(0.72) } }
        }
        .clipShape(shape)
        // the edge of a floating thing: a hairline all round, and light caught along the top
        .overlay { shape.strokeBorder(scheme == .dark ? Color.white.opacity(0.14) : Color.black.opacity(0.10), lineWidth: 0.5) }
        .overlay(alignment: .top) {
            shape.strokeBorder(LinearGradient(colors: [.white.opacity(scheme == .dark ? 0.22 : 0.6), .clear], startPoint: .top, endPoint: .center), lineWidth: 0.5)
                .frame(height: 40).allowsHitTesting(false)
        }
        .shadow(color: .black.opacity(Probe.on ? 0 : (scheme == .dark ? 0.5 : 0.28)), radius: 28, y: 18)
        .contentShape(shape)
        .onTapGesture {}                            // a click on the tray is not a click outside it
        .animation(Motion.tray(reduce), value: stage)
        .animation(Motion.tray(reduce), value: model.ask.thread?.hit.id)
        .animation(Motion.tray(reduce), value: (panel.turn(model.ask)?.live?.text.count ?? 0) / 48)
        .probe("panel.tray", .block)
    }

    private var rule: some View { Rectangle().fill(Ink.ink.opacity(0.08)).frame(height: 1) }

    private func field(_ stage: PanelModel.Stage) -> some View {
        HStack(alignment: .center, spacing: 14) {
            LogoMark(size: 18)
            // one line while the owner types; a long question wraps instead of running out of sight
            TextField("", text: $panel.text, prompt: Text("ask your own history").foregroundStyle(Ink.faint), axis: .vertical)
                .textFieldStyle(.plain)
                .font(.system(size: 22, weight: .regular)).tracking(-0.3)
                .foregroundStyle(Ink.ink)
                .tint(Ink.ember)
                .focused($focused)
                .lineLimit(1...3)
                .probe("panel.field", .text)
        }
        .padding(.horizontal, 22).padding(.vertical, 18)
        .frame(minHeight: 64)
        .onChange(of: panel.focus, initial: true) { focused = true }
    }

    private var earlier: [Turn] { Array(model.ask.recent.prefix(3)) }

    /// Before the owner types: the last few things the owner asked. The arrows walk them; return brings one back with its answer.
    private var recent: some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(Array(earlier.enumerated()), id: \.element.id) { i, t in
                let on = panel.pick == i
                HStack(alignment: .center, spacing: 12) {
                    Text(t.q).font(.system(size: 14)).foregroundStyle(on ? Ink.ink : Ink.soft).lineLimit(1).truncationMode(.tail)
                    Spacer(minLength: 8)
                    Text(Words.since(t.at)).font(.system(size: Face.small)).monospacedDigit().foregroundStyle(Ink.faint)
                        .lineLimit(1).fixedSize()
                        .probe("panel.when", .line)
                }
                .padding(.horizontal, 22)
                .frame(height: 36)
                .background(on ? Ink.ink.opacity(0.07) : .clear)
                .overlay(alignment: .leading) { if on { Rectangle().fill(Ink.ember).frame(width: 2) } }
                .contentShape(Rectangle())
                .onTapGesture { panel.pick = i; act() }
                .probe("panel.row", .block, group: "panel.rows")
            }
        }
        .padding(.vertical, 6)
    }

    /// The answer, as the chat sets it, with the room it needs and no more: past six tenths of the screen it scrolls.
    private func answer(_ t: Turn, _ a: Answer, done: Bool) -> some View {
        let cap = max(300, (NSScreen.main?.visibleFrame.height ?? 900) * 0.62 - 64 - 40)
        return ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                if a.text.isEmpty {
                    Failure(turn: t, sentence: a.error)
                } else {
                    // the page in small: the days it rests on, the answer, and its evidence as notes under it
                    if !a.cites.isEmpty { Ribbon(turn: t.id, cites: a.cites, live: !done).padding(.bottom, 12) }
                    AnswerText(turn: t, answer: a)
                    if !done {
                        WritingEdge(since: t.at).padding(.top, 12)
                    } else {
                        if a.stopped { Aside(text: "stopped before it finished.").padding(.top, 10) }
                        else if a.strength == "weak" { Aside(text: "not sure this is what you meant.").padding(.top, 10) }
                        if !a.links.isEmpty { LinkList(turn: t, links: a.links).padding(.top, 14) }
                        PanelNotes(turn: t, answer: a).padding(.top, 14)
                    }
                }
            }
            .padding(.horizontal, 22).padding(.vertical, 18)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .frame(maxHeight: Probe.on ? 360 : cap)
        .fixedSize(horizontal: false, vertical: true)
    }

    private func footer(_ stage: PanelModel.Stage) -> some View {
        HStack(spacing: 16) {
            switch stage {
            case .typing:
                hint(["↵"], "ask")
                hint(["⌘", "↵"], "ask in the window")
            case .asked:
                hint(["esc"], "stop")
                hint(["⌘", "↵"], "carry on in the window")
            case .answered:
                if panel.cite != nil { hint(["space"], "see it in its conversation") } else if panel.turn(model.ask)?.answer?.cites.isEmpty == false { hint(["↑", "↓"], "sources") }
                hint(["⌘", "↵"], "carry on in the window")
                hint(["esc"], "back")
            case .empty:
                if panel.pick != nil { hint(["↵"], "open") } else if !earlier.isEmpty { hint(["↑", "↓"], "earlier questions") } else { hint(["↵"], "ask") }
            }
            Spacer(minLength: 8)
            // the key that brought them here, so the owner learns it
            if !HotKey.keys(model.liveKey).isEmpty { hint(HotKey.keys(model.liveKey), "anywhere") }
        }
        .padding(.horizontal, 22)
        .frame(height: 36)
    }

    private func hint(_ keys: [String], _ word: String) -> some View {
        HStack(spacing: 5) {
            ForEach(keys, id: \.self) { KeyHint(key: $0) }
            Text(word).font(.system(size: Face.small)).foregroundStyle(Ink.soft).lineLimit(1).fixedSize()
                .probe("panel.hint", .line)
        }
    }
}

/// The panel drawn inside the test window, on plain paper, so the layout gate can measure its states.
struct PanelProof: View {
    @Environment(AppModel.self) private var model
    var body: some View {
        if let p = model.panelProof {
            VStack(spacing: 0) {
                PanelTray(panel: p, act: {}).padding(.top, 40)
                Spacer(minLength: 0)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(Ink.wash)
        }
    }
}

extension LayoutTest {
    /// The panel's states, with made-up rows, drawn inside the test window.
    static func panelScreens(_ m: AppModel, main: @escaping (Tab) -> Void) -> [(String, () -> Void)] {
        func panel(_ text: String, _ more: (PanelModel) -> Void = { _ in }) {
            main(.home)
            m.ask.wipe()
            m.ask.thread = nil
            m.ask.openSources = []
            m.ask.openHow = []
            let p = PanelModel()
            p.shown = true
            p.text = text
            more(p)
            m.panelProof = p
        }
        return [
            ("panel-empty", { panel("") }),
            ("panel-card", { panel("") { _ in
                m.ask.seed([turns(2)])
                m.card = Card(["id": "c", "kind": "promised", "line": "You told Sam you would come back to him about the lease after checking with the others. That was sixteen days ago, and the renewal is due on the first.", "action": ["label": "open"]])
            } }),
            ("panel-recent", { panel("") { p in m.ask.seed([turns(3)]); p.pick = 1 } }),
            ("panel-typing", { panel("the lease renewal") }),
            ("panel-typing-long", { panel(question) }),
            ("panel-asked", { panel(question) { p in m.ask.turns = [Turn(id: 0, q: question)]; m.ask.asking = true; p.turnID = 0 } }),
            ("panel-reading", { panel(question) { p in
                var t = Turn(id: 0, q: question)
                t.live = Live(phase: "read", rows: 250, sources: ["whatsapp", "email", "apple_notes"], threads: ["Sam (landlord)", longName])
                m.ask.turns = [t]; m.ask.asking = true; p.turnID = 0
            } }),
            ("panel-writing", { panel(question) { p in
                var t = Turn(id: 0, q: question)
                t.live = Live(phase: "read", rows: 250, sources: ["whatsapp"], text: "Not yet. Sam asked about the renewal twice [1] and you have not written back. He first raised it on the fourth",
                              cites: [Answer.cite(cite(1, "sam (landlord)", "the lease renewal is due on the first"), 0, prefix: "t0")!])
                m.ask.turns = [t]; m.ask.asking = true; p.turnID = 0
            } }),
            ("panel-answered", { panel(question) { p in m.ask.turns = turns(1); p.turnID = 0 } }),
            ("panel-thread", { panel(question) { p in m.ask.turns = turns(1); p.turnID = 0; m.ask.thread = threadProof(m.ask.turns[0]) } }),
            ("panel-failed", { panel(question) { p in
                m.ask.turns = [Turn(id: 0, q: question, answer: .failure("no plan is signed in, so context cannot read for an answer. sign in to claude code or codex once."))]
                p.turnID = 0
            } }),
        ]
    }
}

extension LayoutTest {
    /// A made-up conversation around the first row an answer cites.
    static func threadProof(_ t: Turn) -> ThreadPeek? {
        guard let hit = t.answer?.cites.first else { return nil }
        var p = ThreadPeek(hit: hit, turn: t.id, number: 1)
        let lines: [(Bool, String)] = [(false, "morning. quick one about the flat."), (true, "Morning, Sam. Go on."),
            (false, "the lease renewal is due on the first. can you let me know by then whether you are staying, and whether the deposit carries over to the new term?"),
            (true, "I will check with the others and come back to you."), (false, "thanks. no rush before the weekend."),
            (false, "did you see my message about the renewal?"), (false, "also the boiler man is coming on thursday between nine and one, someone needs to be in.")]
        p.take(["title": "Sam (landlord)", "src": "whatsapp", "rows_total": Invented.thread, "open": "",
                "rows": lines.enumerated().map { i, l in ["id": "W\(i)", "ts": "2026-11-04T09:\(String(format: "%02d", 10 + i)):00Z", "me": l.0, "sender": l.0 ? "" : "Sam", "text": l.1, "here": i == 2] as [String: Any] }])
        return p
    }
}

extension LayoutTest {
    /// Home, sources and settings as a stranger meets them and as a heavy user does: nothing read, one source, forty.
    /// These run last: they change which sources exist.
    static func sizeScreens(_ m: AppModel, main: @escaping (Tab) -> Void) -> [(String, () -> Void)] {
        let e = m.engine
        func fill(_ ids: [String]) {
            e.order = ids
            e.states = [:]
            for (i, id) in ids.enumerated() { e.states[id] = .done(rows: Invented.sizes[i % 4], secs: 1) }
        }
        let forty = Catalog.order + (0..<max(0, 40 - Catalog.order.count)).map { "custom_app_\($0)" }
        var out: [(String, () -> Void)] = []
        for (word, ids) in [("zero", [String]()), ("one", ["whatsapp"]), ("forty", forty)] {
            out.append(("home-\(word)", { main(.home); fill(ids) }))
            out.append(("sources-\(word)", { main(.sources); fill(ids) }))
            out.append(("settings-\(word)", { main(.settings); fill(ids) }))
        }
        return out
    }
}
