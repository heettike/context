import AppKit

// Made-up numbers for the screens the layout gate draws and the checks beside them. They are round on purpose and
// were measured from nothing: no archive has these counts. A fixture that needs a count or a first day takes it from
// here, so the screens agree with each other.
enum Invented {
    /// rows in a source: a small one, a middling one, a big one, the biggest
    static let sizes = [600, 20_000, 150_000, 900_000]
    static let kept = 30_000          // rows held from last time by a source that cannot be read now
    static let signedIn = 45_000      // a source read through the browser
    static let reading = 16_000       // a source part read
    static let trickle = 3_500        // a small source part read
    static let landed = 55_000        // a source that has just been read
    static let step = 2_500           // what one line of progress adds
    static let scanned = 200_000      // mail found before it is read
    static let found = 1_100          // rows an answer read
    static let thread = 1_700         // rows in one long thread
    static let first = "2012-06-01"   // the earliest day a source goes back to
    static let later = "2020-09-01"   // a source begun later
    static let at = "2025-02"         // the month a collector says it is reading
}

extension LayoutTest {
    /// The app's own sources, for the checks that read them: the folder named by CONTEXT_SOURCES, else Sources/context
    /// under the folder the gate was started in (build.sh starts it in app/). Nothing about the machine that built
    /// the app is kept in the binary; where the sources are not found, those checks have nothing to read.
    static var sourcesDir: URL {
        if let named = ProcessInfo.processInfo.environment["CONTEXT_SOURCES"], !named.isEmpty { return URL(fileURLWithPath: named) }
        return URL(fileURLWithPath: FileManager.default.currentDirectoryPath).appendingPathComponent("Sources/context")
    }
}

// MARK: what context does on its own, and where icons come from: in the gate

extension LayoutTest {
    static func ownScreens(_ m: AppModel, main: @escaping (Tab) -> Void) -> [(String, () -> Void)] {
        func general(_ more: () -> Void = {}) {
            main(.settings); m.settingsPane = .general; m.settings.loaded = true; m.settings.answered = true
            more()
        }
        return [
            ("settings-own", { general() }),                     // as it is on a new mac: nudges off, icons from this mac
            ("settings-own-turned", { general {                  // every switch the other way
                m.saved.nudgeModel = true; m.saved.nameChats = false; m.saved.lookDeeper = false; m.saved.morningCard = false; m.saved.modelCheck = false; m.saved.webIcons = true; m.saved.relatePast = false
                // the two the engine keeps: the weekly re-read on, the nightly catch-up with its budget
                m.settings.raw = ["read_through": ["reread_weekly": true]]
                m.exports.catchup = Catchup(["nightly_calls": 40, "nights_to_catch_up": 3, "may_run_now": false, "why_not": "it is not night yet"])
            } }),
            ("sources-icons-local", { main(.sources) }),         // icons from this mac alone: an app's own, or a letter
            ("sources-icons-fetched", {                          // fetching switched on: a service's mark where there is no app (a drawn square stands in for it here)
                main(.sources); m.saved.webIcons = true
                WebIcons.proof(["instagram", "linkedin", "x", "notion", "google", "chatgpt", "gmail", "drive", "discord"])
            }),
        ]
    }

    static func ownCheck(_ screen: String, _ at: String, _ found: [ProbeInfo]) -> [String] {
        var out: [String] = []
        func count(_ n: String) -> Int { found.filter { $0.name == n }.count }
        let s = AppModel.shared.saved
        switch screen {
        case "settings-own":
            if count("setting.own") != 6 || count("setting.icons") != 1 { out.append("\(at): the things context does on its own are not each a row with a switch, or the icon switch is missing") }
            if s.nudgeModel || s.webIcons { out.append("\(at): a nudge worded by the plan, or fetching icons, is on before the owner switched it on") }
        case "settings-own-turned": if count("setting.own") != 8 || !s.nudgeModel || s.nameChats { out.append("\(at): the switches do not hold what was set") }
        case "sources-icons-fetched": if count("icon.web") == 0 { out.append("\(at): fetching is on and no source wears a fetched mark") }
        default: break
        }
        if screen != "sources-icons-fetched", count("icon.web") > 0 { out.append("\(at): a fetched icon is drawn though fetching is off") }
        return out
    }
}

// MARK: a changed entry in an ai app's config, and an address from someone else's message: in the gate

extension LayoutTest {
    static var bareKeys: [Bool] = []       // whether a bare 2 and a bare 4 were taken on the welcome screen

    static func guardScreens(_ m: AppModel, main: @escaping (Tab) -> Void) -> [(String, () -> Void)] {
        func press(_ ch: String, _ code: UInt16) -> Bool {
            guard let e = NSEvent.keyEvent(with: .keyDown, location: .zero, modifierFlags: [], timestamp: 0, windowNumber: 0, context: nil,
                                           characters: ch, charactersIgnoringModifiers: ch, isARepeat: false, keyCode: code) else { return true }
            return m.key(e, typing: false, endEditing: {})
        }
        return [
            // the welcome screen: a bare 2 or 4 must write nothing into a browser's folder or an ai app's config
            ("first-bare-keys", {
                scenarios(m).first { $0.0 == "first-on" }?.1()
                bareKeys = [press("2", 19), press("4", 21)]
            }),
            // an export tile pressed once: the line says which site will be asked and that it may email, and nothing is sent yet
            ("sources-export-armed", { main(.sources); m.shelfArmed = "export:x"; m.shelfFocus = "export:x" }),
            // the engine's report says links from others are on: the switch shows the engine's word, not the app's copy
            ("settings-links-engine", {
                main(.settings); m.settingsPane = .general; m.settings.loaded = true; m.settings.answered = true
                m.settings.raw = ["links_from_others": "on"]; m.saved.linksFromOthers = false
            }),
            // another program altered what context wrote into an app's config: said in the engine's words, with the way to write it again
            ("settings-ais-changed", {
                main(.settings); m.settingsPane = .ais; m.settings.loaded = true; m.settings.answered = true; m.settings.busy = []; m.settings.said = [:]
                m.settings.apps = [MCPApp(id: "cursor", name: "cursor", state: "changed", path: "~/.cursor/mcp.json",
                                          detail: "another program changed the entry context wrote for cursor: it now starts a different command. nothing was put back."),
                                   MCPApp(id: "claude_desktop", name: "claude", state: "connected", path: "~/Library/Application Support/Claude/config.json", detail: "")]
            }),
            // an answer that names an address only someone else's message held: the engine sends it as plain words, and it is drawn as words
            ("chat-their-address", {
                main(.home); m.saved.sidebar = false
                let a = Answer(["answer": "The sign-up form is at forms.example.com (an address from someone else's message: not opened from here). Sam sent it on the ninth; ask him before you fill it in.",
                                "cites": [[String: Any]](), "strength": "strong"], tag: "t0")
                m.ask.turns = [Turn(id: 0, q: "where is the sign-up form for the open day", answer: a)]
                m.ask.asking = false
            }),
        ]
    }

    static func guardCheck(_ screen: String, _ at: String, _ found: [ProbeInfo]) -> [String] {
        var out: [String] = []
        func has(_ n: String) -> Bool { found.contains { $0.name == n } }
        switch screen {
        case "first-bare-keys": if bareKeys != [false, false] || AppModel.shared.mcpRunning || AppModel.shared.requests.enabling { out.append("\(at): a bare key on the welcome screen writes into another app's folder or config") }
        case "sources-export-armed":
            let item = AppModel.shared.shelf.flatMap(\.items).first { $0.id == "export:x" }
            if item?.action != "ask now" || item?.line.contains("may email you") != true { out.append("\(at): one press on an export sends the request, or the line does not say the site may email") }
        case "settings-links-engine": if AppModel.shared.settings.linksFromOthers != true || !has("setting.links") { out.append("\(at): the switch for links from others does not show the engine's own word") }
        case "settings-ais-changed": if !has("setting.rewrite") { out.append("\(at): an entry another program changed is not said, or has no way to write it again") }
        case "chat-their-address":
            if !has("chat.answer") || found.contains(where: { $0.name.hasPrefix("chat.link") }) { out.append("\(at): an address from someone else's message is not drawn as plain text") }
        case "settings-own": if !has("setting.links") { out.append("\(at): there is no switch for links from other people's messages") }
        default: break
        }
        return out
    }
}
