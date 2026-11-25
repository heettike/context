import AppKit
import SwiftUI

@main
enum Main {
    static func main() {
        umask(0o077)        // before anything else: no file or folder this app or anything it starts makes is readable by another account
        if CommandLine.arguments.contains("--selftest") { SelfTest.run(); return }
        if CommandLine.arguments.contains("--asktest") { AskTest.run() }
        if let i = CommandLine.arguments.firstIndex(of: "--layouttest") {
            LayoutTest.run(out: CommandLine.arguments.count > i + 1 ? CommandLine.arguments[i + 1] : nil)
        }
        if let i = CommandLine.arguments.firstIndex(of: "--motiontest") {
            MotionTest.run(out: CommandLine.arguments.count > i + 1 ? CommandLine.arguments[i + 1] : nil)
        }
                // an option this build does not know must never fall through to opening the real app
        if let odd = CommandLine.arguments.dropFirst().first(where: { $0.hasPrefix("--") }) {
            FileHandle.standardError.write("context: unknown option \(odd)\n".data(using: .utf8)!)
            exit(2)
        }
        let app = NSApplication.shared
        let delegate = AppDelegate()
        app.delegate = delegate
        // a development run or render has no Dock icon, takes no focus and puts nothing on the screen
        app.setActivationPolicy(Engine.debug ? .prohibited : .regular)
        app.run()
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    let model = AppModel.shared
    var window: NSWindow!
    var statusItem: NSStatusItem!
    let popover = NSPopover()
    /// True while the app is only drawing itself to png files. It then stays out of the way: no focus, window off screen.
    let shooting = ProcessInfo.processInfo.environment["CONTEXT_DEBUG"]?.contains("shot=") == true

    func applicationDidFinishLaunching(_ note: Notification) {
        buildMenu()
        buildWindow()
        buildStatusItem()
        buildPanel()
        wirePings()
        pillTimer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in self?.reconcilePill(); self?.reconcileMenuBar() }
        NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] e in
            guard let self, e.window === self.window else { return e }
            let field = self.window.firstResponder as? NSTextView
            KeyNav.shared.key(e.keyCode, typing: field != nil)
            return self.model.windowKey(e, field: field, endEditing: { self.window.makeFirstResponder(nil) }) ? nil : e
        }
        // a click ends a walk with the keyboard: the ring is for tab and the arrows only
        NSEvent.addLocalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown]) { e in KeyNav.shared.mouse(); return e }
        // a wheel turned upward while an answer is written: the owner is reading back, and the page stops following the last line
        NSEvent.addLocalMonitorForEvents(matching: .scrollWheel) { [weak self] e in
            if let self, e.window === self.window, e.scrollingDeltaY > 0 { self.model.ask.follow = false }
            return e
        }
        if !shooting { NSApp.activate(ignoringOtherApps: true) }
        // the cursor starts in the input, not on whichever control macos would pick first
        if !shooting { DispatchQueue.main.async { [weak self] in self?.window.makeFirstResponder(nil); self?.model.focusAsk += 1 } }
        debugShots()
        if ProcessInfo.processInfo.environment["CONTEXT_DEBUG"]?.contains("popover") == true {
            DispatchQueue.main.asyncAfter(deadline: .now() + 1) { self.togglePopover(nil) }
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showWindow(nil)
        return true
    }

    func applicationWillTerminate(_ note: Notification) {
        model.activity.save()
        model.journal.save()
        model.ask.cancelAll()
        model.engine.client.quit()
        // A running collector is left to finish: it rewrites the files in place, and stopping it would leave them cut short.
    }

    // MARK: pill

    var pill: NSPanel?
    var attention = false           // something waits on the owner: the menu-bar mark carries the dot
    var busyTimer: Timer?           // turns the menu-bar mark while work goes on out of sight
    var busyStep = 0
    var busySaid = ""
    var pillTimer: Timer?
    var pillShowing = ""
    var shotPopover: NSWindow?
    var pingPanel: NSPanel?
    var pingTimer: Timer?

    /// Shows, moves or hides the pill so it matches the current nudge and the toggle.
    private func reconcilePill() {
        let want = model.saved.onboarded && model.saved.pill ? model.coach.current : nil
        guard (want?.id ?? "") != pillShowing else { return }
        pillShowing = want?.id ?? ""
        guard let n = want, n.kind != "focus", let screen = NSScreen.main else {
            pill?.orderOut(nil)
            return
        }
        let panel = pill ?? {
            let p = NSPanel(contentRect: .zero, styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
            p.level = .floating
            p.isOpaque = false
            p.backgroundColor = .clear
            p.hasShadow = true
            p.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
            p.hidesOnDeactivate = false
            pill = p
            return p
        }()
        let host = NSHostingView(rootView: PillView(nudge: n, open: { [weak self] in
            self?.model.go(.home)
            self?.showWindow(nil)
        }, dismiss: { [weak self] in self?.model.coach.answer(.ok, n) }))
        let size = host.fittingSize
        panel.contentView = host
        let v = screen.visibleFrame
        panel.setFrame(NSRect(x: shooting ? -6000 : v.maxX - size.width - 20, y: shooting ? -6000 : v.minY + 20,
                              width: size.width, height: size.height), display: true)
        if shooting { return }                 // a render draws the pill's view without ever showing its window
        panel.alphaValue = 0
        panel.orderFrontRegardless()
        NSAnimationContext.runAnimationGroup { $0.duration = 0.25; panel.animator().alphaValue = 1 }
        if ProcessInfo.processInfo.environment["CONTEXT_DEBUG"] != nil {
            FileHandle.standardError.write("pill \(panel.windowNumber)\n".data(using: .utf8)!)
        }
    }

    /// Development only: `CONTEXT_DEBUG=shot=/path.png,wait=3` writes the app's own views to png files and quits.
    /// The app draws itself, so this needs no screen recording permission.
    private func debugShots() {
        guard let d = ProcessInfo.processInfo.environment["CONTEXT_DEBUG"] else { return }
        var path = "", wait = 3.0
        for part in d.split(separator: ",") {
            let kv = part.split(separator: "=", maxSplits: 1).map(String.init)
            if kv[0] == "shot" { path = kv.last ?? "" }
            if kv[0] == "wait" { wait = Double(kv.last ?? "") ?? 3 }
            if kv[0] == "dark" { NSApp.appearance = NSAppearance(named: .darkAqua) }
            if kv[0] == "light" { NSApp.appearance = NSAppearance(named: .aqua) }
            popover.appearance = NSApp.appearance
        }
        guard !path.isEmpty else { return }
        func write(_ view: NSView?, _ to: String) {
            guard let view, let rep = view.bitmapImageRepForCachingDisplay(in: view.bounds) else { return }
            view.cacheDisplay(in: view.bounds, to: rep)
            try? rep.representation(using: .png, properties: [:])?.write(to: URL(fileURLWithPath: to))
        }
        // a render that hangs must not stay around: it is ended from outside the main thread
        DispatchQueue.global().asyncAfter(deadline: .now() + wait + 12) { exit(3) }
        DispatchQueue.main.asyncAfter(deadline: .now() + wait) {
            FileHandle.standardError.write("windows of this render on screen: \(Screen.ours())\n".data(using: .utf8)!)
            write(self.window.contentView, path)
            if let w = self.shotPopover { write(w.contentView, path.replacingOccurrences(of: ".png", with: "-popover.png")) }
            if let p = self.pingPanel {
                write(p.contentView, path.replacingOccurrences(of: ".png", with: "-ping.png"))
                let bar = NSImage(size: NSSize(width: 72, height: 72), flipped: false) { r in
                    (NSApp.effectiveAppearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua ? NSColor(white: 0.16, alpha: 1) : NSColor(white: 0.93, alpha: 1)).setFill()
                    r.fill()
                    LogoMark.menuBarAttentionImage().draw(in: r.insetBy(dx: 9, dy: 9))
                    return true
                }
                if let tiff = bar.tiffRepresentation, let rep = NSBitmapImageRep(data: tiff) {
                    try? rep.representation(using: .png, properties: [:])?.write(to: URL(fileURLWithPath: path.replacingOccurrences(of: ".png", with: "-menubar.png")))
                }
            }
            if let p = self.pill { write(p.contentView, path.replacingOccurrences(of: ".png", with: "-pill.png")) }
            NSApp.terminate(nil)
        }
    }

    // MARK: window

    private func buildWindow() {
        // wide enough, the first time, that an answer is a page with its notes in the margin beside the list of chats
        // (252 + 908). after that the window is wherever the owner left it
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1160, height: 740),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
                          backing: .buffered, defer: false)
        window.titlebarAppearsTransparent = true
        window.titleVisibility = .hidden
        window.title = "context"
        window.isMovableByWindowBackground = true
        window.backgroundColor = Ink.paperNS
        window.minSize = NSSize(width: 760, height: 540)
        window.isReleasedWhenClosed = false
        window.delegate = self
        // a unified title bar: the traffic lights sit on the centre line of a taller bar, and our row is laid on that same line
        let bar = NSToolbar(identifier: "context.bar")
        bar.showsBaselineSeparator = false
        window.toolbar = bar
        window.toolbarStyle = .unified
        window.contentView = NSHostingView(rootView: RootView().environment(model))
        measureLights()
        window.center()
        if !Engine.debug { window.setFrameAutosaveName("context.main") }
        if shooting {
            let tall = ProcessInfo.processInfo.environment["CONTEXT_DEBUG"]?.contains("tall") == true
            window.setContentSize(NSSize(width: 920, height: tall ? 1900 : 640))
            // never ordered in: macos pulls an "off screen" window back so a corner shows. it is laid out and drawn unseen.
            window.contentView?.layoutSubtreeIfNeeded()
        } else {
            window.makeKeyAndOrderFront(nil)
        }
        if ProcessInfo.processInfo.environment["CONTEXT_DEBUG"] != nil {
            FileHandle.standardError.write("window \(window.windowNumber)\n".data(using: .utf8)!)
        }
    }

    /// Reads where macos put the traffic lights, so the top bar is laid on their centre line and starts after them.
    func measureLights() {
        guard let zoom = window.standardWindowButton(.zoomButton), let close = window.standardWindowButton(.closeButton) else { return }
        window.layoutIfNeeded()
        let z = zoom.convert(zoom.bounds, to: nil), c = close.convert(close.bounds, to: nil)
        let centre = window.frame.height - (z.midY + c.midY) / 2
        guard centre > 8, centre < 60, z.maxX > 30, z.maxX < 140 else { return }
        model.lights = CGPoint(x: z.maxX, y: centre)
        if ProcessInfo.processInfo.environment["CONTEXT_DEBUG"] != nil {
            FileHandle.standardError.write("lights centre \(centre) end \(z.maxX)\n".data(using: .utf8)!)
        }
    }

    func windowDidResize(_ note: Notification) { measureLights() }

    func windowDidBecomeKey(_ note: Notification) { model.loadCard() }

    @objc func showWindow(_ sender: Any?) {
        popover.performClose(nil)
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    // MARK: menu bar

    private func buildStatusItem() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        // macos remembers whether an item is shown, per app and per name. an offscreen render must hide its own item, and
        // it once hid the real one for good by sharing its name: it now has a name of its own, and the real item is put
        // back once on machines where that happened.
        if shooting { statusItem.autosaveName = "context-offscreen"; statusItem.isVisible = false }
        else if !UserDefaults.standard.bool(forKey: "statusItemRestored") {
            statusItem.isVisible = true
            UserDefaults.standard.set(true, forKey: "statusItemRestored")
        }
        let image = LogoMark.menuBarImage()
        statusItem.button?.image = image
        statusItem.button?.toolTip = "context"
        statusItem.button?.target = self
        statusItem.button?.action = #selector(statusClick(_:))
        popover.behavior = .transient
        popover.animates = true
        let host = NSHostingController(rootView: PopoverView(open: { [weak self] in self?.showWindow(nil) }).environment(model))
        host.sizingOptions = [.preferredContentSize]
        popover.contentViewController = host
    }

    // MARK: the panel

    var panel: PanelController?

    /// Built once and kept hidden, so the key shows it at once. Never built in a render or a test: nothing of those reaches the screen.
    private func buildPanel() {
        guard !Engine.debug else { return }
        panel = PanelController(model: model, showWindow: { [weak self] in self?.showWindow(nil) })
        setHotKey()
    }

    func setHotKey() {
        HotKey.set(model.saved.hotkey) { [weak self] in self?.panel?.toggle() }
        if !Engine.debug { model.liveKey = HotKey.live }
    }

    /// A click on the menu-bar mark opens the panel, the same one the key opens. When something is waiting for the owner
    /// (an export to approve, a nudge), or with option held, it opens the list of those instead.
    @objc func statusClick(_ sender: Any?) {
        let option = NSApp.currentEvent?.modifierFlags.contains(.option) == true
        if let panel, !option, !popover.isShown, model.saved.onboarded, model.pinger.queue.isEmpty { panel.toggle() } else { togglePopover(sender) }
    }

    @objc func togglePopover(_ sender: Any?) {
        if shooting {      // draw the popover's content in a window nobody sees, never under the real menu bar
            let host = NSHostingView(rootView: PopoverView(open: {}).environment(model))
            let w = NSWindow(contentRect: NSRect(origin: NSPoint(x: -6000, y: -4000), size: host.fittingSize),
                             styleMask: [.borderless], backing: .buffered, defer: false)
            w.isReleasedWhenClosed = false
            w.contentView = host
            host.layoutSubtreeIfNeeded()
            shotPopover = w
            return
        }
        guard let button = statusItem.button else { return }
        if popover.isShown { popover.performClose(sender) } else {
            model.pinger.seen()
            popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
            if !shooting { popover.contentViewController?.view.window?.makeKey() }
            if ProcessInfo.processInfo.environment["CONTEXT_DEBUG"] != nil, let w = popover.contentViewController?.view.window {
                FileHandle.standardError.write("popover \(w.windowNumber)\n".data(using: .utf8)!)
            }
        }
    }

    // MARK: menus

    @objc func goHome() { go(.home) }
    @objc func goSources() { go(.sources) }
    @objc func goSettings() { go(.settings) }
    @objc func goPlan() { go(.plan) }
    @objc func newChat() { showWindow(nil); model.newChat() }
    @objc func searchChats() { showWindow(nil); model.searchChats() }
    @objc func toggleSidebar() { model.toggleSidebar() }
    @objc func stopAnswer() { model.ask.stop() }
    @objc func previousChat() { model.stepChat(-1) }
    @objc func nextChat() { model.stepChat(1) }
    @objc func exact() {
        showWindow(nil)
        if model.tab == .profile, model.wiki.exists { model.wiki.briefing = false; model.wiki.focusFilter += 1 } else { model.exactSearch() }
    }
    @objc func askAnywhere() { panel?.show() }
    @objc func syncNow() { model.engine.sync(tick: true, tier: "fast") }

    private func go(_ tab: Tab) {
        guard model.saved.onboarded else { return }
        showWindow(nil)
        model.go(tab)
    }

    private func buildMenu() {
        let main = NSMenu()
        func add(_ title: String, _ items: [NSMenuItem]) {
            let item = NSMenuItem(), menu = NSMenu(title: title)
            items.forEach(menu.addItem)
            item.submenu = menu
            main.addItem(item)
        }
        func item(_ title: String, _ action: Selector?, _ key: String = "", target: Bool = true) -> NSMenuItem {
            let i = NSMenuItem(title: title, action: action, keyEquivalent: key)
            if target { i.target = self }
            return i
        }
        add("context", [
            item("About context", #selector(NSApplication.orderFrontStandardAboutPanel(_:)), target: false),
            .separator(),
            item("Sync Now", #selector(syncNow), "r"),
            .separator(),
            item("Hide context", #selector(NSApplication.hide(_:)), "h", target: false),
            item("Quit context", #selector(NSApplication.terminate(_:)), "q", target: false),
        ])
        add("File", [
            item("New Chat", #selector(newChat), "n"),
            item("Search Chats", #selector(searchChats), "k"),
            .separator(),
            item("Stop the Answer", #selector(stopAnswer), "."),
        ])
        add("Edit", [
            item("Undo", Selector(("undo:")), "z", target: false),
            item("Cut", #selector(NSText.cut(_:)), "x", target: false),
            item("Copy", #selector(NSText.copy(_:)), "c", target: false),
            item("Paste", #selector(NSText.paste(_:)), "v", target: false),
            item("Select All", #selector(NSText.selectAll(_:)), "a", target: false),
            .separator(),
            item("Ask From Anywhere", #selector(askAnywhere)),
            item("Search Exact Words", #selector(exact), "f"),
        ])
        let fold = item("Show or Hide the List of Chats", #selector(toggleSidebar), "s")
        fold.keyEquivalentModifierMask = [.command, .shift]
        add("View", [
            fold,
            item("Previous Chat", #selector(previousChat), "["),
            item("Next Chat", #selector(nextChat), "]"),
            .separator(),
            item("Chat", #selector(goHome), "1"),
            item("Journal", #selector(goPlan), "2"),
            item("Sources", #selector(goSources), "3"),
            item("Settings", #selector(goSettings), ","),
        ])
        add("Window", [
            item("Close", #selector(NSWindow.performClose(_:)), "w", target: false),
            item("Minimize", #selector(NSWindow.performMiniaturize(_:)), "m", target: false),
            item("context", #selector(showWindow(_:)), "0"),
        ])
        NSApp.mainMenu = main
    }
}

struct RootView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduce

    var body: some View {
        ZStack {
            Ink.paper.ignoresSafeArea()
            if Probe.on, let p = model.pingProof {
                PingProof(ping: p)
            } else if Probe.on, model.popoverProof {
                PopoverProof()
            } else if Probe.on, model.panelProof != nil {
                PanelProof()
            } else if model.saved.onboarded {
                MainView().transition(.opacity.combined(with: .scale(scale: reduce ? 1 : 0.985)))
            } else {
                OnboardingView().transition(.opacity)
            }
        }
        .animation(Motion.spring(reduce), value: model.saved.onboarded)
        .ignoresSafeArea()
        .frame(minWidth: 760, minHeight: 540)
        .coordinateSpace(name: Probe.space)
        .onPreferenceChange(ProbeKey.self) { if Probe.on { Probe.found = $0 } }
    }
}

/// The main window: the list of chats on the left, one page in the middle, and on the right, when asked for, the
/// sources of an answer. The page is a conversation (or home, before the first question), the plan, the sources or settings.
struct MainView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduce
    @Namespace private var space

    var body: some View {
        GeometryReader { geo in
            let panel = model.panelShown(width: geo.size.width)
            let side = model.sidebarShown(width: geo.size.width, panel: panel)
            let _ = (model.frameWidth = geo.size.width)
            HStack(spacing: 0) {
                if side { Sidebar().transition(.move(edge: .leading)) }
                VStack(spacing: 0) {
                    MainBar(side: side).zIndex(1)
                    ZStack {
                        // a page is cut and the next one arrives: no page fades out under another (Motion.page).
                        // home and a conversation are the exception, since the input travels from one to the other
                        switch model.tab {
                        case .home:
                            if model.ask.exact { ExactView().pageIn() }
                            else { HomeStage() }
                        case .sources: SourcesView().pageIn()
                        case .plan: PlanView().pageIn()
                        case .settings: SettingsView().pageIn()
                        case .profile: ProfileView().pageIn()
                        case .teach: TeachView().pageIn()
                        case .made: MadeView().pageIn()
                        }
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .environment(\.askSpace, space)
                    // time is always on screen where the owner asks: the years down the left edge, now at the foot. it stays
                    // while home becomes a conversation
                    .overlay(alignment: .leading) { if model.tab == .home, !model.ask.exact { Spine() } }
                    .onChange(of: model.engine.syncing) { _, on in if !on { model.now.load(model.engine, force: true) } }
                    .overlay {
                        if let add = model.adding, model.addShown {
                            // the page steps out of the way: plain paper, and the sheet in the middle of it
                            ZStack {
                                // a click outside puts a working sheet away without stopping it; otherwise it closes
                                Ink.paper.contentShape(Rectangle()).onTapGesture { if add.stage == .working { model.addHidden = true } else { model.closeAdd() } }
                                AddSheet(add: add).offset(y: -30)
                                    .transition(reduce ? .opacity : .offset(y: 14).combined(with: .opacity))
                            }
                            .frame(maxWidth: .infinity, maxHeight: .infinity)
                            .transition(.opacity)
                        }
                    }
                    .onPreferenceChange(ScrollTopKey.self) { top in
                        let under = top < model.lights.y * 2 - 1
                        if under != model.underBar { model.underBar = under }
                    }
                    .animation(Motion.tray(reduce), value: model.ask.chatting)
                    .animation(Motion.spring(reduce), value: model.addShown)
                }
                .frame(maxWidth: .infinity)
                // whatever is running outside the chats keeps running wherever the owner goes; it waits here, small, in the corner
                .overlay(alignment: .bottomTrailing) { JobPills().padding(.trailing, 18).padding(.bottom, 16) }
                if panel > 0 { SourcesPanel(width: panel).transition(.move(edge: .trailing)) }
            }
            .animation(Probe.on ? nil : Motion.tray(reduce), value: side)
            .animation(Probe.on ? nil : Motion.tray(reduce), value: panel > 0)
        }
    }
}

/// Home, or the conversation it becomes. Sending a question is two beats and never an overlap: home falls back and
/// fades (120 ms) while it is still the only page; then it is cut, the conversation stands in its place and the
/// question rises from the input to the top (`Lift`). Going back to home is a cut and an arrival, like any page.
/// With Reduce Motion both are a plain swap.
struct HomeStage: View {
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduce
    @State private var chat = AppModel.shared.ask.chatting       // which of the two is drawn: it follows the model a beat late on the way in
    @State private var falling = false
    @State private var beat = 0

    var body: some View {
        ZStack {
            if chat { ChatView().transition(.identity).id("chat") }
            else {
                HomeView().transition(.identity).id("home")
                    .opacity(falling ? 0 : 1).scaleEffect(falling ? 0.97 : 1)
                    .modifier(PageIn())
            }
        }
        .onChange(of: model.ask.chatting) { _, on in
            beat += 1
            let mine = beat
            guard on, !chat, !reduce, !Probe.still else { chat = on; falling = false; return }
            withAnimation(Motion.deskOut(false)) { falling = true }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.13) {
                guard mine == beat else { return }
                withAnimation(Motion.tray(false)) { chat = model.ask.chatting }
                falling = false
            }
        }
        .onAppear { chat = model.ask.chatting }
    }
}

extension MainView {
    /// The sidebar and the panel share a narrow window. Run dry at 920 and at 800 points: the panel folds the sidebar,
    /// closing the panel brings it back, and the fold button always changes what is on screen.
    static func foldFaults() -> [String] {
        let m = AppModel.shared
        var out: [String] = []
        let was = (m.saved.sidebar, m.sideOver, m.tab, m.ask.sourcesFor, m.frameWidth, m.saved.onboarded)
        defer { m.saved.sidebar = was.0; m.sideOver = was.1; m.tab = was.2; m.ask.sourcesFor = was.3; m.frameWidth = was.4; m.saved.onboarded = was.5 }
        func side(_ w: CGFloat) -> Bool { m.sidebarShown(width: w, panel: m.panelShown(width: w)) }
        m.saved.onboarded = true; m.tab = .home; m.ask.exact = false; m.adding = nil; m.people.open = nil; m.ask.thread = nil; m.chatSearch = nil
        m.saved.sidebar = true; m.sideOver = false; m.frameWidth = 920
        m.ask.sourcesFor = nil
        if !side(920) { out.append("frame: the sidebar does not show at 920 with nothing open") }
        m.ask.sourcesFor = 0
        if side(920) { out.append("frame: at 920 the sidebar does not fold for the sources panel") }
        m.ask.closePanel()
        if !side(920) { out.append("frame: the sidebar does not come back when the sources panel closes") }
        m.ask.sourcesFor = 0
        m.toggleSidebar()            // the bar offers "show sidebar" while the panel has its room
        if !side(920) || !m.saved.sidebar { out.append("frame: asking for the sidebar while the panel has its room does not show it") }
        if m.panelShown(width: 920) > 0 { out.append("frame: the panel did not give way to the sidebar the owner asked for") }
        m.ask.sourcesFor = 0; m.ask.closePanel()
        if !side(920) { out.append("frame: the sidebar is lost after the panel was opened and closed again") }
        m.frameWidth = 800
        if side(800) { out.append("frame: the sidebar shows by itself in a window 800 wide") }
        m.toggleSidebar()
        if !side(800) { out.append("frame: asking for the sidebar in a narrow window does not show it") }
        m.toggleSidebar()
        if side(800) || m.saved.sidebar { out.append("frame: the sidebar cannot be put away in a narrow window") }
        return out
    }
}

/// `context --selftest` checks the parts that need no window: parsing the collector's lines, reading dates,
/// and searching whatever is in CTX_HOME. It prints counts and timings only, never text from the data.
enum SelfTest {
    static func run() {
        var failed = 0
        func check(_ name: String, _ ok: Bool) { print(ok ? "ok   " : "FAIL ", name); if !ok { failed += 1 } }
        check("parse rows", Engine.parse("whatsapp     {'rows': 150000, 'secs': 6.4}").map { $0.0 == "whatsapp" && $0.1 == .done(rows: 150000, secs: 6.4) } ?? false)
        check("parse skipped", Engine.parse("imessage     {'skipped': 'blocked by macOS: grant Full Disk Access'}").map { $0.1 == .skipped("blocked by macOS: grant Full Disk Access") } ?? false)
        check("parse skipped, double quotes", Engine.parse("x_posts      {'skipped': \"can't read\"}").map { $0.1 == .skipped("can't read") } ?? false)
        check("parse ignores noise", Engine.parse("Traceback (most recent call last):") == nil)
        check("blocked: full disk", Blocked("blocked by macOS: grant Full Disk Access to the app", Catalog.info("imessage")).settings)
        check("service parses", Service(["id": "x", "name": "X", "state": "needs_you", "detail": "d", "asks_for": "code", "arrives": "a day"]).map { $0.state == .needsYou && $0.name == "x" } ?? false)
        check("service without id is dropped", Service(["name": "X"]) == nil)
        print("     something is holding the display awake: \(Pinger.screenBusy())")
        check("progress line", Engine.progress("@{\"src\":\"whatsapp\",\"rows\":1700,\"at\":\"2025-02\",\"label\":\"a thread\"}").map { $0.0 == "whatsapp" && $0.1.rows == 1700 && $0.1.at == "2025-02" } ?? false)
        check("kept from last time", Engine.parse("imessage     {'rows': 30000, 'stale': True, 'why': 'blocked by macOS: grant Full Disk Access'}").map { $0.1 == .kept(rows: 30000, why: "blocked by macOS: grant Full Disk Access") } ?? false)
        check("model nudge", Coach.nudge(from: ["say": "Stop.", "why": "w", "kind": "owed", "confidence": 4]).map { $0.kind == "promise" && $0.text == "stop." } ?? false)
        check("model has nothing to say", Coach.nudge(from: ["say": "", "kind": "none"]) == nil)
        check("rolling line ends on the text", RollingLine.render("you typed 400,000 words. about 4 novels.", 1) == "you typed 400,000 words. about 4 novels.")
        check("rolling line starts low", RollingLine.render("you typed 400,000 words in 2020.", 0.5) == "you typed 200,000 words in 2020.")
        check("answer parses", Answer(["answer": "Yes.", "cites": [["id": "W1", "src": "whatsapp", "ts": "2024-03-09T10:00:00Z", "thread": "a", "who": "me", "text": "t"]], "searched": ["a"], "error": ""], tag: "t0").map { $0.text == "Yes." && $0.cites.count == 1 } ?? false)
        check("answer error", Answer(["answer": "", "error": "no plan signed in"], tag: "t0")?.error == "no plan signed in")
        check("exact search drops small words", AskModel.terms("link to my allotment talk") == ["allotment", "talk"])
        check("words", Coach.words("ship the pricing page", min: 3) == ["pricing", "page"])
        let line = Array("{\"id\": \"W1\", \"src\": \"whatsapp\", \"ts\": \"2024-03-09T10:00:00Z\", \"text\": \"Hello There\"}".utf8)
        line.withUnsafeBufferPointer { b in
            check("date in line", Jsonl.date(in: b) == "2024-03-09")
            let n = Array("hello".utf8)
            n.withUnsafeBufferPointer { check("case-insensitive match", Jsonl.contains(b, $0)) }
        }
        check("dim text reads at 4.5:1 on every ground, light and dark", Ink.contrastFaults().isEmpty)
        check("repo found", Engine.findRepo(Engine.devEngine) != nil)

        // CONTEXT_WARMTEST=1 with CONTEXT_REPO at an engine: talks to `ctx serve` as the app does. a plain request, then a
        // streamed answer, and with DEMO_DEEP the deeper reply that follows the first.
        if ProcessInfo.processInfo.environment["CONTEXT_WARMTEST"] != nil, let repo = Engine.findRepo(Engine.devEngine) {
            let w = Warm(repo: repo)
            var settings = false, deltas = 0, dones = 0, digs = 0, ended = false
            w.send(["cmd": "settings"], event: { if $0["result"] is [String: Any] { settings = true } }, end: {})
            let want = ProcessInfo.processInfo.environment["DEMO_DEEP"] != nil ? 2 : 1
            let id = w.send(["cmd": "answer", "q": "did i reply to sam", "history": [Any](), "stream": true], open: true, event: { d in
                if d["delta"] != nil { deltas += 1 }
                if d["phase"] as? String == "dig" { digs += 1 }
                if d["done"] != nil { dones += 1 }
            }, end: { ended = true })
            let until = Date().addingTimeInterval(40)
            while (dones < want || !settings) && Date() < until { RunLoop.current.run(until: Date().addingTimeInterval(0.05)) }
            check("warm engine: a plain request comes back", settings)
            check("warm engine: an answer streams (\(deltas) pieces)", deltas > 3 && dones >= 1)
            if want == 2 { check("warm engine: the deeper reply follows the first (\(digs) steps)", dones == 2 && digs > 0) }
            if let id { w.finish(id) }
            check("warm engine: the reader ends an open stream", ended)
            w.stop()
        }
        // the checks below read an archive folder. only one that was named: with no CTX_HOME they look at an empty
        // place, never at the real archive of whoever runs the self-test
        let env = ProcessInfo.processInfo.environment
        let home = URL(fileURLWithPath: env["CTX_HOME"].map { ($0 as NSString).expandingTildeInPath } ?? (NSTemporaryDirectory() + "context-selftest-empty"))
        if let log = try? String(contentsOf: home.appendingPathComponent("collect.log"), encoding: .utf8) {
            let lines = log.split(separator: "\n").filter { $0.contains("{") }
            check("every line of collect.log parses (\(lines.count))", lines.allSatisfy { Engine.parse(String($0)) != nil })
        }
        var t = Date()
        let spans = Jsonl.spans(home: home)
        print("     spans for \(spans.count) sources in \(Int(Date().timeIntervalSince(t) * 1000)) ms")
        for q in CommandLine.arguments.drop(while: { $0 != "--selftest" }).dropFirst() {
            t = Date()
            let groups = Jsonl.search(home: home, query: q, stop: Flag())
            let ms = Int(Date().timeIntervalSince(t) * 1000)
            print("     search of \(q.count) chars: \(groups.reduce(0) { $0 + $1.total }) hits in \(groups.count) sources, \(ms) ms")
            if let h = groups.first?.hits.first, h.kind == "message" {
                t = Date()
                let around = Jsonl.thread(home: home, hit: h)
                print("     thread around the first hit: \(around.count) rows, \(Int(Date().timeIntervalSince(t) * 1000)) ms")
                check("thread holds the hit", around.contains { $0.id == h.id })
            }
        }
        print(failed == 0 ? "all checks passed" : "\(failed) failed")
        exit(failed == 0 ? 0 : 1)
    }
}

enum Screen {
    /// How many windows of this process the window server is showing. A render or a layout test must report 0.
    static func ours() -> Int {
        let list = (CGWindowListCopyWindowInfo([.optionOnScreenOnly], kCGNullWindowID) as? [[String: Any]]) ?? []
        let pid = Int(ProcessInfo.processInfo.processIdentifier)
        return list.filter { ($0[kCGWindowOwnerPID as String] as? Int) == pid && (($0[kCGWindowAlpha as String] as? Double) ?? 1) > 0 }.count
    }
}
