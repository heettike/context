import SwiftUI

/// open: readable as is. locked: needs full disk access. browser: read in the daily tier, where the owner is signed in.
/// archive: arrives as an export you request; it only gets a setup step once it holds rows.
enum Via { case open, locked, browser, archive }

struct SourceInfo: Identifiable, Equatable {
    let id: String        // the name the collector prints
    let name: String
    let group: String
    let noun: String
    let reads: String
    let needs: String
    let via: Via
    let color: Color
    let corner: CGFloat
    let aspect: CGFloat
    let turn: Double

    static func == (a: SourceInfo, b: SourceInfo) -> Bool { a.id == b.id }
}

enum Catalog {
    static let fda = "full disk access."
    static let archive = "the official export. leave the zip in downloads: context takes it in on its next look, or at once with sync now under sources."
    static let agent = "context reads this in your browser, where you are signed in. read only."

    /// in the order the collector prints them.
    static let all: [SourceInfo] = [
        .init(id: "whatsapp", name: "whatsapp", group: "messages", noun: "messages",
              reads: "every text in the whatsapp mac app's local database. no media, no calls.",
              needs: "nothing with full disk access on. without it, macos asks once to let context read another app's data.",
              via: .open, color: Color(0x2BA864, 0x35B972), corner: 1, aspect: 1, turn: 0),
        .init(id: "imessage", name: "imessage", group: "messages", noun: "messages",
              reads: "every text in messages, from chat.db in your library folder.",
              needs: fda, via: .locked, color: Color(0x2F7BF6, 0x4B8DF8), corner: 0.56, aspect: 1, turn: 0),
        .init(id: "telegram", name: "telegram", group: "messages", noun: "messages",
              reads: "every chat back to its first message, through telegram's own api.",
              needs: "an api id and hash from my.telegram.org (api development tools), put in .env in the archive folder as TELEGRAM_API_ID and TELEGRAM_API_HASH. then one sign-in, by scanning a code from the telegram app on your phone. the first export takes hours.", via: .browser,
              color: Color(0x3BA4DC, 0x52B3E6), corner: 0.22, aspect: 1, turn: 45),
        .init(id: "slack", name: "slack", group: "messages", noun: "messages",
              reads: "every channel and dm you are in, through slack's api from your signed-in tab.",
              needs: agent, via: .browser,
              color: Color(0x7A3E8E, 0x9A5BB0), corner: 1, aspect: 2.1, turn: -32),
        .init(id: "x_dms", name: "x dms", group: "messages", noun: "messages",
              reads: "your direct messages on x, from your official x archive.",
              needs: archive, via: .archive,
              color: Color(0x17181A, 0xEDECE8), corner: 0.5, aspect: 1.4, turn: 0),
        .init(id: "instagram", name: "instagram", group: "messages", noun: "messages",
              reads: "your instagram dms, from the account export.",
              needs: archive, via: .archive,
              color: Color(0xD6437E, 0xE25C93), corner: 0.34, aspect: 1, turn: 0),
        .init(id: "linkedin", name: "linkedin", group: "messages", noun: "messages",
              reads: "your linkedin messages, from the larger account archive.",
              needs: archive, via: .archive,
              color: Color(0x2867B2, 0x4C87CE), corner: 0.14, aspect: 1, turn: 0),
        .init(id: "gmail_takeout", name: "gmail", group: "messages", noun: "emails",
              reads: "all of gmail, from a google takeout .mbox. the complete copy of your mail.",
              needs: archive, via: .archive,
              color: Color(0xC8463B, 0xDB6156), corner: 0.1, aspect: 1.5, turn: 0),
        .init(id: "email", name: "mail", group: "messages", noun: "emails",
              reads: "mail you sent, and mail from people you have written to. everything else is kept as sender and subject only.",
              needs: fda, via: .locked, color: Color(0x51607A, 0x7C8CA8), corner: 0.1, aspect: 1.5, turn: 0),
        .init(id: "claude_code", name: "claude code", group: "agents", noun: "sessions",
              reads: "what you typed in each session and where the agent left off. files in ~/.claude.",
              needs: "nothing. these are your own files.", via: .open,
              color: Color(0xD9683A, 0xE27B4F), corner: 0.2, aspect: 1, turn: 14),
        .init(id: "codex", name: "codex", group: "agents", noun: "sessions",
              reads: "what you typed in each session and where the agent left off. files in ~/.codex.",
              needs: "nothing. these are your own files.", via: .open,
              color: Color(0x3B3D42, 0xB9BABD), corner: 1, aspect: 0.56, turn: 0),
        .init(id: "cursor", name: "cursor", group: "agents", noun: "sessions",
              reads: "your composer chats, from cursor's local database.",
              needs: "nothing. these are your own files.", via: .open,
              color: Color(0x8A9099, 0x8A9099), corner: 0.04, aspect: 1, turn: 45),
        .init(id: "grok_bot", name: "grok bot", group: "agents", noun: "sessions",
              reads: "the threads the grok bot app keeps on this mac.",
              needs: "nothing. these are your own files.", via: .open,
              color: Color(0x5C5F66, 0xA6A8AC), corner: 0.5, aspect: 1, turn: 0),
        .init(id: "chatgpt_export", name: "chatgpt", group: "agents", noun: "chats",
              reads: "every chatgpt conversation, from the account export.",
              needs: archive, via: .archive,
              color: Color(0x1F8A70, 0x35A68A), corner: 1, aspect: 1, turn: 0),
        .init(id: "browser_history", name: "browsing", group: "notes and saved", noun: "pages",
              reads: "the pages you visited in your browser: title, site, how often. query strings are dropped.",
              needs: "nothing. these are your own files.", via: .open,
              color: Color(0x6B7280, 0x9AA1AD), corner: 0.3, aspect: 1.7, turn: 0),
        .init(id: "safari_history", name: "safari", group: "notes and saved", noun: "pages",
              reads: "the pages you visited in safari: title, site, how often.",
              needs: fda, via: .locked,
              color: Color(0x2D8CD9, 0x4DA2E6), corner: 1, aspect: 1, turn: 0),
        .init(id: "obsidian", name: "obsidian", group: "notes and saved", noun: "notes",
              reads: "the markdown files in your vaults.",
              needs: "nothing. these are your own files.", via: .open,
              color: Color(0x7B5BE0, 0x9179EA), corner: 0.18, aspect: 0.74, turn: 12),
        .init(id: "apple_notes", name: "notes", group: "notes and saved", noun: "notes",
              reads: "every note that is not locked with a password.",
              needs: "full disk access. without it, macos asks to let context control notes, which is slower but works.",
              via: .locked, color: Color(0xEDB92E, 0xF2C544), corner: 0.2, aspect: 1, turn: 0),
        .init(id: "x_bookmarks", name: "x bookmarks", group: "notes and saved", noun: "bookmarks",
              reads: "the posts you bookmarked, from x.com/i/bookmarks.",
              needs: agent, via: .browser,
              color: Color(0x17181A, 0xEDECE8), corner: 0.12, aspect: 0.68, turn: 0),
        .init(id: "instagram_saved", name: "instagram saves", group: "notes and saved", noun: "posts",
              reads: "the posts you saved on instagram, from the account export.",
              needs: archive, via: .archive,
              color: Color(0xD6437E, 0xE25C93), corner: 0.34, aspect: 0.8, turn: 0),
        .init(id: "instagram_likes", name: "instagram likes", group: "notes and saved", noun: "posts",
              reads: "the posts you liked on instagram, from the account export.",
              needs: archive, via: .archive,
              color: Color(0xD6437E, 0xE25C93), corner: 1, aspect: 1, turn: 0),
        .init(id: "x_archive", name: "x posts", group: "notes and saved", noun: "posts",
              reads: "your own posts, replies and likes, from your official x archive.",
              needs: archive, via: .archive,
              color: Color(0x17181A, 0xEDECE8), corner: 1, aspect: 1, turn: 0),
        .init(id: "google_takeout", name: "youtube and keep", group: "notes and saved", noun: "items",
              reads: "what you watched and searched on youtube, and your keep notes, from a google takeout.",
              needs: archive, via: .archive,
              color: Color(0xD93025, 0xE6584E), corner: 0.3, aspect: 1.4, turn: 0),
        .init(id: "linkedin_connections", name: "linkedin people", group: "notes and saved", noun: "people",
              reads: "who you are connected to: name, role, company, when. from the account export.",
              needs: archive, via: .archive,
              color: Color(0x2867B2, 0x4C87CE), corner: 1, aspect: 1, turn: 0),
        .init(id: "notion", name: "notion", group: "notes and saved", noun: "pages",
              reads: "your workspace pages, from notion's export.",
              needs: archive, via: .archive,
              color: Color(0x3B3D42, 0xB9BABD), corner: 0.08, aspect: 1, turn: 0),
        .init(id: "gdrive", name: "google drive", group: "notes and saved", noun: "docs",
              reads: "the docs, slides and sheets you own, read as text from your signed-in google tab.",
              needs: agent, via: .browser,
              color: Color(0x1E9E94, 0x30B5AA), corner: 0.1, aspect: 1.25, turn: -8),
        .init(id: "calendar", name: "calendar", group: "notes and saved", noun: "events",
              reads: "three years of events, and what is coming up, from the calendar app.",
              needs: "macos asks once to let context read the calendar app.", via: .browser,
              color: Color(0xE0483E, 0xEC5F55), corner: 0.26, aspect: 1, turn: 0),
        // sources the engine reads that had no row here
        .init(id: "contacts", name: "contacts", group: "notes and saved", noun: "contacts",
              reads: "the contacts app: names for the numbers in your chats, and the notes you wrote on people.",
              needs: "full disk access.", via: .locked,
              color: Color(0x6B7F99, 0x8FA3BD), corner: 0.3, aspect: 1, turn: 0),
        .init(id: "reminders", name: "reminders", group: "notes and saved", noun: "reminders",
              reads: "every reminder: what, which list, when due, done or not.",
              needs: "full disk access.", via: .locked,
              color: Color(0xE08A2E, 0xF0A24A), corner: 0.3, aspect: 1, turn: 0),
        .init(id: "calls", name: "calls", group: "messages", noun: "calls",
              reads: "your call history and whatsapp's: who, when, how long. no call is recorded.",
              needs: "full disk access for the mac's own history. whatsapp's needs nothing.", via: .locked,
              color: Color(0x3FA66B, 0x5FC088), corner: 1.0, aspect: 1, turn: 0),
        .init(id: "voice_memos", name: "voice memos", group: "notes and saved", noun: "memos",
              reads: "the title, date and length of each recording.",
              needs: "full disk access.", via: .locked,
              color: Color(0xD9534F, 0xE87470), corner: 0.5, aspect: 1, turn: 0),
        .init(id: "journal", name: "journal", group: "notes and saved", noun: "entries",
              reads: "what you wrote in the app's plan tab.",
              needs: "nothing. these are your own files.", via: .open,
              color: Color(0x7A6FB0, 0x9D93D0), corner: 0.26, aspect: 1, turn: 0),
        .init(id: "media_images", name: "pictures", group: "notes and saved", noun: "pictures",
              reads: "the words in your pictures and screenshots, read on this mac.",
              needs: "nothing for your folders. full disk access for pictures inside chats.", via: .open,
              color: Color(0xC08A3E, 0xD9A75C), corner: 0.2, aspect: 1, turn: 0),
        .init(id: "media_audio", name: "voice notes", group: "messages", noun: "voice notes",
              reads: "what was said in voice notes and recordings, heard on this mac.",
              needs: "nothing for your folders. full disk access for voice notes inside chats.", via: .open,
              color: Color(0x4E9CA8, 0x6DBAC6), corner: 0.5, aspect: 1, turn: 0),
        .init(id: "media_files", name: "files", group: "notes and saved", noun: "files",
              reads: "the text of pdfs and documents on this mac and in your chats.",
              needs: "nothing for your folders. full disk access for files inside chats.", via: .open,
              color: Color(0x8A8F98, 0xA9AEB6), corner: 0.2, aspect: 1, turn: 0),
        .init(id: "media_video", name: "videos", group: "notes and saved", noun: "videos",
              reads: "what is said in your videos, heard on this mac.",
              needs: "nothing for your folders. full disk access for videos inside chats.", via: .open,
              color: Color(0xB0567A, 0xCB7697), corner: 0.26, aspect: 1, turn: 0),
        .init(id: "linkedin_posts", name: "linkedin posts", group: "notes and saved", noun: "posts",
              reads: "your posts, comments and articles, from the complete linkedin archive.",
              needs: archive, via: .archive,
              color: Color(0x2F6FB0, 0x5A93D0), corner: 0.2, aspect: 1, turn: 0),
        .init(id: "linkedin_profile", name: "linkedin profile", group: "notes and saved", noun: "entries",
              reads: "your career as you wrote it, the notes on your invitations, recommendations and searches.",
              needs: archive, via: .archive,
              color: Color(0x2F6FB0, 0x5A93D0), corner: 0.3, aspect: 1, turn: 0),
        .init(id: "linkedin_saved", name: "linkedin saved", group: "notes and saved", noun: "posts",
              reads: "the posts you saved on linkedin.", needs: archive, via: .archive,
              color: Color(0x2F6FB0, 0x5A93D0), corner: 0.5, aspect: 1, turn: 0),
        .init(id: "linkedin_likes", name: "linkedin likes", group: "notes and saved", noun: "likes",
              reads: "what you reacted to on linkedin: the address and the day.", needs: archive, via: .archive,
              color: Color(0x2F6FB0, 0x5A93D0), corner: 1.0, aspect: 1, turn: 0),
    ]

    static let order = all.map(\.id)
    /// lines the collector prints that are part of another source (the prompts half of an agent source).
    /// A second way into a row that exists: its rows and its state are shown under that row, never as a row of its own.
    static let partOf: [String: String] = [
    "grok_bot_prompts": "grok_bot", "chatgpt_export_prompts": "chatgpt_export", "claude_history": "claude_code",
    "x_web_likes": "x_archive", "x_web_posts": "x_archive", "x_web_replies": "x_archive",
    "instagram_saved_web": "instagram_saved",
    "linkedin_comments": "linkedin_posts", "linkedin_articles": "linkedin_posts",
    "linkedin_invitations": "linkedin_profile", "linkedin_recommendations": "linkedin_profile", "linkedin_searches": "linkedin_profile",
    ]
    /// Lines an older engine wrote under a name it no longer reads: the engine keeps such a line in status.json, and it
    /// is no source of its own here. Chromium history is browser_history now.
    static let retired: Set<String> = ["dia_history"]
    static let hidden: Set<String> = Set(partOf.keys).union(retired)
    /// a setup step exists for sources read from this mac or a signed-in tab. archives and sources this app
    /// does not know get one only once they hold rows, so the flow stays short.
    static func isStep(_ id: String, rows: Int) -> Bool {
        guard let info = byID[id] else { return rows > 0 && !hidden.contains(id) }
        return info.via != .archive || rows > 0
    }
    private static let byID = Dictionary(uniqueKeysWithValues: all.map { ($0.id, $0) })

    /// Known sources come from the table. A source the collector adds later still gets a step.
    static func info(_ id: String) -> SourceInfo {
        byID[id] ?? SourceInfo(id: id, name: id.replacingOccurrences(of: "_", with: " "), group: "more", noun: "rows",
                               reads: "a source the collector added after this app was built.", needs: "see the readme.",
                               via: .open, color: Ink.soft, corner: 0.3, aspect: 1, turn: 0)
    }

    static let neutral = SourceInfo(id: "_", name: "", group: "", noun: "", reads: "", needs: "", via: .open,
                                    color: Ink.ink, corner: 1, aspect: 1, turn: 0)
    static let window = SourceInfo(id: "_window", name: "", group: "", noun: "", reads: "", needs: "", via: .open,
                                   color: Ink.ink, corner: 0.14, aspect: 1.35, turn: 0)
    static let eye = SourceInfo(id: "_eye", name: "", group: "", noun: "", reads: "", needs: "", via: .open,
                                color: Ink.ink, corner: 1, aspect: 1.9, turn: 0)
    static let aim = SourceInfo(id: "_aim", name: "", group: "", noun: "", reads: "", needs: "", via: .open,
                                color: Ink.ink, corner: 0.16, aspect: 1, turn: 45)
    static let key = SourceInfo(id: "_key", name: "", group: "", noun: "", reads: "", needs: "", via: .open,
                                color: Ink.ink, corner: 0.34, aspect: 1, turn: 0)
}

/// Turn the collector's skip reason into plain words, and the one action that fixes it.
struct Blocked {
    /// settings: full disk access. automation: macos said no to another app. browser: the browser switch of first run.
    /// signIn: telegram's one sign-in, in the app (Terminal only for a two-step password). daily: read it now, where the owner is signed in.
    enum Fix: Equatable { case settings, automation, browser, signIn, daily }
    let word: String
    let line: String
    var fix: Fix?
    var notHere = false
    /// nothing in it yet, and nothing the owner need do: not an error, and not shown during first run
    var empty = false
    var settings: Bool { fix == .settings }

    /// Whether the browser route works, and what its one button says. Set by the model once it exists; a check or a
    /// render that never builds one gets "off".
    static var route: () -> (on: Bool, button: String) = { (false, "turn on") }
    /// What the buttons do that need more than a link: the browser switch, the daily read.
    static var act: (Fix) -> Void = { _ in }
    /// Sources read in a signed-in browser tab. Calendar is read from its own app, and telegram through telegram.
    static let inBrowser: Set<String> = ["slack", "gdrive", "x_bookmarks"]

    var fixLabel: String {
        switch fix {
        case .settings, .automation: return "open settings"
        case .browser: return Blocked.route().button
        case .signIn: return "sign in"
        case .daily: return "read now"
        case nil: return ""
        }
    }

    func run() {
        switch fix {
        case .settings: Access.openSettings()
        case .automation:
            if let u = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation") { NSWorkspace.shared.open(u) }
        case .signIn: Blocked.telegramSignIn()
        case .browser, .daily: if let fix { Blocked.act(fix) }
        case nil: break
        }
    }

    /// The sign-in as one Terminal line that runs the engine this app runs, inside the app: its python, isolated (-I: no
    /// PYTHON* variable, no user site folder, not the folder it starts in) and writing nothing back (-B), handed the
    /// engine's folder by path and the archive folder by CTX_HOME. Empty when there is no engine.
    static var telegramCommand: String {
        let e = AppModel.shared.engine
        guard let repo = e.repo else { return "" }
        func q(_ s: String) -> String { "'" + s.replacingOccurrences(of: "'", with: "'\\''") + "'" }
        return "CTX_HOME=\(q(e.home.path)) \(q(Engine.python ?? "/usr/bin/python3")) -I -B -c \(q(Engine.boot)) \(q(repo.path)) telegram-login"
    }

    /// Telegram's sign-in: in the app, when the engine can stream the code to scan; in Terminal only when it cannot.
    static func telegramSignIn() {
        let x = AppModel.shared.exports
        x.engine = AppModel.shared.engine
        if !Engine.debug, x.telegramLogin() { AppModel.shared.go(.sources); return }
        telegramTerminal()
    }

    /// Opens Terminal with the sign-in running (telegramCommand): a small script in the archive folder, handed to macos
    /// to open. For a two-step password, which is typed there and never in the app. The command goes on the clipboard
    /// as well, for a mac where Terminal would not open it.
    static func telegramTerminal() {
        let command = telegramCommand
        guard !Engine.debug, !command.isEmpty else { return }
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(command, forType: .string)
        let file = AppModel.shared.engine.file("telegram-sign-in.command")
        let text = "#!/bin/sh\n# context: sign in to telegram once. scan the code it shows with the telegram app on your phone.\n\(command)\n"
        guard (try? text.write(to: file, atomically: true, encoding: .utf8)) != nil else { return }
        try? FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: file.path)
        NSWorkspace.shared.open(file)
    }

    /// The engine's sentence with its command for a working copy ("python3 -m ctx telegram-login", which an installed
    /// app cannot run) turned into what to do here: the open terminal button runs the engine inside the app.
    static func telegramSaid(_ s: String) -> (text: String, terminal: Bool) {
        let low = s.lowercased()
        for cmd in ["run once in a terminal: python3 -m ctx telegram-login", "python3 -m ctx telegram-login"] {
            if let r = low.range(of: cmd) { return (low.replacingCharacters(in: r, with: "press open terminal: the sign-in starts there, where you type it"), true) }
        }
        // the engine now names no command: it says the password is typed in a terminal, from this card
        if low.contains("two-step password"), let r = low.range(of: "it is typed in a terminal, never here: press open terminal on the sign-in card in the app's sources page") {
            return (low.replacingCharacters(in: r, with: "press open terminal: the sign-in starts there, where you type it"), true)
        }
        if low.contains("two-step password") { return (low, true) }
        return (low, false)
    }

    init(_ reason: String, _ info: SourceInfo) {
        let r = reason.lowercased()
        if r.contains("blocked by macos") || r.contains("full disk access") {
            word = "locked"; line = "macos keeps this behind full disk access, and it is off."; fix = .settings
        } else if r.contains("telegram_api") {
            word = "needs an api id"
            line = "telegram needs an api id and hash first: get them at my.telegram.org, api development tools, and put them in .env in the archive folder as TELEGRAM_API_ID and TELEGRAM_API_HASH. then sign in."
            fix = .signIn
        } else if (info.id == "telegram" && ["setup", "login", "telethon", "session", "imports/", "logged in"].contains(where: r.contains)) || r.contains("telegram-login") || r.contains("not logged in") {
            word = "needs a one-time sign-in"
            line = "telegram wants you to sign in once. the button shows a code: scan it with telegram on your phone. it needs an api id and hash from my.telegram.org in .env first."
            fix = .signIn
        } else if !r.contains("imports/"), r.contains("archive") || r.contains("takeout") || r.contains("ingest") {
            word = "comes as an export"; line = "the site sends it as an archive. ask for it under sources, exports."
        } else if r.contains("not allowed") || r.contains("not authorized") || r.contains("-1743") {
            word = "not allowed"; line = "macos said no when context asked this app. allow it under privacy, automation."; fix = .automation
        } else if r.contains("nothing written") || r.contains("nothing in it") {
            word = "nothing in it yet"; line = "\(info.name) has nothing in it yet. it is read once there is."; notHere = true; empty = true
        } else if r.contains("not installed") || r.contains("no data") || r.contains("not found") {
            word = "not on this mac"; line = "\(info.name) is not installed here, or has nothing in it yet."; notHere = true
        } else if info.id == "calendar" {
            word = "waits on calendar"; line = "context asks the calendar app for your events once a day. macos asks once to allow it."; fix = .daily
        } else if Blocked.inBrowser.contains(info.id) || r.contains("imports/") || info.via == .browser {
            if Blocked.route().on {
                word = "read once a day"; line = "context reads this one itself, in your browser, where you are signed in. it has not been read yet."; fix = .daily
            } else {
                word = "waits on your browser"; line = "context reads this one itself, in your browser, where you are signed in. the browser switch is off."; fix = .browser
            }
        } else {
            word = "could not read"
            line = String(r.replacingOccurrences(of: "error: ", with: "").prefix(140))
        }
    }
}

extension Catalog {
    /// Two short sentences a step says about its source: what it is, and exactly what is read and what is not.
    static func says(_ id: String) -> (what: String, reads: String) {
        switch id {
        case "whatsapp": return ("the whatsapp app on this mac.", "every text. no photos, voice notes or calls.")
        case "imessage": return ("the messages app: imessage and sms.", "every text. no attachments.")
        case "telegram": return ("your telegram chats, through telegram itself.", "text only. channels you only read are left out.")
        case "slack": return ("your slack workspaces.", "channels and dms you are in. text only, no files.")
        case "x_dms": return ("your direct messages on x.", "text only, from the archive x sends you.")
        case "instagram": return ("your instagram dms.", "text only. the same export also brings your saves and likes.")
        case "instagram_saved": return ("the posts you saved on instagram.", "caption, account and link, from the instagram export.")
        case "instagram_likes": return ("the posts you liked on instagram.", "caption, account and link, from the instagram export.")
        case "linkedin": return ("your linkedin messages.", "text only, from the archive linkedin sends you.")
        case "gmail_takeout": return ("all of gmail, from a google takeout.", "mail you wrote and mail from people you write to.")
        case "email": return ("the mail app on this mac.", "mail you sent, and replies. the rest by subject only.")
        case "claude_code": return ("your claude code sessions.", "what you typed, and where the agent stopped. no code.")
        case "codex": return ("your codex sessions.", "what you typed, and where the agent stopped. no code.")
        case "cursor": return ("your chats with cursor.", "what you typed, and where the agent stopped. no code.")
        case "grok_bot": return ("the grok bot app on this mac.", "your threads with it. what you asked, what it said.")
        case "chatgpt_export": return ("every chatgpt conversation.", "what you asked, from the export chatgpt sends you.")
        case "browser_history": return ("the pages you opened in your browser.", "title, site and how often. no page content, no logins.")
        case "safari_history": return ("the pages you opened in safari.", "title, site and how often. no page content.")
        case "obsidian": return ("your obsidian vaults.", "the notes themselves. no attachments.")
        case "apple_notes": return ("the notes app.", "every note. locked notes stay locked and unread.")
        case "x_bookmarks": return ("the posts you bookmarked on x.", "the post text, its author and the link.")
        case "x_archive": return ("your own posts on x.", "posts, replies and likes, from the archive x sends you.")
        case "google_takeout": return ("youtube and keep, from a google takeout.", "what you watched and searched, and your keep notes.")
        case "linkedin_connections": return ("the people you are connected to on linkedin.", "name, role, company and when. nothing else.")
        case "notion": return ("your notion workspace.", "page text, from notion's own export.")
        case "gdrive": return ("the docs, slides and sheets you own.", "their text only, read where you are signed in.")
        case "calendar": return ("the calendar app.", "three years of events: title, time, who.")
        case "contacts": return ("the contacts app.", "whose number is whose, and your notes on people. read on this mac.")
        case "reminders": return ("the reminders app.", "each reminder, its list, when it is due, done or not.")
        case "calls": return ("your call history, and whatsapp's.", "who, when and how long. no call is recorded.")
        case "voice_memos": return ("the voice memos app.", "title, date and length. the words come from voice notes.")
        case "journal": return ("your own plan notes in this app.", "what you wrote, as you wrote it.")
        case "media_images": return ("pictures and screenshots.", "the words in them, read on this mac. the picture stays where it is.")
        case "media_audio": return ("voice notes and recordings.", "what was said, heard on this mac. no sound leaves it.")
        case "media_files": return ("pdfs and documents.", "their text. the file stays where it is.")
        case "media_video": return ("videos.", "what is said in them, heard on this mac.")
        case "linkedin_posts": return ("what you wrote on linkedin.", "posts, comments and articles, with their addresses.")
        case "linkedin_profile": return ("your linkedin profile.", "your career as you wrote it. no street, birth date or phone.")
        case "linkedin_saved": return ("posts you saved on linkedin.", "the address and the day. linkedin exports no words for them.")
        case "linkedin_likes": return ("what you reacted to on linkedin.", "the address, the day and the kind of reaction.")
        default: return ("a source the collector added recently.", info(id).reads)
        }
    }
}

extension Engine {
    /// The rows a source holds with the parts that are a second way into it (Catalog.partOf): what its row counts.
    func rowsWithParts(_ id: String) -> Int {
        Catalog.partOf.filter { $0.value == id }.keys.reduce(state(id).rows) { $0 + state($1).rows }
    }
}
