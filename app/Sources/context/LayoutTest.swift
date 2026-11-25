import AppKit
import SwiftUI

/// `context --layouttest [folder]` lays every screen out off screen, at three window sizes, filled with awkward
/// content, and checks the numbers: no text cut off, no rows on top of each other, nothing outside the window,
/// buttons at their own size, one left edge, setup headings at one height. With a folder it also writes a render
/// of each screen, light and dark, and two contact sheets. It reads no real data and shows nothing on screen.
enum LayoutTest {
    static let sizes: [(String, CGSize)] = [("920x640", CGSize(width: 920, height: 640)), ("smallest", CGSize(width: 760, height: 540)),
                                            ("large", CGSize(width: 1400, height: 900))]
    static var failures: [String] = []

    /// The sizes this run lays out, as plain lists of names and numbers. Kept out of line and free of tuples and of
    /// CGSize: built in place as an array of sizes, the optimised build handed the loop nonsense (and before that,
    /// as an array of tuples, crashed with exit 138).
    @inline(never) static func wanted() -> (names: [String], wide: [Double], high: [Double]) {
        let asked: [Int] = (ProcessInfo.processInfo.environment["CONTEXT_LAYOUT_SIZE"] ?? "").components(separatedBy: "x").compactMap { Int($0.trimmingCharacters(in: .whitespaces)) }
        if asked.count == 2, asked[0] >= 300, asked[1] >= 200 { return (["920x640"], [Double(asked[0])], [Double(asked[1])]) }
        return (sizes.map { $0.0 }, sizes.map { Double($0.1.width) }, sizes.map { Double($0.1.height) })
    }
    static var heads: [String: [String: CGFloat]] = [:]      // size -> screen -> y of the setup label

    static func pump(_ seconds: Double) { RunLoop.current.run(until: Date().addingTimeInterval(seconds)) }

    static func run(out: String?) -> Never {
        let tmp = NSTemporaryDirectory() + "context-layouttest-\(ProcessInfo.processInfo.processIdentifier)"
        setenv("CONTEXT_DEBUG", "still,layout", 1)       // in-memory state, frozen clock sources, no engine
        setenv("CTX_HOME", tmp, 1)
        setenv("CONTEXT_REPO", "/nonexistent", 1)
        Probe.on = true
        let app = NSApplication.shared
        app.setActivationPolicy(.prohibited)
        // swiftui builds what voiceover reads only once something asks for it: ask, so the check below has a tree to read
        _ = app.accessibilityChildren()
        app.accessibilitySetValue(true, forAttribute: NSAccessibility.Attribute(rawValue: "AXEnhancedUserInterface"))
        DispatchQueue.global().asyncAfter(deadline: .now() + 2700) { print("layout: timed out"); fflush(stdout); _exit(3) }   // never linger
        let model = AppModel.shared
        // this window is never ordered in. the views are laid out and drawn inside it without it reaching the screen
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 920, height: 640),
                              styleMask: [.borderless], backing: .buffered, defer: true)
        window.isReleasedWhenClosed = false
        window.hasShadow = false
        window.ignoresMouseEvents = true
        window.backgroundColor = Ink.paperNS
        if let out { try? FileManager.default.createDirectory(atPath: out, withIntermediateDirectories: true) }
        var shots: [String: [String]] = ["light": [], "dark": []]

        let only = ProcessInfo.processInfo.environment["CONTEXT_LAYOUT_ONLY"] ?? ""      // a name prefix, to look at a few screens
        // CONTEXT_LAYOUT_SIZE=920x1600: that one size only, drawn to the folder, to look at the whole of a page that scrolls
        // or at a screen as the smallest window has it. for looking, not for the gate
        // kept as two plain arrays, a name and a size: with the sizes as an array of tuples swapped for a one-element
        // array, the optimised build crashed in a copy before the first screen (exit 138). the cause was not found;
        // this shape does not do it
        let wanted = LayoutTest.wanted()
        let sizeNames = wanted.names, sizeWide = wanted.wide, sizeHigh = wanted.high
        for (name, setUp) in scenarios(model) where name.hasPrefix(only) {
            // each screen in a pool of its own: the views of one are let go before the next is built. without it
            // every screen ever drawn is kept until the end, and past four hundred of them swiftui runs out of room
            for k in sizeNames.indices { autoreleasepool {
                // read here, inside the pool's closure: captured from outside it, the size arrived as nonsense in the optimised build
                let sizeName = sizeNames[k]
                let size = CGSize(width: CGFloat(sizeWide[k]), height: CGFloat(sizeHigh[k]))
                // said before it is laid out, unbuffered: if a screen crashes the layout, the last line names it
                FileHandle.standardError.write("laying out \(name) @ \(sizeName)\n".data(using: .utf8)!)
                app.appearance = NSAppearance(named: .aqua)
                window.contentView = nil          // the screen before must not react to the next one being set up
                setUp()
                window.setContentSize(size)
                Probe.found = []
                let host = NSHostingView(rootView: AnyView(RootView().environment(model).transaction { $0.disablesAnimations = true }))
                window.contentView = host
                host.layoutSubtreeIfNeeded()
                pump(0.25)
                host.layoutSubtreeIfNeeded()
                pump(0.25)
                check(name, sizeName, size)
                if sizeName == "920x640" {
                    let ax = unlabeled(host)
                    controlsSeen += ax.controls
                    for f in Set(ax.faults) { failures.append("\(name): \(f)") }
                    if ProcessInfo.processInfo.environment["CONTEXT_AX_DUMP"] != nil { FileHandle.standardError.write("ax said \(name): \(ax.said.joined(separator: " | "))\n".data(using: .utf8)!) }
                    // the picture buttons, by the names they must answer to
                    let wanted: [String: [String]] = ["chat-one": ["hide sidebar", "new chat", "add scope", "send", "good answer", "not right", "ask again", "sources panel", "copy"],
                                                      "chat-collapsed": ["show sidebar", "new chat"], "person-full-names": ["Sam Okafor", "Ines Marchetti", "Maya Lindqvist's"]]
                    for w in wanted[name] ?? [] where !ax.said.contains(w) { failures.append("\(name): no control answers to \u{201C}\(w)\u{201D}") }
                    if name == "person-full-names", ax.said.contains(where: { ["Sam", "Okafor", "Ines", "Marchetti"].contains($0) }) { failures.append("\(name): half of a name is a control of its own") }
                    FileHandle.standardError.write("ax \(name): \(ax.controls) controls, \(ax.faults.count) unlabeled\n".data(using: .utf8)!)
                }
                if Screen.ours() > 0 { failures.append("\(name) @ \(sizeName): a window of the test is on screen") }
                if let out, sizeName == "920x640" {
                    for mode in ["light", "dark"] {
                        if mode == "dark" {
                            // a dark mac draws every screen dark from its first frame: build the screen again under the
                            // dark appearance, as the app would, and do not wait for a switch to land
                            app.appearance = NSAppearance(named: .darkAqua)
                            let dark = NSHostingView(rootView: AnyView(RootView().environment(model).transaction { $0.disablesAnimations = true }))
                            dark.appearance = NSAppearance(named: .darkAqua)
                            (window.contentView as? NSHostingView<AnyView>)?.rootView = AnyView(EmptyView())
                            window.contentView = dark
                            dark.layoutSubtreeIfNeeded()
                            pump(0.25)
                        }
                        let path = "\(out)/\(name)-\(mode).png"
                        // drawn, and if the ground is not the scheme's own, given a moment and drawn once more:
                        // a slow machine can capture before the first dark frame. a second wrong ground is a real fault
                        func ground(_ rep: NSBitmapImageRep) -> (wrong: Int, of: Int) {
                            let w = rep.pixelsWide, h = rep.pixelsHigh
                            let lit = [(3, 3), (w - 4, 3), (3, h - 4), (w - 4, h - 4), (w / 2, 3), (w / 2, h - 4), (3, h / 2)]
                                .compactMap { rep.colorAt(x: $0.0, y: $0.1)?.usingColorSpace(.deviceRGB)?.brightnessComponent }
                            return (lit.filter { mode == "dark" ? $0 > 0.3 : $0 < 0.7 }.count, lit.count)
                        }
                        func draw() -> NSBitmapImageRep? {
                            guard let v = window.contentView, let rep = v.bitmapImageRepForCachingDisplay(in: v.bounds) else { return nil }
                            v.cacheDisplay(in: v.bounds, to: rep)
                            return rep
                        }
                        var shot = draw()
                        if let r = shot, ground(r).wrong * 2 > ground(r).of { window.contentView?.layoutSubtreeIfNeeded(); pump(1.2); shot = draw() }
                        if let rep = shot {
                            try? rep.representation(using: .png, properties: [:])?.write(to: URL(fileURLWithPath: path))
                            shots[mode]?.append(path)
                            let (wrong, of) = ground(rep)
                            let lit = Array(repeating: 0, count: of)
                            if lit.isEmpty || wrong * 2 > lit.count {
                                failures.append("\(name) @ \(sizeName): the \(mode) render does not have a \(mode) ground")
                            }
                        }
                    }
                }
                // the screen's own graph is emptied before it is let go: a view that is only dropped keeps all it built
                (window.contentView as? NSHostingView<AnyView>)?.rootView = AnyView(EmptyView())
                window.contentView = nil
            } }
        }
        // setup headings share one y
        for (sizeName, ys) in heads {
            let values = Set(ys.values.map { ($0 * 2).rounded() / 2 })
            if values.count > 1 { failures.append("setup @ \(sizeName): headings sit at different heights: \(ys.sorted { $0.key < $1.key }.map { "\($0.key) \($0.value)" }.joined(separator: ", "))") }
        }
        if let out {
            for mode in ["light", "dark"] { sheet(shots[mode] ?? [], to: "\(out)/contact-\(mode).png", dark: mode == "dark") }
            for mode in ["light", "dark"] {       // the chat on its own sheet
                sheet((shots[mode] ?? []).filter { $0.contains("/chat-") }, to: "\(out)/contact-chat-\(mode).png", dark: mode == "dark")
                sheet((shots[mode] ?? []).filter { $0.contains("/frame-") || $0.contains("/home-") }, to: "\(out)/contact-frame-\(mode).png", dark: mode == "dark")
            }
        }
        if only.isEmpty || only == "stranded" { failures += stranded(window, model) }
        if only.isEmpty || "reading".hasPrefix(only) || only.hasPrefix("reading") { failures += wallMotion(window, model, out: out) }
        if only.isEmpty || only == "motion" { failures += pageMotion(window, model, out: out) }
        if only.isEmpty || only == "motion" { failures += motionStrips(window, model, out: out) }
        if let out { menuBarSheet(to: "\(out)/menubar.png") }
        failures += menuBarFaults()
        failures += bannedWords()
        failures += settingsSourceFaults()
        failures += wikiShapeFaults()
        failures += Ink.contrastFaults()
        failures += PingPolicy.faults()
        failures += KeyNav.faults()
        failures += WorkStep.faults()
        failures += MainView.foldFaults()
        // the check above is only worth something if the tree was really there to read
        if only.isEmpty, controlsSeen < 200 { failures.append("accessibility: only \(controlsSeen) controls were found in all screens; the tree was not read") }
        try? FileManager.default.removeItem(atPath: tmp)
        if failures.isEmpty {
            print("layout: \(scenarios(model).count) screens x \(sizeNames.count) sizes, all checks passed")
            exit(0)
        }
        print("layout: \(failures.count) problem\(failures.count == 1 ? "" : "s")")
        failures.forEach { print("  " + $0) }
        exit(1)
    }

    static func check(_ screen: String, _ sizeName: String, _ size: CGSize) {
        let found = Probe.found
        let at = "\(screen) @ \(sizeName)"
        func fail(_ p: ProbeInfo, _ what: String) {
            failures.append("\(at): \(p.name) \(what) (frame \(Int(p.frame.minX)),\(Int(p.frame.minY)) \(Int(p.frame.width))x\(Int(p.frame.height)), wants \(Int(p.ideal.width))x\(Int(p.ideal.height)))")
        }
        if found.isEmpty { failures.append("\(at): nothing was laid out"); return }
        if let dump = ProcessInfo.processInfo.environment["CONTEXT_PROBE_DUMP"] {       // CONTEXT_PROBE_DUMP=<name prefix>: where each probe came to rest
            for p in found where p.name.hasPrefix(dump) { FileHandle.standardError.write("probe \(at): \(p.name) \(Int(p.frame.minX)),\(Int(p.frame.minY)) \(Int(p.frame.width))x\(Int(p.frame.height)) wants \(Int(p.ideal.width))x\(Int(p.ideal.height))\n".data(using: .utf8)!) }
        }
        if found.contains(where: { $0.name == "focus.ring" }) { failures.append("\(at): a focus ring is drawn though no key was pressed") }
        for p in found {
            if p.frame.width < 1 || p.frame.height < 1 { fail(p, "has no room at all"); continue }
            switch p.kind {
            case .text: if p.ideal.height > p.frame.height + 1 { fail(p, "is cut off") }
            case .line: if p.ideal.width > p.frame.width + 1 { fail(p, "is truncated") }
            case .button: if p.ideal.width > p.frame.width + 1 || p.ideal.height > p.frame.height + 1 { fail(p, "is squeezed") }
            case .block, .edge: break
            }
            if p.frame.minX < -0.5 || p.frame.maxX > size.width + 0.5 { fail(p, "runs past the side of the window") }
            if !p.scrolls, p.kind != .button, p.frame.minY < -0.5 || p.frame.maxY > size.height + 0.5 { fail(p, "runs past the top or bottom of the window") }
        }
        let groups = Dictionary(grouping: found.filter { !$0.group.isEmpty }, by: \.group)
        for (g, members) in groups {
            if members.first?.kind == .edge {
                let xs = members.map(\.frame.minX)
                if let lo = xs.min(), let hi = xs.max(), hi - lo > 1 {
                    failures.append("\(at): \(g) is not one left edge: " + members.map { "\($0.name) \(Int($0.frame.minX))" }.joined(separator: ", "))
                }
                continue
            }
            for i in members.indices {
                for j in members.indices where j > i {
                    let a = members[i].frame, b = members[j].frame
                    let x = a.intersection(b)
                    if !x.isNull, x.width > 1, x.height > 1 {
                        failures.append("\(at): \(members[i].name) and \(members[j].name) overlap by \(Int(x.width))x\(Int(x.height)) in \(g)")
                    }
                }
            }
        }
        // the frame: nothing of the page lies under the sidebar or the sources panel, and the bar has a ground across the main area
        if let side = found.first(where: { $0.name == "side.ground" }) {
            for p in found where !p.name.hasPrefix("side.") && p.name != "bar.item" && p.frame.minX < side.frame.maxX - 0.5 && p.frame.width > 0 {
                fail(p, "lies under the sidebar, which ends at \(Int(side.frame.maxX))")
            }
            for p in found where p.name.hasPrefix("side.") && p.frame.maxX > side.frame.maxX + 0.5 { fail(p, "runs out of the sidebar") }
        }
        if let refs = found.first(where: { $0.name == "refs.panel" }) {
            for p in found where !p.name.hasPrefix("refs.") && !p.name.hasPrefix("peek.") && p.name != "bar.item" && p.name != "chat.cell" && p.frame.maxX > refs.frame.minX + 0.5 && p.frame.minX < refs.frame.minX - 0.5 && p.frame.width > 0 {
                fail(p, "lies under the sources panel, which starts at \(Int(refs.frame.minX))")
            }
            for p in found where (p.name.hasPrefix("refs.") || p.name.hasPrefix("peek.")) && p.frame.minX < refs.frame.minX - 0.5 { fail(p, "runs out of the sources panel") }
            if refs.frame.minX < 400 { failures.append("\(at): the sources panel leaves the conversation \(Int(refs.frame.minX)) points") }
        }
        if AppModel.shared.saved.onboarded, AppModel.shared.panelProof == nil, AppModel.shared.pingProof == nil, !AppModel.shared.popoverProof {
            if let ground = found.first(where: { $0.name == "bar.ground" }) {
                // what lives in a scroll view may have been scrolled up under the bar, which is what the ground is for
                for p in found where !p.scrolls && !p.name.hasPrefix("bar.") && !p.name.hasPrefix("side.") && !p.name.hasPrefix("refs.") && !p.name.hasPrefix("peek.")
                    && p.frame.height > 0 && p.frame.minY < ground.frame.maxY - 0.5 && p.frame.maxY > 0.5 {
                    fail(p, "starts under the top bar, which ends at \(Int(ground.frame.maxY))")
                }
            } else {
                failures.append("\(at): the main area has no bar")
            }
        }
        // the popover: everything in it lies inside its own 16 pt margin
        if let pop = found.first(where: { $0.name == "pop.panel" }) {
            for p in found where p.name.hasPrefix("pop.") && p.name != "pop.panel" && (p.frame.minX < pop.frame.minX + 15 || p.frame.maxX > pop.frame.maxX - 15) {
                fail(p, "runs into the popover's margin, which is \(Int(pop.frame.minX + 16)) to \(Int(pop.frame.maxX - 16))")
            }
        }
        failures += settingsCheck(screen, at, size, found)
        failures += lineCheck(screen, at, size, found)
        failures += teachCheck(screen, at, size, found)
        failures += madeCheck(screen, at, size, found)
        failures += exportCheck(screen, at, found)
        failures += keyCheck(screen, at, found)
        failures += ownCheck(screen, at, found)
        failures += guardCheck(screen, at, found)
        if screen == "panel-typing", found.contains(where: { $0.name == "panel.row" }) { failures.append("\(at): the panel shows rows while the owner types") }
        failures += chatCheck(screen, at, size, found)
        failures += wallCheck(screen, at, found)
        failures += wikiCheck(screen, at, size, found)
        if screen.hasPrefix("setup"), let label = found.first(where: { $0.name == "head.label" }) {
            heads[sizeName, default: [:]][screen] = label.frame.minY
        }
    }

    /// Each thing that can be laid over a page, opened, and then every way of going somewhere else taken: it must be
    /// gone, the keys must be the app's again, and the page the owner went to must be the one drawn.
    static func stranded(_ window: NSWindow, _ m: AppModel) -> [String] {
        var out: [String] = []
        let all = scenarios(m)
        func set(_ name: String) { all.first { $0.0 == name }?.1() }
        func lay() -> [ProbeInfo] { autoreleasepool { layNow() } }
        func layNow() -> [ProbeInfo] {
            (window.contentView as? NSHostingView<AnyView>)?.rootView = AnyView(EmptyView())
            window.contentView = nil
            window.setContentSize(CGSize(width: 920, height: 640))
            Probe.found = []
            let host = NSHostingView(rootView: AnyView(RootView().environment(m).transaction { $0.disablesAnimations = true }))
            window.contentView = host
            host.layoutSubtreeIfNeeded()
            pump(0.2)
            host.layoutSubtreeIfNeeded()
            pump(0.1)
            return Probe.found
        }
        let overlays: [(String, String)] = [("add-search", "the add panel"), ("add-nothing", "the add panel with nothing found"), ("add-kinds", "the add panel with rows"),
                                            ("add-working", "the add panel at work"), ("add-ready", "the add panel with a result"), ("add-note", "the add panel with a note being written"), ("add-site-ask", "the add panel asking which part"), ("person-open", "a person's page"),
                                            ("person-from-profile", "a person's page over about you"), ("chat-thread", "a message in its conversation"),
                                            ("wiki-ref-card", "a conversation's card"), ("wiki-ref-row", "a message opened from the wiki"), ("wiki-filter", "the wiki's filter")]
        let ways: [(String, [String], () -> Void)] = [
            ("home", ["home.greeting", "chat.input"], { m.go(.home) }), ("plan", ["plan.day"], { m.go(.plan) }), ("sources", ["sources.heading"], { m.go(.sources) }),
            ("settings", ["setting.row"], { m.go(.settings) }), ("about you", ["profile.heading", "wiki.title"], { m.go(.profile) }),
            ("new chat", ["chat.input"], { m.newChat() }), ("search chats", ["side.search"], { m.searchChats() })]
        for (name, what) in overlays {
            for (to, marks, go) in ways {
                FileHandle.standardError.write("stranded \(name) -> \(to)\n".data(using: .utf8)!)
                set(name)
                if name == "wiki-filter" { m.sideTyping = true }
                go()
                let found = lay()
                let at = "\(what), then \(to)"
                func has(_ n: String) -> Bool { found.contains { $0.name == n } }
                if has("add.sheet") { out.append("\(at): the add panel is still on the page") }
                if m.adding != nil, !m.addHidden { out.append("\(at): the add panel still holds the keys") }
                if m.people.open != nil || has("refs.person.name") { out.append("\(at): the person's page is still open") }
                if m.wiki.card != nil || has("refs.card.title") { out.append("\(at): the conversation's card is still open") }
                if m.ask.thread != nil || has("peek.card") { out.append("\(at): the message is still open") }
                if m.sideTyping, to != "search chats" { out.append("\(at): a field that is gone still has the keys") }
                if !marks.contains(where: has) { out.append("\(at): the page the owner went to is not what is drawn (no \(marks.joined(separator: " or ")))") }
                // the keys are the app's: esc is not swallowed by something the owner cannot see
                if m.addShown { out.append("\(at): the add panel would take the next key") }
            }
        }
        set("frame-0")
        return out
    }

    /// Everything VoiceOver can land on and press, read from the accessibility tree the screen really has: a button, a
    /// menu or a field that says nothing about itself is a fault. Returns the faults and how many controls it found.
    static func unlabeled(_ root: NSView) -> (faults: [String], controls: Int, said: [String]) {
        var faults: [String] = [], controls = 0, seen = 0, all: [String] = []
        func text(_ o: NSObject, _ name: String) -> String {
            let sel = Selector(name)
            guard o.responds(to: sel), let v = o.perform(sel)?.takeUnretainedValue() else { return "" }
            return (v as? String) ?? (v as? NSAttributedString)?.string ?? ""
        }
        func walk(_ any: Any, _ depth: Int) {
            guard depth < 80, seen < 6000, let o = any as? NSObject else { return }
            seen += 1
            let role = text(o, "accessibilityRole")
            if role == "AXScrollBar" { return }          // the system's own scroller: its parts are not ours to name
            if ["AXButton", "AXMenuButton", "AXPopUpButton", "AXCheckBox", "AXTextField", "AXTextArea", "AXLink", "AXSlider"].contains(role) {
                controls += 1
                let said = [text(o, "accessibilityLabel"), text(o, "accessibilityTitle"), text(o, "accessibilityPlaceholderValue"), role.hasPrefix("AXText") ? text(o, "accessibilityValue") : ""]
                    .joined().trimmingCharacters(in: .whitespacesAndNewlines)
                all.append(text(o, "accessibilityLabel").isEmpty ? said : text(o, "accessibilityLabel"))
                // a symbol's own name ("square.and.pencil") is what an unnamed picture button says: not words
                if !said.isEmpty, !said.contains(" "), said.contains("."), said == said.lowercased(), said.count > 5, !said.contains("/"), role != "AXLink", !role.hasPrefix("AXText") { faults.append("a control that says a symbol's name: \(said)") }
                // what macos calls the picture ("compose", "split view horizontally left", "like") is not a name for what the button does
                if !said.isEmpty, pictureWords.contains(said.lowercased()), !role.hasPrefix("AXText") { faults.append("a control that says only its picture's name: \(said)") }
                if said.isEmpty {
                    // where it is in the window, so it can be found: from the left, from the top
                    var at = ""
                    let fs = Selector(("accessibilityFrame"))
                    if o.responds(to: fs), let m = o.method(for: fs) {
                        typealias F = @convention(c) (AnyObject, Selector) -> NSRect
                        let r = unsafeBitCast(m, to: F.self)(o, fs)
                        at = " \(Int(r.width))x\(Int(r.height)) at \(Int(r.minX)),\(Int(r.minY)) from the screen's lower left"
                    }
                    faults.append("a control with nothing for voiceover to say (\(role)\(at)\(text(o, "accessibilityHelp").isEmpty ? "" : ", help: " + text(o, "accessibilityHelp").prefix(40)))")
                }
            }
            let sel = Selector(("accessibilityChildren"))
            if o.responds(to: sel), let kids = o.perform(sel)?.takeUnretainedValue() as? [Any] { kids.forEach { walk($0, depth + 1) } }
        }
        walk(root, 0)
        return (faults, controls, all)
    }
    static var controlsSeen = 0

    /// What macos would say for each symbol the app draws, in lower case: "compose" for square.and.pencil, "add" for
    /// plus. The symbols are read out of the sources when they are there (every quoted word that names a symbol), so a
    /// new one is covered the day it is written; the list below is for a build with no sources beside it.
    static let pictureWords: Set<String> = {
        var names: Set<String> = ["plus", "arrow.up", "sidebar.left", "sidebar.right", "square.and.pencil", "hand.thumbsup", "hand.thumbsup.fill", "hand.thumbsdown",
                                  "hand.thumbsdown.fill", "arrow.clockwise", "doc.on.doc", "number", "text.badge.plus", "xmark", "chevron.left", "chevron.down", "stop.fill",
                                  "magnifyingglass", "pin.fill", "pin", "pencil", "trash", "gearshape", "tray.full", "person.text.rectangle", "text.alignleft", "checkmark",
                                  "arrow.up.right", "person", "calendar", "link", "bookmark", "doc.text", "sun.max", "circle.dotted", "bubble.left.and.bubble.right"]
        let dir = LayoutTest.sourcesDir
        if let files = try? FileManager.default.contentsOfDirectory(at: dir, includingPropertiesForKeys: nil), let quoted = try? NSRegularExpression(pattern: "(?:systemName: |symbol: |act\\(|tool\\(|round\\(|\\? )\"([a-z0-9]+(\\.[a-z0-9]+)*)\"") {
            for f in files where f.pathExtension == "swift" {
                guard let text = try? String(contentsOf: f, encoding: .utf8) else { continue }
                for m in quoted.matches(in: text, range: NSRange(text.startIndex..., in: text)) {
                    if let r = Range(m.range(at: 1), in: text) { names.insert(String(text[r])) }
                }
            }
        }
        var out = Set<String>()
        for n in names {
            guard let said = NSImage(systemSymbolName: n, accessibilityDescription: nil)?.accessibilityDescription?.lowercased(), !said.isEmpty else { continue }
            out.insert(said)
        }
        // words that are both a picture's name and the honest name of our own control
        return out.subtracting(["search", "settings", "copy", "close", "back", "stop", "send", "plan", "sources", "person", "people", "calendar", "link", "open", "done", "pin", "delete", "rename", "home", "more", "show", "hide", "connect", "share", "play", "pause", "edit", "save"])
    }()

    /// A grid of the renders with their names, for a person or an agent to look over.
    /// Going from one page to another, with animation left on: frames are laid out and drawn 30 to 400 ms after each
    /// change, and at no frame may two pages be in the window at once, nor two names in the bar. A page fading out
    /// under the one fading in reads as two pages printed on each other; the page before is cut and the next arrives.
    static func pageMotion(_ window: NSWindow, _ m: AppModel, out: String?) -> [String] {
        var more: [String] = []
        scenarios(m).first { $0.0 == "frame-3" }?.1()
        (window.contentView as? NSHostingView<AnyView>)?.rootView = AnyView(EmptyView())
        window.contentView = nil
        window.setContentSize(CGSize(width: 920, height: 640))
        NSApplication.shared.appearance = NSAppearance(named: .aqua)
        Probe.found = []
        Probe.moving = true
        defer { Probe.moving = false }
        let host = NSHostingView(rootView: AnyView(RootView().environment(m)))       // animations on: this is the point
        window.contentView = host
        host.layoutSubtreeIfNeeded()
        pump(0.6)
        let pages: [(String, [String])] = [("home", ["home.greeting"]), ("sources", ["sources.heading"]), ("journal", ["plan.day"]),
                                           ("settings", ["setting.row", "settings.pane"]), ("about you", ["profile.heading", "wiki.title"])]
        let ways: [(String, () -> Void)] = [("sources", { m.go(.sources) }), ("settings", { m.go(.settings) }), ("about you", { m.go(.profile) }),
                                            ("journal", { m.go(.plan) }), ("home", { m.go(.home) })]
        for (to, go) in ways {
            let start = Date()
            go()
            for (i, t) in [0.03, 0.08, 0.14, 0.22, 0.4].enumerated() {
                let wait = t - Date().timeIntervalSince(start)
                pump(max(wait, 0.02))
                host.layoutSubtreeIfNeeded()
                let found = Probe.found
                let at = "going to \(to), \(Int(t * 1000)) ms after"
                let here = pages.filter { p in p.1.contains { n in found.contains { $0.name == n } } }.map(\.0)
                if here.count > 1 { more.append("\(at): two pages are in the window at once (\(here.joined(separator: " and ")))") }
                if i == 4, here != [to] { more.append("\(at): the page drawn is \(here.joined(separator: ", ")), not \(to)") }
                if found.filter({ $0.name == "bar.title" }).count > 1 { more.append("\(at): two names are drawn in the bar") }
                if let out, let rep = host.bitmapImageRepForCachingDisplay(in: host.bounds) {
                    host.cacheDisplay(in: host.bounds, to: rep)
                    try? rep.representation(using: .png, properties: [:])?.write(to: URL(fileURLWithPath: "\(out)/motion-page-\(to.replacingOccurrences(of: " ", with: "-"))-\(i).png"))
                }
            }
        }
        (window.contentView as? NSHostingView<AnyView>)?.rootView = AnyView(EmptyView())
        window.contentView = nil
        return more
    }

    /// The menu-bar mark as the menu bar draws it, on a light bar and a dark one: at rest, with something waiting,
    /// and the eight steps it goes through while work runs out of sight. Each at its own size and four times over.
    static func menuBarSheet(to: String) {
        let marks: [(String, (Bool) -> NSImage)] = [("rest", { _ in LogoMark.menuBarImage() }), ("waiting", { _ in LogoMark.menuBarAttentionImage() })]
            + (0..<8).map { i in ("busy \(i)", { _ in LogoMark.menuBarBusyImage(step: i) }) }
        let cell: CGFloat = 96, bar: CGFloat = 150
        let image = NSImage(size: NSSize(width: CGFloat(marks.count) * cell, height: bar * 2), flipped: true) { _ in
            for (row, dark) in [false, true].enumerated() {
                let y = CGFloat(row) * bar
                (dark ? NSColor(white: 0.13, alpha: 1) : NSColor(white: 0.93, alpha: 1)).setFill()
                NSRect(x: 0, y: y, width: CGFloat(marks.count) * cell, height: bar).fill()
                NSAppearance(named: dark ? .darkAqua : .aqua)?.performAsCurrentDrawingAppearance {
                    for (i, (name, make)) in marks.enumerated() {
                        let img = make(dark), x = CGFloat(i) * cell
                        // a template is drawn in the bar's own text colour, as the menu bar does
                        func put(_ r: NSRect) {
                            if img.isTemplate {
                                let tinted = NSImage(size: r.size, flipped: false) { rr in
                                    img.draw(in: rr)
                                    (dark ? NSColor.white : NSColor.black).set()
                                    rr.fill(using: .sourceAtop)
                                    return true
                                }
                                tinted.draw(in: r, from: .zero, operation: .sourceOver, fraction: 1, respectFlipped: true, hints: nil)
                            } else {
                                img.draw(in: r, from: .zero, operation: .sourceOver, fraction: 1, respectFlipped: true, hints: nil)
                            }
                        }
                        put(NSRect(x: x + 12, y: y + 14, width: 72, height: 72))
                        put(NSRect(x: x + 39, y: y + 98, width: 18, height: 18))
                        (name as NSString).draw(at: NSPoint(x: x + 12, y: y + 124), withAttributes: [
                            .font: NSFont.systemFont(ofSize: 10, weight: .medium), .foregroundColor: dark ? NSColor(white: 0.7, alpha: 1) : NSColor(white: 0.35, alpha: 1)])
                    }
                }
            }
            return true
        }
        if let tiff = image.tiffRepresentation, let rep = NSBitmapImageRep(data: tiff) {
            try? rep.representation(using: .png, properties: [:])?.write(to: URL(fileURLWithPath: to))
        }
    }

    /// The menu-bar mark must not read as a letter: drawn into a bitmap, its left half is the mirror of its right
    /// (an open ring, which is a c, is not), it has ink at both sides, and its middle column holds only the dot.
    static func menuBarFaults() -> [String] {
        let n = 72
        guard let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: n, pixelsHigh: n, bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                                         colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0), let ctx = NSGraphicsContext(bitmapImageRep: rep) else { return ["menu bar: the mark could not be drawn"] }
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = ctx
        LogoMark.menuBarImage().draw(in: NSRect(x: 0, y: 0, width: n, height: n))
        NSGraphicsContext.restoreGraphicsState()
        func ink(_ x: Int, _ y: Int) -> Bool { (rep.colorAt(x: x, y: y)?.alphaComponent ?? 0) > 0.5 }
        var out: [String] = [], uneven = 0, left = 0, right = 0
        for y in 0..<n { for x in 0..<(n / 2) {
            let a = ink(x, y), b = ink(n - 1 - x, y)
            if a != b { uneven += 1 }
            if a { left += 1 }
            if b { right += 1 }
        } }
        if left < 40 || right < 40 { out.append("menu bar: the mark has no ink on one side (\(left) and \(right) points)") }
        if uneven > 24 { out.append("menu bar: the mark is not the same left and right (\(uneven) points differ): it will read as a letter") }
        // above and below the dot the middle is open: a bar there would make it a letter or a box
        if ink(n / 2, 8) || ink(n / 2, n - 9) { out.append("menu bar: the mark is closed at the top or the bottom") }
        if !ink(n / 2, n / 2) { out.append("menu bar: the mark has no dot in the middle") }
        return out
    }

    static func sheet(_ all: [String], to: String, dark: Bool) {
        // a picture has a greatest height: past ninety screens the sheet goes on in a second file, and a third
        if all.count > 90 {
            for (n, from) in stride(from: 0, to: all.count, by: 90).enumerated() {
                sheet(Array(all[from..<min(from + 90, all.count)]), to: n == 0 ? to : to.replacingOccurrences(of: ".png", with: "-\(n + 1).png"), dark: dark)
            }
            return
        }
        let paths = all
        let cols = 3, w: CGFloat = 460, h: CGFloat = 320, pad: CGFloat = 20, label: CGFloat = 24
        let rows = (paths.count + cols - 1) / cols
        let size = NSSize(width: CGFloat(cols) * (w + pad) + pad, height: CGFloat(rows) * (h + label + pad) + pad)
        let image = NSImage(size: size, flipped: true) { rect in
            (dark ? NSColor(white: 0.05, alpha: 1) : NSColor(white: 0.86, alpha: 1)).setFill()
            rect.fill()
            for (i, path) in paths.enumerated() {
                let x = pad + CGFloat(i % cols) * (w + pad), y = pad + CGFloat(i / cols) * (h + label + pad)
                if let img = NSImage(contentsOfFile: path) {
                    img.draw(in: NSRect(x: x, y: y, width: w, height: h), from: .zero, operation: .sourceOver, fraction: 1,
                             respectFlipped: true, hints: nil)
                }
                let name = ((path as NSString).lastPathComponent as NSString).deletingPathExtension
                (name as NSString).draw(at: NSPoint(x: x, y: y + h + 4), withAttributes: [
                    .font: NSFont.systemFont(ofSize: 12, weight: .medium), .foregroundColor: dark ? NSColor.white : NSColor.black])
            }
            return true
        }
        if let tiff = image.tiffRepresentation, let rep = NSBitmapImageRep(data: tiff) {
            try? rep.representation(using: .png, properties: [:])?.write(to: URL(fileURLWithPath: to))
        }
    }

    // MARK: screens, filled with made-up, awkward content

    static let longName = "the allotment committee and friends of the lower field (2026)"
    static let question = "did i ever tell sam whether we are renewing the lease, and what did i say about the deposit?"

    static func cite(_ i: Int, _ thread: String, _ text: String) -> [String: Any] {
        ["id": "W\(i)", "src": i % 2 == 0 ? "whatsapp" : "apple_notes", "ts": "2026-11-\(String(format: "%02d", 3 + i))T10:00:00Z",
         "thread": thread, "who": i % 2 == 0 ? "them" : "me", "text": text]
    }

    static func added(_ e: Engine, _ d: [String: Any]) -> AddModel {
        let a = AddModel(engine: e)
        a.picked = Found(id: d["id"] as? String ?? "", name: d["name"] as? String ?? "", kind: "app", installed: true, iconPath: "", known: false)
        if let r = ConnectResult(d) { a.stage = .result(r) }
        return a
    }

    // MARK: the home shelf and the add sheet (kept apart from the answer screens, which have a file of their own)

    static func shelfScreens(_ m: AppModel, main: @escaping (Tab) -> Void, lenses: [LensInfo]) -> [(String, () -> Void)] {
        let e = m.engine
        return [
            ("sources-shelf-rest", {                                     // 25 sources, six of them waiting on them
                main(.sources)
                m.ask.lenses = lenses
                for id in ["imessage", "safari_history"] { e.states[id] = .skipped("blocked by macOS: grant Full Disk Access") }
                e.states["telegram"] = .skipped("needs setup: python3 -m ctx telegram-login")
                e.states["gdrive"] = .skipped("needs the browser bridge: not connected")
                m.requests.services = m.requests.services.enumerated().map { i, sv in
                    var sv = sv
                    sv.state = [.needsYou, .idle, .requested, .arrived, .declined, .failed][i]
                    return sv
                }
                m.bridge = false
            }),
            ("sources-shelf-focus", { main(.sources); m.ask.lenses = lenses; m.shelfFocus = "email" }),
            ("sources-shelf-full", {                                     // every source read: the most crowded the shelf gets
                main(.sources)
                m.ask.lenses = lenses
                for (i, id) in e.order.enumerated() { e.states[id] = .done(rows: Invented.sizes[i % 4], secs: 1) }
            }),
        ]
    }

    static func addScreens(_ m: AppModel, main: @escaping (Tab) -> Void) -> [(String, () -> Void)] {
        let e = m.engine
        return [
            ("add-search", { main(.sources); m.adding = AddModel(engine: e) }),
            ("add-results", {
                main(.sources)
                let a = AddModel(engine: e)
                a.results = [("granola", "granola", true), ("linear", "linear", true), ("a_tool_with_a_long_name", "a note-taking tool with quite a long name", false),
                             ("spotify", "spotify", false)].map { Found(id: $0.0, name: $0.1, kind: $0.2 ? "app" : "service", installed: $0.2, iconPath: "", known: true) }
                m.adding = a
            }),
            ("add-working", {
                main(.sources)
                let a = AddModel(engine: e)
                a.picked = Found(id: "granola", name: "granola", kind: "app", installed: true, iconPath: "", known: false)
                a.phases = ["looking at where granola keeps its data on this mac, including its caches"]
                a.stage = .working
                m.adding = a
            }),
            ("add-ready", { main(.sources); m.adding = added(e, ["id": "granola", "name": "granola", "state": "ready",
                "how": "found granola's notes in its app folder: titles, your own notes and the transcript of each meeting", "sample": ["rows": 300, "since": "2024-05"]]) }),
            ("add-needs-you", { main(.sources); m.adding = added(e, ["id": "linear", "name": "linear", "state": "needs_you",
                "detail": "linear keeps nothing on this mac. sign in to linear in your browser, then try again."]) }),
            ("add-cannot", { main(.sources); m.adding = added(e, ["id": "granola", "name": "granola", "state": "cannot", "detail": "its notes are kept encrypted on this mac and only the app itself can open them"]) }),
            ("add-unavailable", { main(.sources); let a = AddModel(engine: e); a.stage = .unavailable; m.adding = a }),
            ("add-site-ask", {                                              // a site tried: what it found, and the engine's question with its choices
                main(.sources)
                let a = AddModel(engine: e)
                a.picked = Found(id: "site:https://marshlane.example/blog", name: "marshlane.example/blog", kind: "site", installed: true, iconPath: "", known: false)
                let ask: [String: Any] = ["question": "Only the posts, or every page?", "choices": [["label": "only the posts", "only": "posts", "pages": 40], ["label": "everything", "only": "all", "pages": 212]]]
                if let r = ConnectResult(["id": "site:https://marshlane.example/blog", "name": "marshlane.example/blog", "kind": "site", "source": "canvas_marshlane_example", "state": "ready",
                                          "how": "read the site's own list of pages and tried the first twelve", "sample": ["rows": 40, "since": "2018"], "ask": ask]) { a.stage = .result(r) }
                m.adding = a
            }),
            ("add-not-built", {                                             // a kind the engine knows by name and cannot read yet: its own sentence
                main(.sources)
                let a = AddModel(engine: e)
                a.picked = Found(id: "repo:lowerfield/plot-planner", name: "lowerfield/plot-planner", kind: "repo", installed: false, iconPath: "", known: false)
                if let r = ConnectResult(["id": "repo:lowerfield/plot-planner", "name": "lowerfield/plot-planner", "kind": "repo", "state": "cannot", "detail": "reading a github repo is not built yet"]) { a.stage = .result(r) }
                m.adding = a
            }),
            ("add-note", {                                                  // their own notes: a page to write on
                main(.sources)
                let a = AddModel(engine: e)
                a.picked = Found(id: "note:marshlane.example", name: "add your own notes about \u{201C}marshlane.example\u{201D}", kind: "note", installed: true, iconPath: "", known: false)
                a.noteLoaded = true
                a.noteText = "the site of the lower field. minutes go up after each meeting; the water rota is a pdf linked from the front page.\n\nask priya for the login."
                a.stage = .note
                m.adding = a
            }),
            ("add-nothing", { main(.sources); let a = AddModel(engine: e); a.query = "marshlane.example"; a.cancel(); a.searching = false; m.adding = a }),     // nothing by that name: it says what can be typed
            ("add-kinds", {                                                 // a website, a feed, a folder, a repo, a channel, and always their own notes
                main(.sources)
                let a = AddModel(engine: e)
                a.query = "marshlane.example"
                a.cancel()
                a.searching = false
                a.results = [("site", "marshlane.example", "reads the pages of this site that you can open, and keeps them up to date"), ("feed", "marshlane.example/feed.xml", "every post in the feed, and new ones as they come"),
                             ("folder", "~/Documents/allotment/minutes and the long folder name after it", "the text of the 250 files in this folder"), ("repo", "lowerfield/plot-planner", "its issues, pull requests and readme"),
                             ("channel", "the lower field on film", "the titles and transcripts of its videos"), ("note", "add your own notes about \u{201C}marshlane.example\u{201D}", "a page you write or paste into")]
                    .map { Found(id: $0.0 + ":x", name: $0.1, kind: $0.0, installed: false, iconPath: "", known: false, what: $0.2) }
                m.adding = a
            }),
        ]
    }

    // MARK: first run (two screens, and a source's own view opened from the list)

    static func onboardingScreens(_ m: AppModel, reset: @escaping () -> Void) -> [(String, () -> Void)] {
        let e = m.engine
        func first() { reset(); m.stepIndex = 0; m.detail = nil; m.mcp = []; m.mcpRunning = false; m.access = false; m.bridge = false; m.askedForAccess = false }
        func reading() {
            reset()
            m.started = true
            m.stepIndex = 1
            m.detail = nil
            m.readingSince = Date().addingTimeInterval(-72)
            m.readingDone = nil
            e.syncing = true
            // 28 sources in every state a row can be in
            for (i, id) in e.order.enumerated() {
                switch i % 7 {
                case 0:
                    e.states[id] = .reading
                    e.live[id] = Invented.reading * (i + 1)
                    e.log[id] = [Sample(rows: Invented.reading * (i + 1), at: Invented.at, label: i == 0 ? LayoutTest.longName + ", and the thread after that one" : "maya okafor", phase: "")]
                case 1: e.states[id] = .done(rows: Invented.sizes[3], secs: 9.6); e.spans[id] = DateSpan(first: Invented.first, last: "2026-11-01")
                case 2: e.states[id] = .skipped("blocked by macOS: grant Full Disk Access")
                case 3: e.states[id] = .kept(rows: Invented.kept, why: "blocked by macOS: grant Full Disk Access")
                case 4: e.states[id] = .skipped("not installed")
                case 5: e.states[id] = .waiting
                default: e.states[id] = .done(rows: Invented.sizes[0], secs: 0.2)
                }
            }
            m.requests.services = m.requests.services.enumerated().map { i, sv in
                var sv = sv
                sv.state = [.idle, .requested, .needsYou, .arrived, .declined, .failed][i % 6]
                sv.detail = i % 6 == 2 ? "google is asking for your password in the tab that just opened" : ""
                return sv
            }
            // what a stranger's mac really has: sources read where the owner is signed in, telegram before its sign-in, a
            // journal with nothing in it (no tile at all), and mail that is slow to show its first row
            m.bridge = false
            m.signedIn = .notYet
            let unread = "yet: python3 -m ctx tick daily reads it from your signed-in browser (docs/PERMISSIONS.md)"
            for id in ["slack", "gdrive", "x_bookmarks", "calendar"] { e.states[id] = .skipped("no imports/\(id).jsonl " + unread); e.live[id] = nil; e.log[id] = nil }
            e.states["telegram"] = .skipped("needs setup: python3 -m venv .venv && .venv/bin/pip install --require-hashes -r requirements-telegram.txt")
            e.order.append("journal")
            e.states["journal"] = .skipped("nothing written in the plan tab yet")
            e.states["email"] = .reading
            e.live["email"] = 0
            e.scanned = ["email": Invented.scanned]
            e.phaseSince = ["email": Date().addingTimeInterval(-48)]
            e.log["email"] = [Sample(rows: 0, at: "", label: "", phase: "found 200,000 emails. working out which address is yours"), Sample(rows: 0, at: "", label: "", phase: "finding the people you write to")]
            e.landed = []
        }
        /// first run's second part: this mac is read, and the signed-in sources are being read
        func signedIn(browser: Bool) {
            reading()
            for id in e.order where e.states[id] == .reading || e.states[id] == .waiting { e.states[id] = .done(rows: Invented.sizes[1], secs: 1.2) }
            m.readingDone = Date().addingTimeInterval(-6)
            m.bridge = browser
            m.signedIn = .reading
        }
        return [
            ("first-off", { first(); m.plan = ModelPlan(["using": "none", "fix": "sign in once: open claude code and type /login"]) }),
            ("first-mixed", {
                first()
                m.access = true
                m.askedForAccess = true
                m.requests.browser = BrowserInfo(name: "a browser with a long name", scripting: false, howToEnable: "run: python3 -m ctx request --enable-browser")
                m.mcpRunning = true
            }),
            ("first-on", {
                first()
                m.models = ModelsReport(modelsReport)
                m.access = true
                m.bridge = true
                m.mcp = [MCPLine(name: "claude desktop", status: "registered"), MCPLine(name: "claude code", status: "already there"),
                         MCPLine(name: "cursor", status: "registered"), MCPLine(name: "codex", status: "skipped: not installed")]
            }),
            ("reading-mixed", { reading() }),
            ("reading-signed-in", { signedIn(browser: true) }),
            ("reading-signed-in-no-browser", { signedIn(browser: false) }),
            ("reading-signed-in-done", {         // the daily tier ran: one source read, one the engine could not read and says why
                signedIn(browser: true)
                e.syncing = false
                m.signedIn = .done
                e.states["slack"] = .done(rows: Invented.signedIn, secs: 31)
                e.spans["slack"] = DateSpan(first: Invented.later, last: "2026-11-01")
                let res: [String: Any] = ["x_bookmarks": ["state": "needs_you", "detail": "x only loads while its window is in front"]]
                let tier: [String: Any] = ["last": 0.0, "due": false, "next_in": 80000.0, "sources": [String](), "results": res]
                e.schedule = Schedule(["fast": tier, "daily": tier])
            }),
            ("reading-done", {
                reading()
                e.syncing = false
                m.readingDone = Date()
                for id in e.order where e.states[id] == .reading || e.states[id] == .waiting { e.states[id] = .done(rows: Invented.sizes[1], secs: 1.2) }
            }),
            ("reading-start", {                 // the collector has only just begun: every tile is in line, none has a figure
                reading()
                for id in e.order { e.states[id] = .waiting }
                e.live = [:]
                e.log = [:]
                m.readingSince = Date().addingTimeInterval(-1)
            }),
            ("reading-zero", {                  // a mac with nothing to read and no exports to ask for
                reading()
                e.order = []
                e.states = [:]
                e.live = [:]
                e.syncing = false
                m.readingDone = Date()
                m.requests.services = []
            }),
            ("reading-one", {
                reading()
                e.order = ["apple_notes"]
                e.states = ["apple_notes": .reading]
                e.live = ["apple_notes": 450]
                e.log = ["apple_notes": [Sample(rows: 450, at: "2018-04", label: "packing list for the lakes", phase: "")]]
                m.requests.services = []
            }),
            ("reading-exports", {               // few sources, so the line over the exports and their tiles are in view
                reading()
                let keep = ["whatsapp", "claude_code", "a_source_with_a_very_long_name"]
                e.order = keep
                e.states = ["whatsapp": .done(rows: Invented.sizes[2], secs: 6), "claude_code": .reading, "a_source_with_a_very_long_name": .done(rows: Invented.sizes[3], secs: 2)]
                e.live = ["claude_code": Invented.trickle]
                e.log = ["claude_code": [Sample(rows: Invented.trickle, at: Invented.at, label: "plot-planner", phase: ""), Sample(rows: Invented.trickle, at: "2026-09", label: "plot-planner", phase: "")]]
                e.spans = ["whatsapp": DateSpan(first: Invented.first, last: "2026-11-01")]
            }),
            ("reading-forty", {                 // forty sources, all read: the last frame of first run
                reading()
                e.order = e.order + (1...12).map { "extra_source_\($0)" }
                e.syncing = false
                m.readingSince = Date().addingTimeInterval(-192)
                m.readingDone = Date()
                for (i, id) in e.order.enumerated() {
                    e.states[id] = .done(rows: (Invented.sizes + [0])[i % 5], secs: 1)
                    e.spans[id] = DateSpan(first: "20\(String(format: "%02d", 12 + i % 13))-04-01", last: "2026-11-01")
                }
                m.requests.services = m.requests.services.map { var sv = $0; sv.state = .arrived; return sv }
            }),
            ("reading-detail", {
                reading()
                m.detail = "whatsapp"
                e.states["whatsapp"] = .reading
                e.log["whatsapp"] = (1...8).map { Sample(rows: $0 * 6_000, at: "202\\($0 % 5 + 1)-0\\($0)", label: $0 % 2 == 0 ? LayoutTest.longName : "maya okafor", phase: "") }
            }),
            ("reading-detail-kept", {
                reading()
                m.detail = "imessage"
                e.states["imessage"] = .kept(rows: Invented.kept, why: "blocked by macOS: grant Full Disk Access to the app running this")
                m.settled = "imessage"
            }),
        ]
    }

    static func scenarios(_ m: AppModel) -> [(String, () -> Void)] {
        let e = m.engine
        func reset(wide: Bool = true) {
            m.panelProof = nil
            m.pingProof = nil
            m.pending = []; m.pendingBusy = []; m.pendingFault = [:]
            m.popoverProof = false
            m.rules.reset()
            m.made.reset()
            m.journalLines.reset()
            m.exports.reset()
            m.keys.reset()
            WebIcons.proof([])
            m.wiki.paras = [:]; m.wiki.removed = []; m.wiki.gone = []; m.wiki.holding = []; m.wiki.noting = nil
            m.ask.evidenceShown = []
            m.automation = [:]
            m.now.data = nil
            m.ask.pinned = nil; m.ask.hoverPick = nil; m.ask.threadInMargin = false
            m.pinger?.queue = []
            m.saved.pings = PingBook()
            m.card = nil
            m.saved = Saved()
            e.syncing = false
            m.detail = nil
            m.mcp = []
            m.mcpRunning = false
            m.stepIndex = 0
            m.started = false
            m.following = false
            m.settled = nil
            m.wanted = []
            m.facts = nil
            m.awayRead = false
            m.plan = ModelPlan(["using": "claude", "plan": "your claude plan"])
            m.signedIn = .notYet
            m.settingsPane = .general
            ModelsPane.unfolded = false
            AIsPane.unfolded = false
            m.settings.report = ""
            m.settings.reporting = false
            m.wikiBuild.status = nil
            m.wikiBuild.estimate = nil
            m.wikiBuild.estimating = false
            m.wikiBuild.running = false
            m.wikiBuild.paused = false
            m.wikiBuild.progress = nil
            m.wikiBuild.failed = ""
            e.landed = []
            e.scanned = [:]
            e.phaseSince = [:]
            m.models = nil
            m.measuring = false
            // 28 sources: everything in the catalog and three the collector added later
            e.order = Catalog.order + (wide ? ["a_source_with_a_very_long_name", "another_new_source", "third_new_source"] : [])
            e.stepOrder = e.order
            e.states = [:]
            e.log = [:]
            e.live = [:]
            e.spans = [:]
            e.failure = nil
            for (i, id) in e.order.enumerated() {
                // a mix: read, locked, missing, and exports that have not been asked for (the longest words in a cell)
                let archive = Catalog.info(id).via == .archive
                e.states[id] = archive ? .idle : (i % 5 == 3 ? .skipped(i % 2 == 0 ? "not installed" : "blocked by macOS: grant Full Disk Access") : .done(rows: Invented.sizes[1] * (i + 1), secs: 1.2))
                if i % 5 != 3, !archive { e.spans[id] = DateSpan(first: "20\(12 + i % 13)-04-01", last: "2026-11-01") }
            }
            m.requests.browser = BrowserInfo(name: "your browser", scripting: false, howToEnable: "")
            m.requests.services = ["x", "google", "instagram", "linkedin", "chatgpt", "notion"].compactMap {
                Service(["id": $0, "name": $0, "what": "everything you posted and every message, since the day you joined.", "state": "idle",
                         "asks_for": "password", "arrives": "a day"])
            }
            m.ask.exact = false
            m.ask.query = ""
            pump(0.2)
            m.ask.groups = []
            m.ask.wipe()
            m.chatSearch = nil
            m.renaming = nil
            m.sideTyping = false
            m.sideOver = false
            m.ask.follow = true
            m.panelWidth = 340
            m.ask.thread = nil
            m.ask.notice = ""
            m.access = false               // the scenarios say what macos allows; this mac's own setting never decides a check
            m.healed = []
            e.syncing = false
            e.ticking = false
            e.heard = nil
            m.addHidden = false
            m.ask.opened = nil
            m.ask.lenses = []
            m.coach.nudges = []
            m.activity.spans = []
            m.activity.app = ""
            m.activity.title = ""
            m.journal.text = ""
            m.journal.notes = []
            m.journal.relating = false
            e.schedule = nil
            m.bridge = true
            m.adding = nil
            m.shelfFocus = nil
            m.ask.starters = []
            m.ask.starterLenses = nil
            m.people.list = []
            m.people.open = nil
            m.profile.pages = []
            m.profile.cards = 0
            m.profile.wrong = [:]
            m.profile.rebuilding = false
            m.profile.progress = nil
            m.profile.said = ""
            m.profile.cost = nil
            m.profile.page = "core"
            m.wiki.take([])
            m.wiki.page = nil
            m.wiki.briefing = false
            m.wiki.building = false
            m.wiki.filter = ""
            m.wiki.hits = []
            m.wiki.folded = []
            m.wiki.sort = .closeness
            m.wiki.card = nil
            m.tab = .home
        }
        func main(_ tab: Tab) { reset(wide: tab != .home); m.saved.onboarded = true; m.tab = tab }
        let lenses = [("intros", "intros i promised", "people you said you would introduce, and whether you did"),
                      ("tasks", "tasks i owe", "things you told someone you would do"),
                      ("money", "money i agreed to", "money you owe, are owed, or said you would pay or put in"),
                      ("saved", "things i saved", "things you saved to come back to, and what you could do with each")]
            .map { LensInfo(id: $0.0, title: $0.1, about: $0.2) }
        let t = Date().timeIntervalSince1970
        let fastTier: [String: Any] = ["last": t - 360, "due": false, "next_in": 540, "results": [String: Any](),
            "sources": ["whatsapp", "imessage", "claude_code", "codex", "cursor", "grok_bot", "browser_history", "safari_history", "obsidian", "apple_notes"]]
        let dailyResult: [String: Any] = ["state": "needs_you", "detail": "x only loads while its window is in front, and it was behind another window all day"]
        let dailyTier: [String: Any] = ["last": t - 36000, "due": false, "next_in": 50400,
            "sources": ["email", "slack", "gdrive", "telegram", "x_bookmarks"], "results": ["x_bookmarks": dailyResult]]
        let weeklyX: [String: Any] = ["state": "requested", "every": "monthly", "last": 0.0, "due": false, "next_in": 2584800]
        let schedule: [String: Any] = ["fast": fastTier, "daily": dailyTier, "weekly": ["x": weeklyX]]

        var all: [(String, () -> Void)] = [
            ("home-exact", {                                             // exact-word search, asked for by name: the only place a list of matches shows
                main(.home)
                m.ask.exact = true
                m.ask.query = "the lease renewal"
                pump(0.7)                      // let the real search of the empty test folder land before the made-up rows go in
                m.ask.groups = ["whatsapp", "apple_notes", "claude_code"].map { src in
                    HitGroup(src: src, total: Invented.found, more: true, hits: (0..<4).map {
                        Hit(id: "\(src)\($0)", src: src, kind: "message", ts: "2026-11-0\($0 + 1)T10:00:00Z", thread: $0 == 1 ? longName : "sam (landlord)", threadID: "t",
                            who: "them", sender: "sam", text: "x", url: "", offset: 0,
                            snippet: "the lease renewal is due on the first. can you let me know by then whether you are staying, and whether the deposit carries over to the new term?")
                    })
                }
            }),
            ("home-card", {                                              // this morning's card over the starters
                main(.home)
                m.card = Card(["id": "2026-11-17-promised-1", "kind": "promised", "state": "unread",
                               "line": "You told Sam you would come back to him about the lease after checking with the others. That was sixteen days ago, and the renewal is due on the first.",
                               "cite": cite(2, "sam (landlord)", "I will check with the others and come back to you."), "action": ["label": "reply", "thread": "W2"]])
            }),
            ("home-card-done", {
                main(.home)
                var c = Card(["id": "c", "kind": "saved", "line": "You saved a long thread on pricing pages in march and never opened it again.", "action": ["label": "open"]])
                c?.state = "done"
                m.card = c
            }),
            ("home-typing-long", { main(.home); m.ask.homeDraft = question + " " + veryLong; pump(0.25) }),      // a question being typed: the field, and nothing looked up
            ("sources", {
                main(.sources)
                e.schedule = Schedule(schedule)
                e.states["imessage"] = .kept(rows: Invented.kept, why: "blocked by macOS: grant Full Disk Access to the app running this")
                e.states["telegram"] = .skipped("needs setup: python3 -m ctx telegram-login")
            }),
            ("sources-pending", {                                       // two trials that were saved and never switched on, one of them refused just now
                main(.sources)
                e.schedule = Schedule(schedule)
                m.pending = [PendingSource(["id": "allotment_forum", "name": "The Allotment Forum", "kind": "website", "how": "reads the pages you posted on", "created": "2026-11-16T18:04:11Z", "rows": 300, "enabled": false]),
                             PendingSource(["id": "seed_ledger", "name": "A seed ledger with a very long name that someone typed in full", "kind": "folder", "how": "reads the files in it", "created": "2026-11-12T09:30:00Z", "rows": 0, "enabled": false])].compactMap { $0 }
                m.pendingFault["seed_ledger"] = "the folder it was read from is not there any more. add it again from where it is now."
            }),
            ("plan-empty", { main(.plan) }),
            ("plan-writing", {
                main(.plan)
                m.journal.text = "today is the pricing page. the yearly toggle goes on by default and each plan gets one line under the price.\n\n"
                    + "i keep putting off the lease. sam asked twice and i still have not said whether we are staying or what happens to the deposit.\n\n"
                    + "after lunch: proofs, then the checkout bug again.\n"
                m.journal.notes = Journal.notes(from: [
                    ["line": "you already decided this in march: yearly on by default, two months free.", "cite": cite(1, "pricing page outline", "three plans. yearly toggle on by default.")],
                    ["line": "sam's deadline is the first, and he has asked about the deposit as well.", "cite": cite(2, "sam (landlord)", "the lease renewal is due on the first")],
                    ["line": "you fixed this checkout bug six weeks ago: verify the signature on the raw body, before parsing.", "cite": cite(3, "fix stripe webhook signature check", "fixed: verify the signature against the raw request body")]])
            }),
        ]
        // added one by one: a single long sum of these is more than the type checker will work through
        all += onboardingScreens(m, reset: { reset() })
        all += settingsScreens(m, main: main)
        all += shelfScreens(m, main: main, lenses: lenses)
        all += addScreens(m, main: main)
        all += chatScreens(m, main: main)
        all += panelScreens(m, main: main)
        all += frameScreens(m, main: main, lenses: lenses)
        all += sizeScreens(m, main: main)
        all += profileScreens(m, main: main)
        all += peopleScreens(m, main: main)
        all += lastScreens(m, main: main, lenses: lenses)
        all += pingScreens(m, main: main)
        all += wikiScreens(m, main: main)
        all += lineScreens(m, main: main)
        all += teachScreens(m, main: main)
        all += madeScreens(m, main: main)
        all += exportScreens(m, main: main)
        all += keyScreens(m, main: main)
        all += ownScreens(m, main: main)
        all += guardScreens(m, main: main)
        return all
    }
}
