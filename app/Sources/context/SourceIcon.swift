import AppKit
import Observation
import SwiftUI

/// The one icon for a source or an app, wherever one is shown: the shelf, the sources tab, the chat's sources and
/// citation cards, the add panel, the plan margin, the menu-bar panel, setup and settings.
///
///     SourceIcon(id: "whatsapp", size: 16)
///
/// `id` is the name the collector uses for the source (or an app's id from `connect --search`). It draws, in order:
/// the app's own icon when the app is on this mac; else a monogram on a quiet tint of the source's colour. Nothing is
/// asked of any site for it. Only when "fetch source icons from their sites" is switched on in settings does a source
/// without an app wear the service's own mark, fetched once from its site and kept in the archive folder. No logo
/// file is in the repo.
/// The view is exactly `size` by `size` points. To sit on a line of text, give it that text's cap-to-descender
/// height and `.alignmentGuide(.firstTextBaseline) { $0[.bottom] - descender }`, or use `SourceIcon.inline(id:font:)`.
struct SourceIcon: View {
    let id: String
    var size: CGFloat = 32
    var name: String? = nil       // for the monogram, when the catalog does not know this id (an app found by search)
    var path = ""                 // an app bundle on this mac, when the caller already knows where it is
    var muted = false             // greyed: not read, or waiting on them

    /// Names other parts of the app use for the same thing.
    static let alias = ["claude": "claude_code", "claude_desktop": "claude_code", "claude code": "claude_code", "chatgpt": "chatgpt_export",
                        "x": "x_archive", "google": "gmail_takeout"]

    init(id: String, size: CGFloat = 32, name: String? = nil, path: String = "", muted: Bool = false) {
        self.id = SourceIcon.alias[id] ?? id
        self.size = size
        self.name = name
        self.path = path
        self.muted = muted
    }

    var body: some View {
        let _ = IconStore.shared.version           // drawn again when a fetched icon lands
        Group {
            if let icon = AppIcons.icon(for: id, path: path) {
                Image(nsImage: icon).resizable().interpolation(.high).frame(width: size, height: size)
            } else if WebIcons.on, let web = WebIcons.cached(id) {
                // the service's own mark, cut to the shape of a tile; app icons carry a margin, so this one gets the same
                Image(nsImage: web).resizable().interpolation(.high).frame(width: size * 0.82, height: size * 0.82)
                    .background(Color.white)
                    .clipShape(RoundedRectangle(cornerRadius: size * 0.2, style: .continuous))
                    .overlay(RoundedRectangle(cornerRadius: size * 0.2, style: .continuous).strokeBorder(Ink.line, lineWidth: 0.5))
                    .frame(width: size, height: size)
                    .probe("icon.web", .block, scrolls: true)
            } else {
                let tint = Catalog.info(id).color
                let label = name ?? (Catalog.info(id).name.isEmpty ? id : Catalog.info(id).name)
                ZStack {
                    RoundedRectangle(cornerRadius: size * 0.26, style: .continuous).fill(tint.opacity(muted ? 0.1 : 0.18))
                    Text(String(label.first { $0.isLetter || $0.isNumber } ?? "·"))
                        .font(.system(size: size * 0.5, weight: .bold)).foregroundStyle(tint.opacity(muted ? 0.6 : 1))
                }
                .frame(width: size * 0.82, height: size * 0.82).frame(width: size, height: size)
                .onAppear { WebIcons.want(id) }
            }
        }
        .saturation(muted ? 0 : 1).opacity(muted ? 0.6 : 1)
        .accessibilityHidden(true)
    }

    /// The icon set in a line of text: as tall as the face from the top of a capital to the bottom of a descender,
    /// and placed so that it is centred on the words beside it in an `HStack(alignment: .firstTextBaseline)`.
    static func inline(id: String, font: NSFont, name: String? = nil, muted: Bool = false) -> some View {
        let box = (font.capHeight - font.descender).rounded()
        return SourceIcon(id: id, size: box, name: name, muted: muted)
            .alignmentGuide(.firstTextBaseline) { $0[.bottom] + font.descender }
    }
}

enum AppIcons {
    private static var cache: [String: NSImage?] = [:]
    /// The bundle ids an app might have. Nothing is shipped in the repo: the icon is read from the app on this mac.
    static let bundles: [String: [String]] = [
        "whatsapp": ["net.whatsapp.WhatsApp"], "imessage": ["com.apple.MobileSMS"], "email": ["com.apple.mail"],
        "apple_notes": ["com.apple.Notes"], "calendar": ["com.apple.iCal"],
        "telegram": ["ru.keepcoder.Telegram", "org.telegram.desktop", "com.tdesktop.Telegram"], "obsidian": ["md.obsidian"],
        "cursor": ["com.todesktop.230313mzl4w4u92"], "claude_code": ["com.anthropic.claudefordesktop"],
        "codex": ["com.openai.codex"], "chatgpt_export": ["com.openai.chat"], "safari_history": ["com.apple.Safari"],
        "slack": ["com.tinyspeck.slackmacgap"], "notion": ["notion.id"],
        "grok_bot": ["ai.x.grok", "com.xai.grok"],
    ]

    static func icon(for source: String, path: String? = nil) -> NSImage? {
        if let path, !path.isEmpty, FileManager.default.fileExists(atPath: path) { return NSWorkspace.shared.icon(forFile: path) }
        if let hit = cache[source] { return hit }
        var found: NSImage?
        if source == "browser_history" || source == "_window" {      // "browsing" wears the icon of whichever browser is the default here
            if let u = URL(string: "https://example.com").flatMap({ NSWorkspace.shared.urlForApplication(toOpen: $0) }) {
                found = NSWorkspace.shared.icon(forFile: u.path)
            }
        }
        for b in bundles[source] ?? [] {
            if let u = NSWorkspace.shared.urlForApplication(withBundleIdentifier: b) { found = NSWorkspace.shared.icon(forFile: u.path); break }
        }
        cache[source] = found
        return found
    }
}


/// Redraws the icons when one arrives.
@Observable final class IconStore {
    static let shared = IconStore()
    var version = 0
}

/// A service's own mark, for a source that has no app on this mac. Off unless the owner switches it on: asking a site for its
/// icon tells that site this mac has something to do with it. When on, the icon is fetched once from the service's own
/// site, kept under `cache/icons` in the archive folder, and read from there afterwards. The request carries no
/// cookies and no stored credentials, and says what it is: context, fetching an icon.
enum WebIcons {
    /// "fetch source icons from their sites", in settings. Off by default.
    static var on: Bool { AppModel.shared.saved.webIcons }

    /// Which service a source belongs to: `instagram_saved` and `instagram_likes` wear instagram's mark.
    static func key(_ source: String) -> String? {
        let table: [(String, String)] = [
            ("instagram", "instagram"), ("linkedin", "linkedin"), ("x_", "x"), ("slack", "slack"), ("gdrive", "drive"),
            ("google_takeout", "google"), ("gmail", "gmail"), ("grok", "grok"), ("chatgpt", "chatgpt"), ("codex", "chatgpt"),
            ("notion", "notion"), ("telegram", "telegram"), ("whatsapp", "whatsapp"), ("claude", "claude"),
            ("cursor", "cursor"), ("obsidian", "obsidian"), ("discord", "discord"),
        ]
        return table.first { source == $0.0 || source.hasPrefix($0.0) }?.1
    }

    /// Where to look, in order: addresses of the icon itself, then the service's front page, whose own
    /// `apple-touch-icon` link is followed.
    static let sites: [String: (icons: [String], page: String)] = [
        "slack": (["https://a.slack-edge.com/80588/marketing/img/meta/app-256.png"], "https://slack.com"),
        "instagram": (["https://www.instagram.com/static/images/ico/apple-touch-icon-180x180-precomposed.png/c06fdb2357bd.png"], "https://www.instagram.com"),
        "linkedin": ([], "https://www.linkedin.com"),
        "x": (["https://abs.twimg.com/responsive-web/client-web/icon-ios.77d25eba.png"], "https://x.com"),
        "drive": (["https://ssl.gstatic.com/images/branding/product/2x/drive_2020q4_96dp.png"], "https://drive.google.com"),
        "gmail": (["https://ssl.gstatic.com/images/branding/product/2x/gmail_2020q4_96dp.png"], "https://mail.google.com"),
        "google": ([], "https://www.google.com"),
        "grok": ([], "https://grok.com"),
        "chatgpt": ([], "https://chatgpt.com"),
        "notion": ([], "https://www.notion.so"),
        "telegram": (["https://telegram.org/img/apple-touch-icon.png"], "https://telegram.org"),
        "whatsapp": (["https://www.whatsapp.com/apple-touch-icon.png"], "https://www.whatsapp.com"),
        "claude": (["https://claude.ai/apple-touch-icon.png"], "https://claude.ai"),
        "cursor": ([], "https://cursor.com"),
        "obsidian": (["https://obsidian.md/apple-touch-icon.png"], "https://obsidian.md"),
        "discord": ([], "https://discord.com"),
    ]

    static var home: URL { AppModel.shared.engine.home }
    static func file(_ key: String, home: URL) -> URL {
        // CONTEXT_ICON_DIR: a folder of icons to draw a render with, when looking at how fetched marks sit on the shelf
        if let dir = ProcessInfo.processInfo.environment["CONTEXT_ICON_DIR"] { return URL(fileURLWithPath: dir).appendingPathComponent("\(key).png") }
        return home.appendingPathComponent("cache/icons/\(key).png")
    }

    private static var memory: [String: NSImage] = [:]
    private static var asked: Set<String> = []

    /// A made-up mark for the gate's screen of fetched icons: a plain square, drawn here, nobody's logo.
    static func proof(_ keys: [String]) {
        memory = [:]
        for k in keys {
            memory[k] = NSImage(size: NSSize(width: 64, height: 64), flipped: false) { r in
                NSColor(white: 0.2, alpha: 1).setFill(); r.fill()
                NSColor(white: 0.9, alpha: 1).setFill(); NSBezierPath(ovalIn: r.insetBy(dx: 18, dy: 18)).fill()
                return true
            }
        }
    }

    /// The icon if it is already on this mac. Never touches the network.
    static func cached(_ source: String, home: URL? = nil) -> NSImage? {
        guard let key = key(source) else { return nil }
        if let hit = memory[key] { return hit }
        guard let image = NSImage(contentsOf: file(key, home: home ?? WebIcons.home)), image.isValid else { return nil }
        memory[key] = image
        return image
    }

    /// Fetches it once per run if it is not here, and only when the owner switched fetching on. Renders and tests never fetch.
    static func want(_ source: String) {
        guard on, !Engine.debug, !Probe.on, let key = key(source), !asked.contains(key), memory[key] == nil, let site = sites[key] else { return }
        asked.insert(key)
        let home = WebIcons.home
        if FileManager.default.fileExists(atPath: file(key, home: home).path) { return }
        fetch(key, site: site, home: home) { ok in if ok { IconStore.shared.version += 1 } }
    }

    /// A request that carries nothing of their: no cookies in or out, no cache, no credentials. It names itself honestly.
    static func request(_ url: URL) -> URLRequest {
        var r = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalAndRemoteCacheData, timeoutInterval: 10)
        r.httpShouldHandleCookies = false
        r.setValue(agent, forHTTPHeaderField: "User-Agent")
        r.setValue("text/html,image/png,image/*;q=0.9,*/*;q=0.5", forHTTPHeaderField: "Accept")
        return r
    }

    /// What the request calls itself: the app and what it is doing, not a browser.
    static let agent = "context/\(Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "0") (macOS app; fetching this site's own icon)"

    static let session: URLSession = {
        let c = URLSessionConfiguration.ephemeral
        c.httpCookieStorage = nil
        c.httpShouldSetCookies = false
        c.httpCookieAcceptPolicy = .never
        c.urlCredentialStorage = nil
        c.urlCache = nil
        return URLSession(configuration: c)
    }()

    /// The icon links on a page, biggest first. Vector files are left out: the tile wants pixels.
    static func links(html: String, base: URL) -> [URL] {
        guard let tag = try? NSRegularExpression(pattern: "<link\\b[^>]*>", options: [.caseInsensitive]) else { return [] }
        func attr(_ name: String, _ s: String) -> String? {
            guard let re = try? NSRegularExpression(pattern: name + "\\s*=\\s*[\"']?([^\"'>\\s]+(?:\\s[^\"'>]*)?)[\"']?", options: [.caseInsensitive]),
                  let m = re.firstMatch(in: s, range: NSRange(s.startIndex..., in: s)), let r = Range(m.range(at: 1), in: s) else { return nil }
            return String(s[r]).trimmingCharacters(in: .whitespaces)
        }
        var found: [(Int, URL)] = []
        for m in tag.matches(in: html, range: NSRange(html.startIndex..., in: html)) {
            guard let r = Range(m.range, in: html) else { continue }
            let t = String(html[r])
            guard let rel = attr("rel", t)?.lowercased(), rel.contains("icon"), let href = attr("href", t)?.replacingOccurrences(of: "&amp;", with: "&"),
                  !href.lowercased().hasSuffix(".svg"), let url = URL(string: href, relativeTo: base)?.absoluteURL, url.scheme == "https" else { continue }
            let size = attr("sizes", t).flatMap { Int($0.prefix { $0.isNumber }) } ?? (rel.contains("apple") ? 180 : 32)
            found.append((size, url))
        }
        return found.sorted { $0.0 > $1.0 }.map(\.1)
    }

    /// Bytes that are a picture of at least 32 pixels, as a png; else nil.
    static func png(_ data: Data) -> Data? {
        guard data.count > 200, let image = NSImage(data: data) else { return nil }
        let reps = image.representations.sorted { $0.pixelsWide > $1.pixelsWide }
        guard let best = reps.first, best.pixelsWide >= 32, best.pixelsHigh >= 32 else { return nil }
        let side = min(256, best.pixelsWide)
        guard let out = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: side, pixelsHigh: side, bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true,
                                         isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0) else { return nil }
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: out)
        NSGraphicsContext.current?.imageInterpolation = .high
        best.draw(in: NSRect(x: 0, y: 0, width: side, height: side))
        NSGraphicsContext.restoreGraphicsState()
        return out.representation(using: .png, properties: [:])
    }

    static func fetch(_ key: String, site: (icons: [String], page: String), home: URL, done: @escaping (Bool) -> Void) {
        func finish(_ ok: Bool) { DispatchQueue.main.async { done(ok) } }
        func save(_ data: Data) -> Bool {
            guard let png = png(data) else { return false }
            let to = file(key, home: home)
            try? FileManager.default.createDirectory(at: to.deletingLastPathComponent(), withIntermediateDirectories: true)
            return (try? png.write(to: to, options: .atomic)) != nil
        }
        func tryIcons(_ urls: [URL], then: @escaping () -> Void) {
            guard let url = urls.first else { then(); return }
            session.dataTask(with: request(url)) { data, resp, _ in
                if (resp as? HTTPURLResponse)?.statusCode == 200, let data, data.count < 3_000_000, save(data) { finish(true); return }
                tryIcons(Array(urls.dropFirst()), then: then)
            }.resume()
        }
        let fixed = site.icons.compactMap { URL(string: $0) }.filter { $0.scheme == "https" }
        tryIcons(fixed) {
            guard let page = URL(string: site.page) else { finish(false); return }
            session.dataTask(with: request(page)) { data, resp, _ in
                let base = resp?.url ?? page
                var next = data.map { links(html: String(decoding: $0.prefix(800_000), as: UTF8.self), base: base) } ?? []
                next += ["/apple-touch-icon.png", "/favicon.ico"].compactMap { URL(string: $0, relativeTo: base)?.absoluteURL }
                tryIcons(Array(next.prefix(4))) { finish(false) }
            }.resume()
        }
    }
}
