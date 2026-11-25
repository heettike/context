import AppKit
import ApplicationServices
import Observation
import ServiceManagement
import SwiftUI

enum Tab: Int, CaseIterable {
    case home, plan, sources, settings, profile, teach, made
    var word: String { ["home", "plan", "sources", "settings", "profile", "teach", "made"][rawValue] }
}

enum Step: Equatable, Hashable {
    case welcome, reading      // first run is two screens: what this is and its switches, then the live list
}

@Observable final class AppModel {
    static let shared = AppModel()

    let engine: Engine
    let ask: AskModel
    let loops: LoopsModel
    let activity: Activity
    let requests: Requests
    let journal: Journal
    let settings: SettingsModel
    let profile: ProfileModel
    let wiki: WikiModel
    let people = PeopleModel()
    let wikiBuild = WikiBuild()
    @ObservationIgnored private(set) var coach: Coach!
    @ObservationIgnored private(set) var pinger: Pinger!
    var saved: Saved
    /// links_from_others, the switch answers, the wiki and the pages about you follow: the engine's word when its report
    /// carries it, else the app's copy
    var linksFromOthers: Bool { settings.linksFromOthers ?? saved.linksFromOthers }
    var tab: Tab = .home { didSet { if tab != oldValue { dismissOverlays() } } }
    var settingsPane: SettingsPane = .general
    var focusAsk = 0
    var liveKey = "control-option"  // the key that opens the panel, as macos registered it; "off" when none
    var card: Card?                 // the morning card, when today has one
    var underBar = false            // content has been scrolled up under the top bar
    var models: ModelsReport?       // which model does which job, once the engine has said
    var measuring = false
    var chatSearch: String?         // the sidebar's search field, while it is open
    var renaming: String?           // the chat whose title is being typed over
    var sideTyping = false          // the cursor is in a field that is not the input: the search, a title, a name
    var focusSearch = 0
    var sideOver = false            // the owner asked for the sidebar in a window too narrow to show it by itself
    @ObservationIgnored var frameWidth: CGFloat = 920      // the window's width, as the frame last laid it out
    var panelWidth: CGFloat = 340   // the sources panel on the right, as wide as the owner last dragged it
    var popoverProof = false        // set only by the layout test: the menu-bar popover drawn inside the test window
    var pingProof: Ping?            // set only by the layout test: the menu-bar panel drawn inside the test window
    var panelProof: PanelModel?     // set only by the layout test: the panel drawn inside the test window
    var shelfArmed: String?         // an export tile pressed once: the line asks, and a second press sends the request
    var shelfFocus: String?         // the shelf item under the pointer or the arrow keys
    @ObservationIgnored var restPointer = NSEvent.mouseLocation     // where the pointer was resting when home came up
    @ObservationIgnored var healed: Set<String> = []                 // sources read again since access was last found on
    var adding: AddModel?           // the add sheet, while it is open
    var addHidden = false           // the sheet is put away while the engine works; the job sits in the corner
    let journalLines = JournalLines()   // the engine's page of the day, gone over line by line: notes and removals
    let keys = KeysModel()              // apps with a key: what each reads over the local api, its log, the never list
    let exports = ExportsModel()        // the engine's export rows, the nightly catch-up, telegram's sign-in
    let made = MadeModel()          // what context has made for them: posts, plans, briefs
    let rules = RulesModel()        // teach: how the owner has told context to treat their data
    let now = NowModel()            // the desk: the last thirty days, from the engine's `now`
    var pending: [PendingSource] = []      // tried and saved, never switched on: shown on the sources page until it is
    var pendingBusy: Set<String> = []      // being switched on now
    var pendingFault: [String: String] = [:]     // what the engine said when switching one on did not work
    var lights = CGPoint(x: 79, y: 26)     // the traffic lights: where they end, and their centre from the top of the window
    var bridge: Bool?               // whether the browser extension is connected, once the engine has said
    var loginItem = false

    // onboarding
    var stepIndex = 0
    var following = false
    var access = false
    var askedForAccess = false
    var askedForTitles = false
    var settled: String?            // the source step whose read has landed and finished counting on screen
    var plan: ModelPlan?            // which of their own plans the model calls run on
    var started = false             // the reading has begun in this run
    var awayRead = false            // it finished while nobody was looking
    var seen: Set<String> = []      // source steps that were on screen until they settled
    var wanted: Set<String> = []    // exports switched on in the permissions list
    var facts: Facts?
    var detail: String?             // the source whose own live view is open on the reading screen
    var readingSince: Date?
    var readingDone: Date?
    var signedIn = SignedIn.notYet  // first run's second part: the sources read where the owner is signed in (the daily tier)
    var mcp: [MCPLine] = []         // how connecting each ai app went, from the engine
    var mcpRunning = false
    @ObservationIgnored private var retried = Set<String>()
    @ObservationIgnored private var browserTried = false
    var automation: [String: Grant] = [:]
    var askingAutomation = false

    @ObservationIgnored private var clock: Timer?
    @ObservationIgnored private var lastTick = Date.distantPast

    init() {
        let e = Engine()
        engine = e
        saved = Saved.load(e.file("app.json"))
        ask = AskModel(home: e.home)
        loops = LoopsModel(home: e.home)
        activity = Activity(home: e.home)
        requests = Requests(engine: e)
        journal = Journal(home: e.home)
        settings = SettingsModel(engine: e)
        profile = ProfileModel(home: e.home)
        profile.engine = e
        wiki = WikiModel(home: e.home)
        wiki.engine = e
        wiki.linksFromOthers = { [weak self] in self?.linksFromOthers ?? false }
        people.engine = e
        wikiBuild.engine = e
        // pages show up in the list as they are written; when the writing ends by itself, that is said once
        wikiBuild.onProgress = { [weak self] in self?.wiki.load() }
        wikiBuild.onDone = { [weak self] in
            guard let self else { return }
            self.wiki.load()
            if !self.wikiBuild.paused, let n = self.wikiBuild.status?.total, n > 0 { self.pinger.finished("wiki", text: "the wiki is written: \(Words.count(n)) pages about you", fix: .window) }
        }
        coach = Coach(model: self)
        pinger = Pinger(model: self)
        Blocked.route = { [unowned self] in (self.browserOn, (self.requests.browser?.howToEnable ?? "").contains("--enable-browser") ? "turn on" : "set it up") }
        Blocked.act = { [unowned self] fix in if fix == .browser { self.browserAct() } else if fix == .daily { self.readSignedIn(again: true) } }
        e.onFinish = { [weak self] in
            guard let self else { return }
            self.loops.reload()
            if self.ask.exact, !self.ask.query.isEmpty { self.ask.rerun() }
            self.coach.evaluate()
            self.requests.refresh()
            self.collected()
            self.heal()
        }
        activity.onChange = { [weak self] in self?.coach.evaluate() }
        // the day's apps and window titles are written down only for nudges worded by the plan, which is off until switched on
        activity.keeps = { [weak self] in self?.saved.nudgeModel == true }
        loginItem = SMAppService.mainApp.status == .enabled
        access = Access.fullDisk
        clock = Timer.scheduledTimer(withTimeInterval: 60, repeats: true) { [weak self] _ in self?.tick() }
        // setup is for a mac with no archive. once anything has been read, it is never shown again unless asked for.
        if !saved.onboarded, engine.totalRows > 0 { saved.onboarded = true; persist() }
        debugSetup()
        loadPlan()
        loadModels()
        journal.engine = e
        ask.loadLenses(e)
        ask.loadStarters(e)
        loadBridge()
        if saved.onboarded { startWatching() }
        DispatchQueue.main.async { [weak self] in self?.profile.load(); self?.wiki.load() }       // the pages, and from them or the engine, the people
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { [weak self] in self?.heal() }
        NotificationCenter.default.addObserver(forName: NSApplication.didBecomeActiveNotification, object: nil, queue: .main) { [weak self] _ in
            self?.restPointer = NSEvent.mouseLocation
            self?.heal()
        }
    }

    func persist() { if !Engine.debug { saved.save(engine.file("app.json")) } }

    // MARK: watching

    static let interval: TimeInterval = 15 * 60

    /// Runs once at launch, and then the minute clock keeps it going: `tick` itself decides what is due.
    func startWatching() {
        if !activity.frozen, saved.hourly, !engine.syncing, lastTick == .distantPast {
            lastTick = Date()
            DispatchQueue.main.asyncAfter(deadline: .now() + 4) { if !self.engine.syncing { self.engine.sync(tick: true) } }
        }
        activity.start()
        coach.start()
        pinger.start()
    }

    private func tick() {
        heal()
        guard saved.onboarded, saved.hourly, !engine.syncing else { return }
        if Date().timeIntervalSince(lastTick) >= AppModel.interval { lastTick = Date(); engine.sync(tick: true) }
    }

    var nextSync: String {
        guard saved.hourly else { return "" }
        let left = Int((AppModel.interval - Date().timeIntervalSince(lastTick)) / 60)
        return left <= 0 ? "next look within a minute" : "next look in \(left) min"
    }

    func setHourly(_ on: Bool) { saved.hourly = on; persist() }
    func setPill(_ on: Bool) { saved.pill = on; persist() }

    func setFocus(_ text: String) {
        let t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard t != saved.focus else { return }
        saved.focus = t
        saved.focusSet = Date().timeIntervalSince1970
        persist()
        coach.evaluate()
    }

    /// Only ever called from the toggle. Nothing is registered until the user flips it.
    func setLoginItem(_ on: Bool) {
        do {
            if on { try SMAppService.mainApp.register() } else { try SMAppService.mainApp.unregister() }
        } catch {}
        loginItem = SMAppService.mainApp.status == .enabled
    }

    /// Asks macOS to list context under Accessibility, then opens that pane. Called from a button only.
    func askForTitles() {
        askedForTitles = true
        _ = AXIsProcessTrustedWithOptions(["AXTrustedCheckOptionPrompt": true] as CFDictionary)
        if let u = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility") {
            NSWorkspace.shared.open(u)
        }
    }

    // MARK: permissions, all in one place

    static let automated = [("com.apple.iCal", "calendar"), ("com.apple.Notes", "notes"), ("com.apple.mail", "mail")]

    var automationGrant: Grant {
        if askingAutomation { return .asked }
        let all = AppModel.automated.map { automation[$0.0] ?? .off }
        return all.allSatisfy { $0 == .on } ? .on : (all.contains(.asked) ? .asked : .off)
    }

    /// Switch n on the first screen. Each is one click; its state comes from polling, never from the click.
    func grant(_ n: Int) {
        switch n {
        case 1: askedForAccess = true; Access.openSettings()
        case 2: browserAct()
        case 3: plan = nil; loadPlan()
        case 4: connectAIs()
        default: break
        }
    }

    /// Whether the browser route works: page scripting is on, or the extension is connected.
    var browserOn: Bool { exports.browser?.canRead ?? (requests.browser?.scripting == true || bridge == true) }
    /// Asking a site for an export is a second ability: page scripting gives it, the extension alone does not.
    var canAskExports: Bool { exports.browser?.canRequest ?? (requests.browser?.scripting == true) }
    /// The one line of how to get it, when it is missing: the engine's own, else a plain one.
    var askExportsNeeds: String {
        let said = exports.browser?.requestNeeds ?? ""
        let name = requests.browser?.name.isEmpty == false ? requests.browser!.name : (exports.browser?.name.isEmpty == false ? exports.browser!.name : "your browser")
        return said.isEmpty ? "switch on page scripting in \(name). the extension reads, but only page scripting can press a site's own buttons." : said
    }

    /// The route this browser needs: the scripting switch where the engine can flip it, else the extension.
    func browserAct() {
        guard !activity.frozen else { return }
        if (requests.browser?.howToEnable ?? "").contains("--enable-browser") { requests.enableBrowser(); return }
        engine.json(["bridge", "--install"], timeout: 60) { [weak self] _ in self?.loadBridge() }
        if let ext = engine.repo?.appendingPathComponent("extension"), FileManager.default.fileExists(atPath: ext.path) {
            NSWorkspace.shared.activateFileViewerSelecting([ext])      // the folder to load in the browser's extensions page
        }
    }

    /// `python3 -m ctx mcp --install`: registers context with the ai apps on this mac and says how each went.
    func connectAIs() {
        guard !mcpRunning, !activity.frozen else { return }
        mcpRunning = true
        engine.json(["mcp", "--install"], timeout: 120) { [weak self] obj in
            guard let self else { return }
            self.mcpRunning = false
            guard let obj else { self.mcp = [MCPLine(name: "context", status: "skipped: the engine did not answer")]; return }
            let order = ["claude desktop", "claude code", "cursor", "codex"]
            self.mcp = obj.compactMap { k, v in (v as? String).map { MCPLine(name: k, status: $0) } }
                .sorted { (order.firstIndex(of: $0.name) ?? 9, $0.name) < (order.firstIndex(of: $1.name) ?? 9, $1.name) }
        }
    }

    /// How many sources can start now, and how many wait on a switch.
    var startCounts: (now: Int, disk: Int, browser: Int) {
        var now = 0, disk = 0, browser = 0
        for id in engine.order {
            switch Catalog.info(id).via {
            case .open: now += 1
            case .locked: if access { now += 1 } else { disk += 1 }
            case .browser: if browserOn { now += 1 } else { browser += 1 }
            case .archive: break
            }
        }
        return (now, disk, browser)
    }

    /// Looks at the switches again. On the reading screen, a source that was locked starts by itself once its switch is on.
    func pollSwitches(deep: Bool) {
        guard !activity.frozen else { return }
        access = Access.fullDisk
        if deep, !browserOn { requests.refresh(); loadBridge() }
        // the browser switch came on after the signed-in sources were tried: they are read now, once
        if step == .reading, !engine.syncing, signedIn == .done, browserOn, !browserTried {
            browserTried = true
            if AppModel.daily.contains(where: { if case .skipped = engine.state($0) { return Blocked.inBrowser.contains($0) } else { return false } }) { readSignedIn(again: true) }
        }
        guard step == .reading, access, !engine.syncing else { return }
        for id in engine.order where !engine.running.contains(id) && !retried.contains(id) {
            let why: String? = { switch engine.state(id) { case .skipped(let w), .kept(_, let w): return w; default: return nil } }()
            if let why, Blocked(why, Catalog.info(id)).fix == .settings {
                retried.insert(id)
                engine.readRun.remove(id)
                engine.read(id)
            }
        }
    }

    /// Brings up the macos "context wants to control ..." pop-ups, one after another.
    func askAutomation() {
        guard !askingAutomation, !activity.frozen else { return }
        askingAutomation = true
        DispatchQueue.global(qos: .userInitiated).async {
            for (bundle, _) in AppModel.automated {
                let g = Automation.ask(bundle)
                DispatchQueue.main.async { self.automation[bundle] = g }
            }
            DispatchQueue.main.async { self.askingAutomation = false }
        }
    }

    /// Looks, without asking, at what is already allowed.
    func pollPermissions() {
        guard !activity.frozen else { return }
        access = Access.fullDisk
        activity.trusted = AXIsProcessTrusted()
        if !askingAutomation {
            DispatchQueue.global(qos: .utility).async {
                let found = AppModel.automated.map { ($0.0, Automation.status($0.0)) }
                DispatchQueue.main.async { for (b, g) in found where g != .off || self.automation[b] == nil { self.automation[b] = g } }
            }
        }
    }

    func show(_ nudge: Nudge) {
        guard !nudge.query.isEmpty else { return }
        tab = .home
        ask.exact = true                  // "show me": the rows themselves, by their exact words
        ask.query = nudge.query
        focusAsk += 1
    }

    // MARK: onboarding

    var steps: [Step] { [.welcome, .reading] }
    var step: Step { stepIndex == 0 ? .welcome : .reading }

    func advance() {
        switch step {
        case .welcome: startReading()
        case .reading: if detail != nil { detail = nil } else { finishOnboarding() }
        }
    }

    func back() { detail = nil }

    /// Opens one source's own live view.
    func jump(to id: String) { detail = id }

    /// Everything that is switched on is fetched from here on without them, all at once: one collector run for
    /// what is on this mac. Whatever is off waits, and starts by itself when its switch comes on.
    func startReading() {
        started = true
        seen = []
        retried = []
        browserTried = browserOn
        detail = nil
        signedIn = .notYet
        readingSince = Date()
        readingDone = nil
        if !engine.syncing { engine.sync() }
        pinger.start()
        stepIndex = 1
    }

    func go(_ step: Step) { stepIndex = step == .welcome ? 0 : 1 }

    /// The collector finished. Count what it found; if nobody was watching, wait on the summary. In first run the
    /// sources read where the owner is signed in come next, by themselves: they are the daily tier, run once now.
    private func collected() {
        if signedIn == .reading { signedIn = .done; return }
        if readingSince != nil, readingDone == nil {
            readingDone = Date()
            pinger.finished("read", text: "the first read of this mac is done: \(Words.count(engine.totalRows)) rows", fix: .window)
            if !saved.onboarded { readSignedIn() }
        }
    }

    enum SignedIn { case notYet, reading, done }

    /// The sources this app reads in a signed-in tab, from the calendar app and through telegram, in the daily tier.
    static let daily = ["slack", "gdrive", "calendar", "telegram", "x_bookmarks"]

    /// Runs the daily tier now: once after the first read of what is on disk, and again when the owner asks for it.
    func readSignedIn(again: Bool = false) {
        guard !engine.syncing, !activity.frozen, again || signedIn == .notYet else { return }
        signedIn = .reading
        engine.sync(tick: true, tier: "daily")
        if !engine.syncing { signedIn = .done }
    }

    /// Asks the engine which signed-in plan it would use. Slow, so it runs off the main thread, at launch and on demand.
    func loadPlan() {
        engine.json(["model"], timeout: 40) { [weak self] obj in
            if let obj { self?.plan = ModelPlan(obj) }
        }
    }

    /// Exact-word search, asked for by name (cmd F, or the link on the sources tab). Never the default.
    func exactSearch() {
        guard saved.onboarded else { return }
        tab = .home
        ask.closePanel()
        ask.exact = true
        focusAsk += 1
    }

    func closeAdd() {
        adding?.cancel()
        adding = nil
        addHidden = false
        loadPending()       // a trial that was saved and then left is listed on the sources page, not lost
        focusAsk += 1
    }

    /// "+ add": the panel belongs to the sources page, and is only ever shown there.
    func openAdd() {
        guard saved.onboarded else { return }
        if tab != .sources { tab = .sources }
        addHidden = false
        if adding == nil { adding = AddModel(engine: engine) }
    }

    /// The add panel is on screen and has the keys.
    var addShown: Bool { adding != nil && !addHidden && tab == .sources }

    /// The owner went somewhere: nothing that was laid over the page the owner left may stay over the next one, or keep its keys.
    /// A source being worked out is not stopped; it goes to the corner, where it can be opened again.
    func dismissOverlays() {
        if let add = adding, !addHidden {
            if add.stage == .working { addHidden = true } else { add.cancel(); adding = nil }
        }
        if people.open != nil { people.close() }
        if ask.thread != nil { ask.closeThread() }
        if wiki.card != nil { wiki.card = nil }
        if wiki.building, tab != .profile { wiki.building = false }
        if ask.peek != nil { ask.peek = nil }
        if shelfFocus != nil { shelfFocus = nil }
        // a field that had the cursor is gone with its page: the keys go back to the app
        if chatSearch == nil, renaming == nil, sideTyping { sideTyping = false }
    }

    /// `python3 -m ctx bridge --status`: is the browser extension connected.
    func loadBridge() {
        engine.json(["bridge", "--status"], timeout: 20) { [weak self] obj in
            if let c = obj?["connected"] as? Bool { self?.bridge = c }
        }
    }

    func loadFacts() {
        engine.json(["facts"], timeout: 120) { [weak self] obj in
            guard let self else { return }
            self.facts = Facts(obj, engine: self.engine)
        }
    }

    func finishOnboarding() {
        Tick.play()
        saved.onboarded = true
        persist()
        tab = .home
        lastTick = Date()          // setup has just read everything
        startWatching()
    }

    /// "run setup again": straight to the live list, reading everything once more.
    func restartOnboarding() {
        saved.onboarded = false
        persist()
        startReading()
    }

    // MARK: keys

    /// Returns true when the key was used. `typing` is true while a text field has the cursor.
    func key(_ e: NSEvent, typing: Bool, endEditing: () -> Void) -> Bool {
        let mods = e.modifierFlags.intersection([.command, .option, .control])
        guard mods.isEmpty else { return false }
        let code = e.keyCode
        let ret = code == 36 || code == 76, esc = code == 53
        let up = code == 126, down = code == 125, left = code == 123, right = code == 124
        let ch = typing ? "" : (e.charactersIgnoringModifiers?.lowercased() ?? "")
        if !saved.onboarded {
            // 1 opens system settings and 3 looks at the plan again: neither writes anything. the browser's helper (2) and the
            // entries in ai apps' configs (4) are written only by a press on their own labelled buttons, never by a bare key
            if step == .welcome, let n = Int(ch), n == 1 || n == 3 { grant(n); return true }
            if step == .reading, esc, detail != nil { detail = nil; return true }
            if ret || (right && !typing) { advance(); return true }
            if left && !typing { back(); return true }
            return false
        }
        if let add = adding, addShown {             // the add sheet has the keys while it is open, on its own page
            if esc { if add.stage == .working { addHidden = true } else { closeAdd() }; return true }
            if add.stage == .note, !esc { return false }      // the page the owner is writing on has every key but esc
            if down { add.move(1); return true }
            if up { add.move(-1); return true }
            if ret {
                switch add.stage {
                case .search: add.pick()
                case .result(let r):
                    if r.state == "ready" { add.add() } else if r.state == "needs_you" { add.again() } else { add.back() }
                case .added, .unavailable: closeAdd()
                case .note: return false
                case .working: break
                }
                return true
            }
            return false
        }
        switch tab {
        case .home:
            // exact-word search, which the owner asked for by name: the arrows walk the rows, return opens one, esc leaves
            guard ask.exact else { return false }
            if down { ask.move(1); return true }
            if up { ask.move(-1); return true }
            if ret { ask.open(); return true }
            if esc { let used = ask.close(); if !ask.exact { focusAsk += 1 }; return used }
        case .sources:
            if typing { return false }                  // the arrows walk the shelf
            if right { shelfMove(1); return true }
            if left { shelfMove(-1); return true }
            if ret, let f = shelfFocus, let item = shelf.flatMap(\.items).first(where: { $0.id == f }) { shelfAct(item); return true }
            if esc, shelfFocus != nil { shelfFocus = nil; return true }
        case .plan, .settings, .profile, .teach, .made:
            break
        }
        return false
    }

    /// Every key pressed in the main window comes through here first. True when it was used.
    func windowKey(_ e: NSEvent, field: NSTextView?, endEditing: () -> Void) -> Bool {
        let typing = field != nil
        guard saved.onboarded else { return key(e, typing: typing, endEditing: endEditing) }
        let code = e.keyCode
        let mods = e.modifierFlags.intersection([.command, .option, .control, .shift])
        if people.open != nil, code == 53, mods.isEmpty, !sideTyping, renaming == nil { people.close(); return true }
        if tab == .profile, wiki.card != nil, code == 53, mods.isEmpty, !sideTyping { wiki.card = nil; return true }
        // the sidebar's own fields: esc puts them away; everything else is theirs
        if sideTyping || renaming != nil {
            if code == 53, mods.isEmpty {
                if renaming != nil { renaming = nil; sideTyping = false } else if chatSearch != nil { endSearch() } else { sideTyping = false; endEditing() }
                focusAsk += 1
                return true
            }
            return false
        }
        if tab == .home, !ask.exact {
            // shift-return is a new line in the input; return alone sends
            if (code == 36 || code == 76), mods == [.shift], let field {
                field.insertNewlineIgnoringFieldEditor(nil)
                return true
            }
            if ask.chatKey(e, engine) { return true }
            if code == 53, mods.isEmpty, chatSearch != nil { endSearch(); return true }
            return false
        }
        if ask.thread != nil, ask.threadKey(e, engine) { return true }
        return key(e, typing: typing, endEditing: endEditing)
    }

    // MARK: development switches, used to take the screenshots

    private func debugSetup() {
        let env = ProcessInfo.processInfo.environment
        guard let d = env["CONTEXT_DEBUG"] else { return }
        for part in d.split(separator: ",") {
            let kv = part.split(separator: "=", maxSplits: 1).map(String.init)
            switch kv[0] {
            case "main": saved.onboarded = true
            case "onboarding": saved.onboarded = false
            case "tab": tab = Tab.allCases.first { $0.word == kv.last } ?? .home; saved.onboarded = true
            case "query":
                let q = kv.last ?? ""
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { self.ask.query = q.replacingOccurrences(of: "+", with: " ") }
            case "answer": DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) { self.ask.ask(self.engine, self.ask.query); self.ask.query = "" }
            case "open": DispatchQueue.main.asyncAfter(deadline: .now() + 1.4) { self.ask.open() }
            case "step": stepIndex = Int(kv.last ?? "") ?? 0
            case "at":       // at=reading, at=source:whatsapp (that source's own view)
                let want = kv.last ?? ""
                DispatchQueue.main.asyncAfter(deadline: .now() + (d.contains("read") ? 1.0 : 0.3)) {
                    if want.hasPrefix("source:") { self.stepIndex = 1; self.detail = String(want.dropFirst(7)) } else if want == "reading" { self.stepIndex = 1 }
                }
            case "facts": started = true; loadFacts()
            case "away": awayRead = true
            case "want": wanted = Set((kv.last ?? "").split(separator: "+").map(String.init))
            case "busy": requests.busy.insert(kv.last ?? "")
            case "read": DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) { self.startReading() }
            case "still": activity.frozen = true; activity.trusted = true   // keep the seeded timeline as it is
            case "pill": saved.pill = true
            default: break
            }
        }
    }
}
