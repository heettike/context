import AppKit
import SwiftUI

/// Settings, checked: every pane at every size with long values, nothing cut with an ellipsis, nothing out of its
/// card, and what is folded stays folded until asked for.
extension LayoutTest {
    static func settingsScreens(_ m: AppModel, main: @escaping (Tab) -> Void) -> [(String, () -> Void)] {
        let st = m.settings
        let long = "/Users/someone-with-a-long-name/Library/Application Support/a folder/another folder/and one more/.context/v2"
        func base(_ pane: SettingsPane) {
            main(.settings)
            m.settingsPane = pane
            st.loaded = true
            st.answered = true
            st.busy = []
            st.test = ""
            st.testing = false
            st.reading = false
            st.exported = ""
            m.access = false
            let answerCalls: [String: Any] = ["calls": 1_250, "tokens_in": 1, "tokens_out": 1]
            let usage: [String: Any] = ["today": ["answer": answerCalls, "coach": answerCalls], "week": ["answer": ["calls": 9_000]],
                                        "cost": "$0 extra: calls run on the plan you already pay for"]
            let rows: [String: Any] = ["messages": 1_000_000, "docs": 80_000, "mail_index": 40_000, "sessions": 0]
            let archive: [String: Any] = ["folder": long, "bytes": 3e9, "rows": rows]
            let readThrough: [String: Any] = ["reread_weekly": true, "read": 170, "units": 1_600, "calls_left_about": 120]
            let keys: [String: Any] = ["file": ".env in the engine folder", "present": ["TELEGRAM_API_ID"], "not_set": ["A_KEY_WITH_A_RATHER_LONG_NAME_THAT_GOES_ON", "ANOTHER_KEY"]]
            let syncSettings: [String: Any] = ["fast_minutes": 15, "daily_hour": 4, "weekly_day": "sun"]
            let about: [String: Any] = ["repo": "github.com/an-owner-with-a-long-name/a-repository-with-a-long-name-too"]
            st.raw = ["usage": usage, "archive": archive, "read_through": readThrough, "keys": keys, "sync": ["settings": syncSettings], "about": about]
            let now = Date().timeIntervalSince1970
            let fastTier: [String: Any] = ["last": now - 360, "due": false, "next_in": 540, "results": [String: Any](),
                                           "sources": ["whatsapp", "imessage", "claude_code", "codex", "cursor", "grok_bot", "grok_bot_prompts", "browser_history", "safari_history", "obsidian", "apple_notes"]]
            let dailyTier: [String: Any] = ["last": now - 36000, "due": false, "next_in": 50400, "results": [String: Any](),
                                            "sources": ["email", "slack", "gdrive", "calendar", "telegram", "x_bookmarks"]]
            let weekly: [String: Any] = ["x": ["state": "requested", "every": "monthly", "last": now - 86400 * 3, "due": false, "next_in": 2584800],
                                         "google": ["state": "idle", "every": "weekly", "last": 0.0, "due": false], "instagram": ["state": "idle", "every": "monthly", "last": 0.0, "due": false]]
            m.engine.schedule = Schedule(["fast": fastTier, "daily": dailyTier, "weekly": weekly])
            st.understand = (170, 1_600)
            st.apps = [MCPApp(id: "claude_desktop", name: "claude desktop", state: "not registered", path: long + "/claude_desktop_config.json", detail: "another server is registered there under the name context, not this one"),
                       MCPApp(id: "claude_code", name: "claude code", state: "connected", path: "~/.claude.json", detail: ""),
                       MCPApp(id: "cursor", name: "cursor", state: "registered", path: "~/.cursor/mcp.json", detail: ""),
                       MCPApp(id: "vscode", name: "vs code (copilot)", state: "not registered", path: "~/.copilot/mcp-config.json", detail: ""),
                       MCPApp(id: "codex", name: "codex", state: "app not found", path: "", detail: ""),
                       MCPApp(id: "zed", name: "zed", state: "app not found", path: "", detail: ""),
                       MCPApp(id: "lmstudio", name: "lm studio", state: "app not found", path: "", detail: ""),
                       MCPApp(id: "chatgpt", name: "chatgpt (web, then every chatgpt app)", state: "remote off", path: "", detail: "", how: "start the remote endpoint, then paste its address into chatgpt's connectors page"),
                       MCPApp(id: "claude_ai", name: "claude.ai (web, desktop and mobile)", state: "remote off", path: "", detail: "")]
            m.models = ModelsReport(modelsReport)
            m.wikiBuild.status = WikiBuild.status(["built": false, "pages": [String: Any](), "words": 0, "spent": ["secs": 0]])
        }
        return [
            ("settings-general", { base(.general) }),
            ("settings-models", { base(.models); st.test = "answered in 3.2 s" }),
            ("settings-models-jobs", { base(.models); ModelsPane.unfolded = true }),
            ("settings-models-trouble", {       // signed out, and the other plan at its limit: the pane says both, and so does the sidebar
                base(.models)
                m.plan = ModelPlan(["using": "none", "fix": "sign in once: open claude code and type /login"])
                var d = modelsReport
                d["limited"] = ["plan b": ["until": 4_102_444_800.0, "why": "Your plan's limit was reached; it resets in a few hours."]]
                d["fallback_when_limited"] = false
                m.models = ModelsReport(d)
            }),
            ("settings-ais", { base(.ais); AIsPane.unfolded = true }),
            ("settings-ais-folded", { base(.ais); st.busy = ["cursor"] }),
            ("settings-sync", { base(.sync) }),
            ("settings-sync-none", { base(.sync); m.engine.schedule = nil }),
            ("settings-permissions", {
                base(.permissions)
                m.requests.browser = BrowserInfo(name: "a browser with a long name", scripting: false, howToEnable: "run: python3 -m ctx request --enable-browser")
                m.bridge = false
                m.automation = ["com.apple.iCal": .on, "com.apple.Notes": .asked]
            }),
            ("settings-data", { base(.data) }),
            ("settings-data-estimate", {        // the cost, before anything starts; and a report already written
                base(.data)
                m.wikiBuild.status = WikiBuild.status(["built": true, "pages": ["front": 1, "people": 10, "projects": 5, "years": 2, "themes": 4], "words": 35_000, "spent": ["calls": 160, "secs": 2_100]])
                m.wikiBuild.estimate = WikiBuild.estimate(["estimate": ["pages_to_write": ["people, the closest": 50, "people, the rest": 200, "projects": 12, "quarters": 20, "years": 8, "themes": 5],
                                                                        "calls_total": 700, "hours_at_5_workers": 3.0, "plan": "your claude plan"]])
                st.report = "~/a folder with a long name/another folder/.context/v2/reports/context-report-2026-11-15.txt"
                st.understand = (1_600, 1_600)
            }),
            ("settings-data-building", {        // the wiki being written
                base(.data)
                m.wikiBuild.status = WikiBuild.status(["built": true, "pages": ["front": 1, "people": 30], "words": 50_000, "spent": ["calls": 100, "secs": 4_800]])
                m.wikiBuild.running = true
                m.wikiBuild.progress = WikiBuild.Progress(n: 30, of: 250, kind: "people")
                m.wikiBuild.failed = "a page could not be written and will be tried again."
                st.exported = "copied to context-archive-2026-11-12"
            }),
            ("settings-about", { base(.about) }),
            ("settings-empty", {            // an engine that has answered nothing: every pane says so in a sentence
                base(.models)
                st.answered = false
                st.raw = [:]
                st.apps = []
                st.understand = nil
                m.models = nil
                m.engine.schedule = nil
                m.wikiBuild.status = nil
                m.plan = nil
            }),
            ("settings-empty-data", {
                base(.data)
                st.answered = false
                st.raw = [:]
                st.understand = nil
                m.wikiBuild.status = nil
            }),
        ]
    }

    /// What must hold on every pane.
    static func settingsCheck(_ screen: String, _ at: String, _ size: CGSize, _ found: [ProbeInfo]) -> [String] {
        guard screen.hasPrefix("settings") else { return [] }
        var more: [String] = []
        func count(_ n: String) -> Int { found.filter { $0.name == n }.count }
        if count("setting.pane") != SettingsPane.allCases.count { more.append("\(at): the list of panes does not show all \(SettingsPane.allCases.count)") }
        if count("setting.heading") != 1 { more.append("\(at): a pane has one name at its head, not \(count("setting.heading"))") }
        if count("setting.card") == 0 { more.append("\(at): the pane has no card") }
        // the list on the left and the pane beside it share no ground
        if let list = found.first(where: { $0.name == "setting.list" }) {
            for p in found where p.name.hasPrefix("setting.") && !p.name.hasPrefix("setting.pane") && p.name != "setting.list" && p.frame.minX < list.frame.maxX - 0.5 {
                more.append("\(at): \(p.name) lies under the list of panes"); break
            }
        }
        // every word and control of a card lies inside it
        let cards = found.filter { $0.name == "setting.card" }.map(\.frame)
        for p in found where ["setting.title", "setting.about", "setting.mono", "setting.label", "setting.pill", "setting.control", "setting.fold", "setting.preset"].contains(p.name) {
            guard let card = cards.first(where: { $0.minY - 1 <= p.frame.midY && p.frame.midY <= $0.maxY + 1 && $0.minX - 1 <= p.frame.minX }) else { continue }
            if p.frame.maxX > card.maxX - 6 || p.frame.minX < card.minX + 6 {
                more.append("\(at): \(p.name) runs out of its card (\(Int(p.frame.minX)) to \(Int(p.frame.maxX)), card \(Int(card.minX)) to \(Int(card.maxX)))")
            }
        }
        // a pill and the control of a row never lie on the row's words
        let controls = found.filter { $0.name == "setting.control" || $0.name == "setting.pill" || $0.name == "setting.fold" }
        for t in found where t.name == "setting.about" || t.name == "setting.title" || t.name == "setting.mono" {
            for c in controls {
                let x = t.frame.intersection(c.frame)
                if !x.isNull, x.width > 1, x.height > 1 { more.append("\(at): \(c.name) lies on \(t.name) by \(Int(x.width))x\(Int(x.height))") }
            }
        }
        // the plan the answers run on is said in the sidebar only when it is in trouble
        let warned = count("side.plan") > 0
        if screen == "settings-models-trouble", size.width >= Grid.narrow, !warned { more.append("\(at): a plan that is signed out is not said in the sidebar") }
        if screen != "settings-models-trouble", screen != "settings-empty", warned { more.append("\(at): the sidebar says something about the plan though nothing is wrong with it") }
        switch screen {
        case "settings-ais":
            if count("setting.missing") != 1 { more.append("\(at): apps that are not on this mac should share one line") }
            if count("setting.path") == 0 { more.append("\(at): details does not show where the entry is kept") }
        case "settings-ais-folded":
            if count("setting.path") != 0 { more.append("\(at): a config path shows before details is asked for") }
        case "settings-about":
            if count("setting.key") != 0 { more.append("\(at): key names show before they are asked for") }
        case "settings-models":
            if count("setting.preset") != 1 || count("setting.measure") != 1 { more.append("\(at): the pane does not show the presets as one control and the measurement") }
            if count("setting.job") != 0 { more.append("\(at): the per-job rows show before they are asked for") }
        case "settings-models-jobs":
            if count("setting.job") != 4 { more.append("\(at): choose per job does not show the four jobs") }
        case "settings-pings":
            if count("setting.ping.kind") != 4 || count("setting.ping.note") != 10 { more.append("\(at): notifications do not show the four kinds of ping and the last ten") }
        case "settings-data-building", "settings-data", "settings-data-estimate":
            if count("wiki.build") != 1 { more.append("\(at): your data does not show where the wiki stands") }
        default: break
        }
        return more
    }

    /// The files of the settings page, read for a line cut any other way than the page's own text makers allow: a limit
    /// on lines is only ever set together with a width of its own, and nothing is told where to put an ellipsis.
    /// With no sources beside the build there is nothing to read, and the measured checks stand alone.
    static func settingsSourceFaults() -> [String] {
        let dir = LayoutTest.sourcesDir
        var more: [String] = []
        let cut = "truncation" + "Mode", limit = "line" + "Limit("
        for name in ["SettingsView.swift", "SettingsPanes.swift", "WikiBuild.swift"] {
            guard var text = try? String(contentsOf: dir.appendingPathComponent(name), encoding: .utf8) else { continue }
            if name == "SettingsView.swift", let r = text.range(of: "// MARK: the page") { text = String(text[r.lowerBound...]) }
            for (i, line) in text.split(separator: "\n", omittingEmptySubsequences: false).enumerated() {
                if line.contains(cut) { more.append("settings: \(name) line \(i + 1) says where to put an ellipsis") }
                if line.contains(limit), !line.contains("fixedSize()") { more.append("settings: \(name) line \(i + 1) limits a text's lines without giving it its own width") }
            }
        }
        return more
    }
}
