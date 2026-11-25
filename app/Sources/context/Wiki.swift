import AppKit
import Observation
import SwiftUI

// MARK: the wiki: the long form of what context knows about them, as the engine writes it under CTX_HOME/memory/wiki

/// One page of the wiki, as index.json lists it.
struct WikiEntry: Identifiable, Equatable {
    enum Kind: String, CaseIterable { case front, person, project, year, theme
        var group: String { ["front": "front page", "person": "people", "project": "projects", "year": "years", "theme": "themes"][rawValue] ?? rawValue }
        /// The engine says "people" where the plan says "person"; a quarter is filed with its year.
        init(_ raw: String) {
            let r = raw.lowercased()
            if r.hasPrefix("pe") { self = .person } else if r.hasPrefix("pr") { self = .project } else if r.hasPrefix("y") || r.hasPrefix("q") { self = .year }
            else if r.hasPrefix("f") { self = .front } else { self = .theme }
        }
    }
    let id: String
    var title: String
    var kind: Kind
    var path: String
    var updated = ""            // iso day or time
    var words = 0
    var conversations = 0
    var rows = 0
    var summary = ""
    var rank = 0                // its place in the index, which for people is closeness

    init(id: String, title: String, kind: Kind, path: String = "", updated: String = "", words: Int = 0, conversations: Int = 0, rows: Int = 0, summary: String = "", rank: Int = 0) {
        self.id = id; self.title = title; self.kind = kind; self.path = path.isEmpty ? id + ".md" : path
        self.updated = updated; self.words = words; self.conversations = conversations; self.rows = rows; self.summary = summary; self.rank = rank
    }

    init?(_ d: [String: Any], rank: Int) {
        guard let id = d["id"] as? String, !id.isEmpty else { return nil }
        self.id = id
        title = (d["title"] as? String ?? id.split(separator: "/").last.map(String.init) ?? id)
        kind = Kind(d["kind"] as? String ?? "")
        path = d["path"] as? String ?? id + ".md"
        if let s = d["updated"] as? String { updated = s } else if let t = d["updated"] as? Double { updated = Words.isoDay(Date(timeIntervalSince1970: t)) }
        words = d["words"] as? Int ?? 0
        let s = d["sources"] as? [String: Any] ?? [:]
        conversations = s["conversations"] as? Int ?? 0
        rows = s["rows"] as? Int ?? 0
        summary = d["summary"] as? String ?? ""
        // the engine gives each page its place within its kind ("order": closeness for people, the year for years);
        // an index without it is taken in the order it lists them
        self.rank = (d["order"] as? NSNumber)?.intValue ?? rank
    }

    /// A person's page whose title is a name to find in a sentence: one to three words, no figures, not "the …".
    /// The engine writes titles in lower case, so a capital cannot be the test. A group ("the committee") is not a name.
    var isName: Bool {
        guard kind == .person else { return false }
        let words = title.split(separator: " ")
        return (1...3).contains(words.count) && !title.lowercased().hasPrefix("the ") && !title.contains(where: \.isNumber) && !title.contains("&") && !title.contains(",")
    }

    /// "person · from 40 conversations · updated 14 nov · 2,000 words"
    var meta: String {
        var parts: [String] = [kind == .front ? "the front page" : kind.rawValue]
        if conversations > 0 { parts.append("from \(Words.count(conversations)) conversation\(conversations == 1 ? "" : "s")") }
        else if rows > 0 { parts.append("from \(Words.count(rows)) message\(rows == 1 ? "" : "s")") }
        if updated.count >= 10 { parts.append("updated " + Words.day(String(updated.prefix(10)))) }
        if words > 0 { parts.append("\(Words.count(words)) words") }
        return parts.joined(separator: "  ·  ")
    }
}

/// What a paragraph rests on: a conversation's card, or one row of the archive.
struct WikiRef: Hashable, Identifiable {
    var row: Bool               // false: a conversation
    var key: String
    var id: String { (row ? "r:" : "c:") + key }
}

/// Which web addresses on a page may be links, under the rule answers follow: those a row the owner wrote or saved
/// holds, among the rows the page cites (the engine's guard.own_row and urls_split), or every one when the owner's
/// setting links_from_others is on. The rest are their site's name in plain words (WikiText.gate).
struct WikiLinks: Equatable {
    var widen = false
    var mine: Set<String> = []          // addresses as norm() gives them

    /// An address in the form the engine compares (guard._norm): no scheme, no www., no trailing slash or full stop, lower case.
    static func norm(_ u: String) -> String {
        var s = u.trimmingCharacters(in: .whitespaces).lowercased()
        while let c = s.last, ".,;:*)>!?'\"".contains(c) { s.removeLast() }
        for p in ["https://", "http://"] where s.hasPrefix(p) { s.removeFirst(p.count); break }
        if s.hasPrefix("www.") { s.removeFirst(4) }
        while s.hasSuffix("/") { s.removeLast() }
        return s
    }

    /// An address one of the owner's rows holds, whole or as its start.
    func allows(_ u: String) -> Bool {
        if widen { return true }
        let n = WikiLinks.norm(u)
        return !n.isEmpty && mine.contains { $0 == n || $0.hasPrefix(n) }
    }

    /// The owner's own addresses in a row as `thread` gives it ({"src", "open", "rows": [{"who", "me", "text", "here"}]}):
    /// a row they wrote or saved, and the address of the thing itself. Someone else's row gives none.
    static func mine(inThread d: [String: Any]) -> Set<String> {
        guard let rows = d["rows"] as? [[String: Any]], let r = rows.first(where: { $0["here"] as? Bool == true }) else { return [] }
        let who = r["who"] as? String ?? ""
        guard who == "me" || who == "saved" || r["me"] as? Bool == true else { return [] }
        var out = Set(WikiText.addresses(in: r["text"] as? String ?? ""))
        if let open = d["open"] as? String, Answer.web(open) != nil { out.insert(norm(open)) }
        return out
    }
}

/// One block of a page, ready to draw: its words as one attributed run (so a long page is a few hundred texts, not
/// thousands of words), and the evidence its paragraph ends with.
struct WikiBlock: Identifiable {
    let id: Int
    var md: MDBlock
    var text = AttributedString()
    var plain = ""
    var refs: [WikiRef] = []
    var read = false            // starts "my read:": the model's own inference
    var anchor = ""             // the engine's name for the paragraph this block is the first of; empty when it has none
}

struct WikiPage {
    var entry: WikiEntry
    var raw: String
    var blocks: [WikiBlock]
    var outline: [(id: Int, title: String, level: Int)] { blocks.filter { $0.md.kind == .heading && $0.md.level >= 2 && $0.md.level <= 3 }.map { ($0.id, $0.plain, $0.md.level) } }
}

/// A conversation as the read-through summed it up: CTX_HOME/memory/cards/<key>.json.
struct WikiCard: Equatable {
    var key: String
    var title = ""
    var src = ""
    var from = "", to = ""
    var messages = 0, mine = 0
    var about = ""
    var facts: [String] = []
    var open: [String] = []
    var found = true

    init(key: String) { self.key = key }
    init(key: String, _ d: [String: Any]) {
        self.key = key
        func words(_ v: Any?) -> [String] {
            if let s = v as? String { return s.isEmpty ? [] : [s] }
            return ((v as? [Any]) ?? []).compactMap { one in
                if let s = one as? String { return s }
                guard let d = one as? [String: Any] else { return nil }
                return (d["what"] as? String) ?? (d["text"] as? String) ?? d.values.compactMap { $0 as? String }.sorted().joined(separator: ", ")
            }.filter { !$0.isEmpty }
        }
        title = d["_title"] as? String ?? d["title"] as? String ?? ""
        src = d["_src"] as? String ?? ""
        from = d["_from"] as? String ?? ""
        to = d["_to"] as? String ?? ""
        messages = d["_n"] as? Int ?? 0
        mine = d["_mine"] as? Int ?? 0
        about = words(d["about"]).joined(separator: " ")
        facts = words(d["facts"])
        open = words(d["open"])
    }

    /// "450 messages, 200 yours  ·  mar 2019 to nov 2026"
    var meta: String {
        var parts: [String] = []
        if messages > 0 { parts.append("\(Words.count(messages)) message\(messages == 1 ? "" : "s")" + (mine > 0 ? ", \(Words.count(mine)) yours" : "")) }
        let a = from.count >= 10 ? Words.day(String(from.prefix(10))) : from, b = to.count >= 10 ? Words.day(String(to.prefix(10))) : to
        if !a.isEmpty || !b.isEmpty { parts.append(a == b || b.isEmpty ? a : (a.isEmpty ? b : "\(a) to \(b)")) }
        return parts.joined(separator: "  ·  ")
    }
}

/// A page the filter found, with the line that matched.
struct WikiHit: Identifiable, Equatable { var id: String; var line: String }

enum WikiText {
    private static let open: Character = "\u{E000}", close: Character = "\u{E001}", bar: Character = "\u{E002}"
    private static let ref = try! NSRegularExpression(pattern: #"\[\[([crp]):([^\]|]+?)(?:\|([^\]]*))?\]\]"#)

    /// `[[r:id]]`, `[[c:key]]` and `[[p:page|title]]` as private marks that pass through the markdown reader untouched.
    static func marked(_ text: String) -> String {
        let ns = text as NSString
        var out = "", at = 0
        for m in ref.matches(in: text, range: NSRange(location: 0, length: ns.length)) {
            out += ns.substring(with: NSRange(location: at, length: m.range.location - at))
            let kind = ns.substring(with: m.range(at: 1)), key = ns.substring(with: m.range(at: 2)).trimmingCharacters(in: .whitespaces)
            let title = m.range(at: 3).location == NSNotFound ? "" : ns.substring(with: m.range(at: 3))
            out += String(open) + kind + ":" + key + (kind == "p" ? String(bar) + (title.isEmpty ? key : title) : "") + String(close)
            at = m.range.location + m.range.length
        }
        return out + ns.substring(from: at)
    }

    static func url(page id: String) -> URL? {
        var c = URLComponents(); c.scheme = "ctxwiki"; c.host = "page"; c.path = "/" + id
        return c.url
    }
    static func url(person name: String) -> URL? {
        var c = URLComponents(); c.scheme = "ctxwiki"; c.host = "person"; c.path = "/" + name
        return c.url
    }

    /// The ids of the rows (`[[r:id]]`) a text cites, in order, once each.
    static func rows(in text: String) -> [String] {
        let ns = text as NSString
        var out: [String] = []
        for m in ref.matches(in: text, range: NSRange(location: 0, length: ns.length)) where ns.substring(with: m.range(at: 1)) == "r" {
            let id = ns.substring(with: m.range(at: 2)).trimmingCharacters(in: .whitespaces)
            if !out.contains(id) { out.append(id) }
        }
        return out
    }

    // a code span (left alone), a markdown link with an optional ! before it, an address in angle brackets, or a bare
    // web address, wherever its scheme starts (the reader takes "_https://…_" for one too), up to a table's bar
    private static let address = try! NSRegularExpression(pattern: #"`[^`\n]*`|(!?)\[([^\]\n]*)\]\(\s*<?([^\s)>]*)>?\s*\)|<(https?://[^\s<>|]+)>|https?://[^\s<>()\[\]"'`|]+"#, options: [.caseInsensitive])
    // in words already read as markdown: an address in angle brackets, or a bare one up to a space, a bracket, a quote, a bar or one of the page's marks
    private static let bare = try! NSRegularExpression(pattern: #"<(https?://[^\s<>|]+)>|https?://[^\s<>()\[\]"'`|\x{E000}-\x{E002}]+"#, options: [.caseInsensitive])

    /// The web addresses in a text, each in the form `WikiLinks` compares.
    static func addresses(in text: String) -> [String] {
        let ns = text as NSString
        return address.matches(in: text, range: NSRange(location: 0, length: ns.length)).compactMap { m in
            let whole = ns.substring(with: m.range)
            if whole.hasPrefix("`") { return nil }
            let g = [3, 4].first { m.range(at: $0).location != NSNotFound }
            let u = g.map { ns.substring(with: m.range(at: $0)) } ?? whole
            return Answer.web(u) == nil ? nil : WikiLinks.norm(u)
        }
    }

    /// The name of an address's site, in lower case: what a refused address is shown as.
    static func site(_ u: String) -> String {
        let h = (URL(string: u)?.host ?? "").lowercased()
        return h.isEmpty ? "a site" : h
    }

    /// The page under the rule answers follow: an address stays a link only when `links` allows it; any other is the
    /// name of its site in plain words, so nothing someone else sent opens from the wiki: not as a link, not as the
    /// words of one, not bare, not in angle brackets, not in a table's cell. An allowed bare address becomes a link
    /// too, as it is in an answer.
    static func gate(_ text: String, _ links: WikiLinks) -> String {
        guard text.range(of: "http", options: .caseInsensitive) != nil else { return text }
        let ns = text as NSString
        var out = "", at = 0
        for m in address.matches(in: text, range: NSRange(location: 0, length: ns.length)) {
            out += ns.substring(with: NSRange(location: at, length: m.range.location - at))
            at = m.range.location + m.range.length
            let whole = ns.substring(with: m.range)
            if whole.hasPrefix("`") { out += whole; continue }
            if m.range(at: 3).location != NSNotFound {
                let words = ns.substring(with: m.range(at: 2)), url = ns.substring(with: m.range(at: 3))
                // the words of a link can be an address too: one refused is its site's name there as well, so a cell
                // or a line that sets the words bare has nothing to open
                let shown = unlink(words, links)
                // a picture, or a link to no web address, is the reader's to drop: it links neither
                if m.range(at: 1).length > 0 || Answer.web(url) == nil || links.allows(url) {
                    out += shown == words ? whole : ns.substring(with: m.range(at: 1)) + "[" + shown + "](" + url + ")"
                    continue
                }
                let h = site(url)
                out += h == "a site" || shown.lowercased().contains(h) ? shown : shown + " (" + h + ")"
                continue
            }
            if m.range(at: 4).location != NSNotFound {
                let url = ns.substring(with: m.range(at: 4))
                out += Answer.web(url) != nil && links.allows(url) ? "[" + url + "](" + url + ")" : site(url)
                continue
            }
            var url = whole, tail = ""
            while let c = url.last, ".,;:!?*".contains(c) { tail = String(c) + tail; url.removeLast() }
            if Answer.web(url) != nil, links.allows(url) { out += "[" + url + "](" + url + ")" + tail } else { out += site(url) + tail }
        }
        return out + ns.substring(from: at)
    }

    /// Words under the same rule, as they are, with no link made: every address in them that `links` refuses becomes
    /// its site's name; one it allows stays as written, out of its angle brackets.
    static func unlink(_ words: String, _ links: WikiLinks) -> String {
        guard words.range(of: "http", options: .caseInsensitive) != nil else { return words }
        let ns = words as NSString
        var out = "", at = 0
        for m in bare.matches(in: words, range: NSRange(location: 0, length: ns.length)) {
            out += ns.substring(with: NSRange(location: at, length: m.range.location - at))
            at = m.range.location + m.range.length
            var url = ns.substring(with: m.range(at: 1).location != NSNotFound ? m.range(at: 1) : m.range), tail = ""
            while let c = url.last, ".,;:!?*".contains(c) { tail = String(c) + tail; url.removeLast() }
            out += (Answer.web(url) != nil && links.allows(url) ? url : site(url)) + tail
        }
        return out + ns.substring(from: at)
    }

    /// A block as the markdown reader made it, under the same rule, so nothing it took for a link gets past: a link
    /// `links` refuses loses the link (its words already name the site), and in words that are not code every refused
    /// address is its site's name. Lines, a table's head and its cells alike. The pages about you are set through this
    /// alone; the wiki through gate first, then this.
    static func gate(_ block: MDBlock, _ links: WikiLinks) -> MDBlock {
        func one(_ bits: [Bit]) -> [Bit] {
            bits.map { bit in
                guard case .span(var s) = bit else { return bit }
                if let l = s.link, Answer.web(l) == nil || !links.allows(l) { s.link = nil }
                if !s.code { s.text = unlink(s.text, links) }
                return .span(s)
            }
        }
        var b = block
        b.bits = one(b.bits)
        b.header = b.header.map(one)
        b.rows = b.rows.map { $0.map(one) }
        return b
    }

    /// A page's markdown as blocks to draw. `names` finds people in the prose; `pages` says which of them have a page;
    /// `links` which web addresses may be links (gate).
    static func parse(_ raw: String, names: PeopleModel, pages: [String: String], size: CGFloat = 16, links: WikiLinks = WikiLinks()) -> [WikiBlock] {
        MD.parse(marked(gate(raw, links)), cites: 0).map { read in
            let b = gate(read, links)
            var out = WikiBlock(id: b.id, md: b)
            guard b.kind == .paragraph || b.kind == .item || b.kind == .quote || b.kind == .heading else { return out }
            let head = b.kind == .heading
            let pt: CGFloat = head ? [24, 24, 20, 17, 16][min(b.level, 4)] : size
            var text = AttributedString(), plain = ""
            for bit in b.bits {
                guard case .span(let s) = bit else { continue }
                // the span, cut at each mark
                var buf = "", mark: String? = nil, skip = false
                func flush() {
                    guard !buf.isEmpty else { return }
                    plain += buf
                    text += styled(buf, s, pt, head: head, quote: b.kind == .quote, names: s.code || s.link != nil ? nil : names, pages: pages)
                    buf = ""
                }
                for ch in s.text {
                    if ch == open { flush(); mark = "" } else if ch == close, let m = mark {
                        mark = nil
                        let kind = m.prefix(1), rest = String(m.dropFirst(2))
                        if kind == "p" {
                            let parts = rest.split(separator: bar, maxSplits: 1).map(String.init)
                            var a = AttributedString(parts.last ?? rest)
                            a.font = font(s, pt, head: head, quote: b.kind == .quote)
                            a.foregroundColor = Ink.ink
                            a.swiftUI.underlineStyle = Text.LineStyle(pattern: .dot, color: Ink.faint)
                            a.link = url(page: parts.first ?? rest)
                            text += a
                            plain += parts.last ?? rest
                        } else {
                            let r = WikiRef(row: kind == "r", key: rest)
                            if !out.refs.contains(r) { out.refs.append(r) }
                            skip = plain.last == " " || plain.isEmpty       // a mark in mid-paragraph leaves one space, not two
                        }
                    } else if mark != nil { mark!.append(ch) } else if skip, ch == " " { continue } else { skip = false; buf.append(ch) }
                }
                flush()
            }
            // the marks stood at the end of the paragraph: what is left of the space before them goes
            while let last = text.characters.last, last == " " { text.characters.removeLast() }
            out.plain = plain.trimmingCharacters(in: .whitespaces)
            out.read = out.plain.lowercased().hasPrefix("my read:")
            if out.read, let r = text.range(of: "my read:", options: .caseInsensitive) { text[r].foregroundColor = Ink.soft; text[r].font = .system(size: pt - 2.5, weight: .semibold) }
            out.text = text
            return out
        }
    }

    private static func font(_ s: Styled, _ size: CGFloat, head: Bool, quote: Bool) -> Font {
        if s.code { return .system(size: size * 0.86, design: .monospaced) }
        let f = Font.system(size: size, weight: s.bold ? .semibold : (head ? .medium : .regular), design: .serif)
        return s.italic || quote ? f.italic() : f
    }

    /// A run in one style. A known person's name in it is one link: to their page in the wiki, or to their panel.
    private static func styled(_ t: String, _ s: Styled, _ size: CGFloat, head: Bool, quote: Bool, names: PeopleModel?, pages: [String: String]) -> AttributedString {
        func plain(_ part: String) -> AttributedString {
            var a = AttributedString(part)
            a.font = font(s, size, head: head, quote: quote)
            a.foregroundColor = quote ? Ink.soft : (head ? Ink.ink : Ink.ink.opacity(0.9))
            if s.code { a.backgroundColor = Ink.wash }
            if s.strike { a.strikethroughStyle = .single }
            if let l = s.link, let u = Answer.web(l) { a.link = u; a.foregroundColor = Ink.ink; a.swiftUI.underlineStyle = Text.LineStyle(pattern: .solid, color: Ink.faint) }
            return a
        }
        guard let names, !names.isEmpty, !head else { return plain(t) }
        // words with their places, so a run of them can be cut out whole
        var words: [(text: String, range: Range<String.Index>)] = []
        var i = t.startIndex
        while i < t.endIndex {
            if t[i].isWhitespace { i = t.index(after: i); continue }
            var j = i
            while j < t.endIndex, !t[j].isWhitespace { j = t.index(after: j) }
            words.append((String(t[i..<j]), i..<j))
            i = j
        }
        let runs = names.runs(words.map(\.text))
        guard !runs.isEmpty else { return plain(t) }
        var out = AttributedString(), at = t.startIndex
        for r in runs {
            let from = words[r.at].range.lowerBound
            var to = words[r.at + r.count - 1].range.upperBound
            // the comma after a name is not part of it
            while to > from, let c = t[..<to].last, !(c.isLetter || c.isNumber) { to = t.index(before: to) }
            if t[from..<to].hasSuffix("'s") || t[from..<to].hasSuffix("\u{2019}s") { to = t.index(to, offsetBy: -2) }
            guard from >= at, to > from else { continue }
            out += plain(String(t[at..<from]))
            var a = plain(String(t[from..<to]))
            a.swiftUI.underlineStyle = Text.LineStyle(pattern: .dot, color: Ink.faint)
            a.link = pages[r.name.lowercased()].flatMap { url(page: $0) } ?? url(person: r.name)
            out += a
            at = to
        }
        return out + plain(String(t[at...]))
    }
}

/// The wiki as the app holds it: the index, the page that is open, the filter. It reads the engine's files as they
/// are and writes nothing to them.
@Observable final class WikiModel {
    enum Sort: String, CaseIterable { case closeness, recency, name }
    let home: URL
    @ObservationIgnored weak var engine: Engine?
    var entries: [WikiEntry] = []
    var loaded = false
    var openID = "front"
    var page: WikiPage?
    var briefing = false                // the five short pages are showing in the wiki's place
    var building = false                // the state of the wiki's writing is showing in the page's place
    var filter = "" { didSet { if filter != oldValue { search() } } }
    var hits: [WikiHit] = []
    var folded: Set<String> = []
    var sort: Sort = .closeness
    var focusFilter = 0
    var paras: [String: [WikiPara]] = [:]     // page -> its paragraphs as the engine names them, when it can edit them
    var removed: Set<String> = []            // "page#anchor" just removed, while it can still be undone
    var gone: Set<String> = []               // removed for good, until the page is read again
    var holding: Set<String> = []            // pages kept as they were while a removal can still be undone
    var noting: String?                      // the paragraph a note is being written on
    var noteDraft = ""
    var jump: Int?                      // a heading the outline asked for
    var card: WikiCard?                 // a conversation a paragraph rests on, open in the panel on the right
    @ObservationIgnored private var token = 0
    @ObservationIgnored private var texts: [String: String] = [:]      // pages read for the filter
    @ObservationIgnored var names = PeopleModel()
    /// the owner's setting links_from_others: set by the app model, off until then
    @ObservationIgnored var linksFromOthers: () -> Bool = { false }
    @ObservationIgnored private var vouched: [String: Set<String>] = [:]      // page -> the owner's own addresses among the rows it cites
    @ObservationIgnored private var asked: [String: [String]] = [:]           // page -> the rows looked up for it

    init(home: URL) { self.home = home }

    /// Which addresses on this page may be links, from what is known of its rows so far.
    func links(_ page: String) -> WikiLinks { WikiLinks(widen: linksFromOthers(), mine: vouched[page] ?? []) }

    /// Looks up the rows cited beside each web address on the page (at most 40, by `thread`), keeps the addresses the
    /// owner's own rows hold, and draws the page again with those as links. Until then every address is plain words.
    func vouch(_ id: String, _ raw: String) {
        guard !Probe.on, !Engine.debug, let engine, !linksFromOthers() else { return }
        var ids: [String] = []
        for para in raw.components(separatedBy: "\n\n") where para.range(of: "http", options: .caseInsensitive) != nil {
            for r in WikiText.rows(in: para) where !ids.contains(r) { ids.append(r) }
        }
        ids = Array(ids.prefix(40))
        guard !ids.isEmpty, asked[id] != ids else { return }
        asked[id] = ids
        var mine = Set<String>(), left = ids.count
        for r in ids {
            engine.json(["thread", r, "--around", "0", "--json"], timeout: 20) { [weak self] obj in
                DispatchQueue.main.async {
                    if let obj { mine.formUnion(WikiLinks.mine(inThread: obj)) }
                    left -= 1
                    guard left == 0, let self, self.asked[id] == ids else { return }
                    let was = self.vouched[id] ?? []
                    self.vouched[id] = mine
                    if mine != was { self.regate(id) }
                }
            }
        }
    }

    /// The owner changed links_from_others: the open page is drawn again under it.
    func relink() {
        guard let p = page else { return }
        regate(p.entry.id)
        vouch(p.entry.id, p.raw)
    }

    /// The open page drawn again under what is now known of its links, off the main thread.
    private func regate(_ id: String) {
        guard let now = page, now.entry.id == id else { return }
        let named = paras[id] ?? [], names = self.names, pages = personPages, links = self.links(id)
        DispatchQueue.global(qos: .userInitiated).async {
            let blocks = named.isEmpty ? WikiText.parse(now.raw, names: names, pages: pages, links: links)
                                       : WikiText.parse(now.raw, paras: named, names: names, pages: pages, links: links)
            // only over the same text: a page opened or changed since is drawn by whatever opened or changed it
            DispatchQueue.main.async { if let p = self.page, p.entry.id == id, p.raw == now.raw { self.page = WikiPage(entry: now.entry, raw: now.raw, blocks: blocks) } }
        }
    }

    var dir: URL { home.appendingPathComponent("memory/wiki", isDirectory: true) }
    var exists: Bool { !entries.isEmpty }
    var entry: WikiEntry? { entries.first { $0.id == openID } }
    var words: Int { entries.reduce(0) { $0 + $1.words } }

    /// The pages of one kind, in the order the owner asked for: people by closeness, how lately, or name; years newest first.
    func list(_ kind: WikiEntry.Kind) -> [WikiEntry] {
        let all = entries.filter { $0.kind == kind }
        switch kind {
        // newest first: by the engine's order when it gave one (a quarter sorts inside its year), else by the title
        case .year:
            let ordered = all.contains { $0.rank > 1000 }
            return all.sorted { ordered && $0.rank != $1.rank ? $0.rank > $1.rank : $0.title.localizedStandardCompare($1.title) == .orderedDescending }
        case .person:
            switch sort {
            case .closeness: return all.sorted { $0.rank < $1.rank }
            case .recency: return all.sorted { ($0.updated, $1.rank) > ($1.updated, $0.rank) }
            case .name: return all.sorted { $0.title.localizedCaseInsensitiveCompare($1.title) == .orderedAscending }
            }
        default: return all.sorted { $0.rank < $1.rank }
        }
    }

    /// Who has a page: lower-case name -> page id.
    var personPages: [String: String] { Dictionary(entries.filter { $0.kind == .person }.map { ($0.title.lowercased(), $0.id) }, uniquingKeysWith: { a, _ in a }) }

    func take(_ list: [WikiEntry]) {
        entries = list
        // a page for a group ("the committee") is filed with people, and is not a name to find in a sentence
        names.list = list.filter(\.isName).map { Person(name: $0.title) }
        loaded = true
        if !list.contains(where: { $0.id == openID }) { openID = list.first { $0.kind == .front }?.id ?? list.first?.id ?? "front" }
    }

    /// index.json as the engine writes it: {"v", "updated", "pages": [...]}, or the list alone.
    static func entries(_ obj: Any) -> [WikiEntry] {
        let rows = (obj as? [[String: Any]]) ?? ((obj as? [String: Any])?["pages"] as? [[String: Any]]) ?? []
        return rows.enumerated().compactMap { WikiEntry($1, rank: $0) }
    }

    /// Reads index.json, off the main thread. A render or a test is given its pages and reads nothing.
    func load() {
        guard !Engine.debug else { loaded = true; return }
        let file = dir.appendingPathComponent("index.json")
        DispatchQueue.global(qos: .userInitiated).async {
            var list: [WikiEntry] = []
            if let d = try? Data(contentsOf: file), let obj = try? JSONSerialization.jsonObject(with: d) {
                list = WikiModel.entries(obj)
            }
            DispatchQueue.main.async {
                let changed = list != self.entries
                self.take(list)
                if changed || self.page == nil, !list.isEmpty { self.show(self.openID) }
            }
        }
    }

    /// Opens a page: its file is read and taken apart off the main thread, so a long one never holds the window.
    func show(_ id: String) {
        loadParas(id)
        guard let e = entries.first(where: { $0.id == id }) ?? entries.first(where: { $0.id.split(separator: "/").last.map(String.init) == id }) else { return }
        openID = e.id
        briefing = false
        building = false
        guard !Engine.debug else { return }
        token += 1
        let mine = token, file = dir.appendingPathComponent(e.path), names = self.names, pages = personPages, links = self.links(e.id)
        DispatchQueue.global(qos: .userInitiated).async {
            let raw = (try? String(contentsOf: file, encoding: .utf8)) ?? ""
            let blocks = WikiText.parse(raw, names: names, pages: pages, links: links)
            DispatchQueue.main.async { if self.token == mine { self.page = WikiPage(entry: e, raw: raw, blocks: blocks); self.vouch(e.id, raw) } }
        }
    }

    /// A page given as text: for a render, a test, and the measure of how long a long page takes.
    func set(_ e: WikiEntry, text: String) {
        openID = e.id
        page = WikiPage(entry: e, raw: text, blocks: WikiText.parse(text, names: names, pages: personPages, links: links(e.id)))
    }

    /// The filter: titles at once, then the pages themselves, read from this mac, with the line that matched.
    func search() {
        let q = filter.trimmingCharacters(in: .whitespaces).lowercased()
        token += 1
        let mine = token
        guard q.count >= 2 else { hits = []; return }
        hits = entries.filter { $0.title.lowercased().contains(q) }.map { WikiHit(id: $0.id, line: $0.summary) }
        guard !Engine.debug else { return }
        let entries = self.entries, dir = self.dir
        var cache = texts
        func local() {
            DispatchQueue.global(qos: .userInitiated).async {
                let words = q.split(separator: " ").map(String.init)
                var found: [(WikiHit, Int)] = []
                for e in entries {
                    let text = cache[e.id] ?? ((try? String(contentsOf: dir.appendingPathComponent(e.path), encoding: .utf8)) ?? "")
                    cache[e.id] = text
                    let inTitle = words.filter { e.title.lowercased().contains($0) }.count
                    var best = "", top = 0
                    for para in text.components(separatedBy: "\n\n") where !para.hasPrefix("#") {
                        let low = para.lowercased()
                        let n = words.filter { low.contains($0) }.count
                        if n > top { top = n; best = para }
                    }
                    guard inTitle > 0 || top == words.count else { continue }
                    let line = WikiText.marked(best).filter { !($0 >= "\u{E000}" && $0 <= "\u{E002}") }.replacingOccurrences(of: "\n", with: " ")
                    found.append((WikiHit(id: e.id, line: inTitle > 0 && top == 0 ? e.summary : WikiModel.around(q, in: line)), inTitle * 100 + top))
                }
                let out = found.sorted { $0.1 > $1.1 }.prefix(40).map(\.0)
                DispatchQueue.main.async { if self.token == mine { self.hits = out; self.texts = cache } }
            }
        }
        local()
    }

    /// The part of a long line round the first word that was asked for.
    static func around(_ q: String, in line: String, most: Int = 150) -> String {
        guard line.count > most, let w = q.split(separator: " ").first, let r = line.range(of: w, options: .caseInsensitive) else { return line }
        let at = line.distance(from: line.startIndex, to: r.lowerBound)
        let from = max(0, at - 50)
        let cut = line.dropFirst(from).prefix(most)
        return (from > 0 ? "…" : "") + cut + (from + most < line.count ? "…" : "")
    }
}

extension AppModel {
    /// "ask about this page": a new chat narrowed to that person or that year, with the page's title already typed.
    func askAbout(page e: WikiEntry) {
        newChat()
        var s = Scope()
        if e.kind == .person { s.people = [e.title] }
        if e.kind == .year, let y = Int(e.title.prefix(4)), e.title.count >= 4 { s.after = "\(y)-01-01"; s.before = "\(y + 1)-01-01" }
        ask.scope = s
        ask.draft = e.kind == .person || e.kind == .year ? "" : e.title + ": "
        if e.kind == .person || e.kind == .year { ask.draft = e.kind == .year ? "in \(e.title): " : "about \(e.title): " }
        focusAsk += 1
    }

    /// A link inside a page: another page, or a person who has none.
    func openWiki(_ url: URL) -> Bool {
        guard url.scheme == "ctxwiki" else { return false }
        let what = String(url.path.dropFirst()).removingPercentEncoding ?? String(url.path.dropFirst())
        if url.host == "page" { if !Probe.on { wiki.show(what) } } else if url.host == "person" { showPerson(what) }
        return true
    }
}

// MARK: the reader

/// "about you", once the wiki is written: the pages down the left of the page area, the one that is open in a
/// measure made for reading, and its headings at the right when the window has the room.
struct WikiReader: View {
    @Environment(AppModel.self) private var model

    static let index: CGFloat = 228, outline: CGFloat = 168, measure: CGFloat = 660

    var body: some View {
        let wiki = model.wiki
        GeometryReader { geo in
            let w = geo.size.width
            let showIndex = w >= 560
            let showOutline = w >= WikiReader.index + WikiReader.outline + 520
            HStack(spacing: 0) {
                if showIndex {
                    WikiIndex().frame(width: WikiReader.index)
                    Rectangle().fill(Ink.line).frame(width: 1)
                }
                if wiki.building {
                    WikiBuildPage(back: !showIndex)
                } else if let page = wiki.page, page.entry.id == wiki.openID {
                    WikiPageView(page: page, outline: showOutline, back: !showIndex)
                } else if let e = wiki.entry {
                    VStack(alignment: .leading, spacing: 10) {
                        Text(e.title).font(.system(size: 28, weight: .regular, design: .serif)).foregroundStyle(Ink.ink)
                        HStack(spacing: 8) { Spinner(size: 10); Text("opening").font(.system(size: 12, weight: .medium)).foregroundStyle(Ink.soft) }
                    }
                    .padding(.horizontal, 36).padding(.top, 30)
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                } else {
                    Color.clear
                }
            }
        }
        .environment(\.openURL, OpenURLAction { url in
            if model.openWiki(url) { return .handled }
            // only a web address the page kept as a link (WikiText.gate): one from someone else's message never is one
            if !Probe.on, let u = Answer.web(url.absoluteString) { NSWorkspace.shared.open(u) }
            return .handled
        })
        .onAppear { wiki.load(); if !Probe.on { model.wikiBuild.load() } }
    }
}

/// The wiki's writing, in the page's place: what exists, what it is doing now, what the rest would take before it
/// starts, and pause or carry on. The same block settings shows, reading the same object.
struct WikiBuildPage: View {
    @Environment(AppModel.self) private var model
    var back = false

    var body: some View {
        let b = model.wikiBuild
        ScrollView {
            ScrollTop()
            VStack(alignment: .leading, spacing: 0) {
                if back || model.wiki.exists {
                    Button { model.wiki.building = false } label: {
                        HStack(spacing: 5) { Image(systemName: "chevron.left").font(.system(size: 9, weight: .bold)); Text("the wiki") }
                    }
                    .buttonStyle(QuietButton(size: 12)).accessibilityLabel("back to the wiki")
                    .probe("wiki.build.back", .button, scrolls: true)
                    .padding(.bottom, 14)
                }
                HStack(alignment: .firstTextBaseline, spacing: 10) {
                    Text("how the wiki is written").font(.system(size: 30, weight: .regular, design: .serif)).tracking(-0.4).foregroundStyle(Ink.ink)
                        .fixedSize(horizontal: false, vertical: true)
                        .probe("wiki.build.title", .text, scrolls: true)
                        .accessibilityAddTraits(.isHeader)
                    Pill(text: b.pill.0, tone: b.pill.1)
                }
                SetText.about("context writes these pages from your archive, on your own ai plan: a page for each person who matters, each project, each year and each theme. every paragraph is checked against the messages it cites. it says what it would take before it starts, and you can pause it: what is written stays.")
                    .padding(.top, 10).padding(.bottom, 18)
                WikiBuildBlock()
                    .padding(16)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Ink.raised, in: RoundedRectangle(cornerRadius: Radius.card, style: .continuous))
                    .overlay(RoundedRectangle(cornerRadius: Radius.card, style: .continuous).strokeBorder(Ink.line, lineWidth: 1))
            }
            .frame(maxWidth: WikiReader.measure, alignment: .leading)
            .padding(.horizontal, 36).padding(.top, 26).padding(.bottom, 40)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

/// At the foot of the list of pages: where the writing stands, in a line, and the door to all of it.
struct WikiBuildFoot: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let b = model.wikiBuild, on = model.wiki.building
        Button { model.wiki.building = true; model.wiki.briefing = false } label: {
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 6) {
                    Text("writing").font(.system(size: Face.label, weight: on ? .medium : .regular)).foregroundStyle(Ink.ink).lineLimit(1).fixedSize()
                    if b.running { Spinner(size: 9) }
                }
                Text(WikiBuildFoot.line(b)).font(.system(size: 11)).monospacedDigit().foregroundStyle(Ink.soft)
                    .fixedSize(horizontal: false, vertical: true)
                    .probe("wiki.build.line", .text, scrolls: true)
                if b.running, let p = b.progress, p.of > 0 { Meter(part: Double(p.n) / Double(p.of)).padding(.top, 2) }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 10).padding(.vertical, 7)
            .background(Ink.ink.opacity(on ? 0.075 : 0), in: RoundedRectangle(cornerRadius: Radius.row, style: .continuous))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain).ring(Radius.row, inset: 0)
        .accessibilityLabel("how the wiki is written: " + WikiBuildFoot.line(b))
        .padding(.horizontal, 8).padding(.top, 8)
        .probe("wiki.build.foot", .block, group: "wiki.index")
    }

    /// "writing people: 30 of 250", "paused", "22 pages, and more to write", "22 pages"
    static func line(_ b: WikiBuild) -> String {
        if b.running { return b.progress == nil ? "starting" : b.doing }
        if b.paused { return "paused. what is written stays." }
        guard let s = b.status else { return "what exists, and what is left" }
        let pages = "\(Words.count(s.total)) page\(s.total == 1 ? "" : "s") written"
        if let e = b.estimate, e.pages > 0 { return pages + ", \(Words.count(e.pages)) more to write" }
        return pages
    }
}

/// The pages, down the left of the reader: the front page, then people, projects, years and themes, each a group that
/// folds, with its count; a field that filters them and searches inside them.
struct WikiIndex: View {
    @Environment(AppModel.self) private var model
    @FocusState private var typing: Bool

    var body: some View {
        @Bindable var wiki = model.wiki
        let filtering = wiki.filter.trimmingCharacters(in: .whitespaces).count >= 2
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 7) {
                Image(systemName: "magnifyingglass").font(.system(size: 11, weight: .medium)).foregroundStyle(Ink.soft).accessibilityHidden(true)
                TextField("", text: $wiki.filter, prompt: Text("find in the wiki").foregroundStyle(Ink.soft))
                    .textFieldStyle(.plain).font(.system(size: 13)).foregroundStyle(Ink.ink).tint(Ink.ember)
                    .focused($typing)
                    .accessibilityLabel("find in the wiki")
                    .onChange(of: typing) { _, on in model.sideTyping = on }
                if !wiki.filter.isEmpty {
                    Button { wiki.filter = "" } label: { Image(systemName: "xmark").font(.system(size: 9, weight: .bold)).foregroundStyle(Ink.soft).frame(width: 18, height: 18).contentShape(Rectangle()) }
                        .buttonStyle(.plain).accessibilityLabel("clear the filter")
                }
            }
            .padding(.horizontal, 10).frame(height: 30)
            .background(Ink.wash.opacity(0.7), in: RoundedRectangle(cornerRadius: Radius.row, style: .continuous))
            .padding(.horizontal, 12).padding(.top, 14).padding(.bottom, 8)
            .probe("wiki.filter", .block, group: "wiki.index")
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 1) {
                    if filtering {
                        if wiki.hits.isEmpty {
                            Text("no page has that.").font(.system(size: 12)).foregroundStyle(Ink.soft).padding(.horizontal, 10).padding(.top, 8)
                                .probe("wiki.none", .line, scrolls: true)
                        }
                        ForEach(wiki.hits) { h in
                            if let e = wiki.entries.first(where: { $0.id == h.id }) { WikiRow(entry: e, line: h.line, on: !wiki.briefing && !wiki.building && wiki.openID == e.id) }
                        }
                    } else {
                        ForEach(wiki.list(.front)) { e in WikiRow(entry: e, on: !wiki.briefing && !wiki.building && wiki.openID == e.id) }
                        ForEach([WikiEntry.Kind.person, .project, .year, .theme], id: \.self) { kind in
                            let rows = wiki.list(kind)
                            if !rows.isEmpty {
                                WikiGroupHead(kind: kind, count: rows.count)
                                if !wiki.folded.contains(kind.rawValue) {
                                    ForEach(rows) { e in WikiRow(entry: e, on: !wiki.briefing && !wiki.building && wiki.openID == e.id) }
                                }
                            }
                        }
                    }
                }
                .padding(.horizontal, 8).padding(.bottom, 10)
            }
            Rectangle().fill(Ink.line).frame(height: 1)
            WikiBuildFoot()
            // the five short pages every answer starts from: still here, under their own name
            Button { wiki.briefing = true; wiki.building = false } label: {
                VStack(alignment: .leading, spacing: 1) {
                    Text("briefing").font(.system(size: Face.label, weight: wiki.briefing ? .medium : .regular)).foregroundStyle(Ink.ink)
                    Text("what the model reads first").font(.system(size: 11)).foregroundStyle(Ink.soft).lineLimit(1)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 10).padding(.vertical, 7)
                .background(Ink.ink.opacity(wiki.briefing ? 0.075 : 0), in: RoundedRectangle(cornerRadius: Radius.row, style: .continuous))
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain).ring(Radius.row, inset: 0)
            .accessibilityLabel("briefing: what the model reads first")
            .padding(.horizontal, 8).padding(.top, 1).padding(.bottom, 8)
            .probe("wiki.briefing", .block, group: "wiki.index")
        }
        .frame(maxHeight: .infinity, alignment: .top)
        .onChange(of: wiki.focusFilter) { _, _ in typing = true }
        .probe("wiki.index", .block)
    }
}

/// "people  ·  240", with the fold, and for people the order they are listed in.
struct WikiGroupHead: View {
    @Environment(AppModel.self) private var model
    let kind: WikiEntry.Kind
    let count: Int

    var body: some View {
        let wiki = model.wiki
        let folded = wiki.folded.contains(kind.rawValue)
        HStack(spacing: 6) {
            Button { if folded { wiki.folded.remove(kind.rawValue) } else { wiki.folded.insert(kind.rawValue) } } label: {
                HStack(spacing: 6) {
                    Image(systemName: "chevron.down").font(.system(size: 7.5, weight: .bold)).foregroundStyle(Ink.soft).rotationEffect(.degrees(folded ? -90 : 0)).frame(width: 10)
                    Text(kind.group).font(Face.heading).foregroundStyle(Ink.soft)
                    Text(Words.count(count)).font(.system(size: Face.micro)).monospacedDigit().foregroundStyle(Ink.soft.opacity(0.75))
                }
                .frame(height: 22).contentShape(Rectangle())
            }
            .buttonStyle(.plain).ring(5, inset: 1)
            .accessibilityLabel("\(kind.group), \(count) page\(count == 1 ? "" : "s"), \(folded ? "folded" : "open")")
            Spacer(minLength: 4)
            if kind == .person, !folded {
                Menu {
                    ForEach(WikiModel.Sort.allCases, id: \.self) { s in
                        Button("by " + (s == .recency ? "how lately" : s.rawValue)) { wiki.sort = s }
                    }
                } label: {
                    Text(wiki.sort == .recency ? "lately" : wiki.sort.rawValue).font(.system(size: Face.micro)).foregroundStyle(Ink.soft)
                }
                .menuStyle(.borderlessButton).menuIndicator(.hidden).fixedSize()
                .accessibilityLabel("order of people: by \(wiki.sort.rawValue)")
                .help("the order people are listed in")
                .probe("wiki.sort", .button, scrolls: true)
            }
        }
        .padding(.leading, 6).padding(.trailing, 8).padding(.top, 12).padding(.bottom, 2)
        .probe("wiki.head", .block, group: "wiki.rows", scrolls: true)
    }
}

/// One page in the list: its title, and under a filter the line that matched.
struct WikiRow: View {
    @Environment(AppModel.self) private var model
    let entry: WikiEntry
    var line = ""
    let on: Bool
    @State private var hover = false
    private var front: Bool { entry.kind == .front }

    var body: some View {
        Button { model.wiki.show(entry.id); if Engine.debug { model.wiki.briefing = false } } label: {
            VStack(alignment: .leading, spacing: 2) {
                Text(front ? "front page" : entry.title).font(.system(size: Face.label, weight: on ? .medium : .regular)).foregroundStyle(Ink.ink).lineLimit(1).truncationMode(.tail)
                if !line.isEmpty {
                    Text(line).font(.system(size: 11)).foregroundStyle(Ink.soft).lineLimit(2).lineSpacing(1.5)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 10).padding(.vertical, line.isEmpty ? 0 : 6).frame(minHeight: 28)
            .background(Ink.ink.opacity(on ? 0.075 : (hover ? 0.04 : 0)), in: RoundedRectangle(cornerRadius: Radius.row, style: .continuous))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
        .ring(Radius.row, inset: 0)
        .help(entry.summary.isEmpty ? entry.title : entry.summary)
        .accessibilityLabel((front ? "front page" : entry.title) + (line.isEmpty ? "" : ": " + line))
        .accessibilityAddTraits(on ? [.isSelected] : [])
        .probe("wiki.row", .block, group: "wiki.rows", scrolls: true)
    }
}

/// One page, set to be read: its name and where it came from, then the page; the headings beside it when there is room.
struct WikiPageView: View {
    @Environment(AppModel.self) private var model
    let page: WikiPage
    let outline: Bool
    var back = false
    @State private var copied = false

    var body: some View {
        let e = page.entry
        let heads = page.outline
        HStack(alignment: .top, spacing: 0) {
            ScrollViewReader { proxy in
                ScrollView {
                    ScrollTop()
                    LazyVStack(alignment: .leading, spacing: 0) {
                        // the head of a page, set like the head of a printed one: what kind of page it is in a small
                        // line over its name, the name in the serif, then where it came from in one quiet line
                        VStack(alignment: .leading, spacing: 0) {
                            let parts = e.meta.components(separatedBy: "  ·  ")
                            Text(parts.first ?? "").font(Face.heading).foregroundStyle(Ink.soft).lineLimit(1)
                                .accessibilityHidden(true)
                            Text(e.kind == .front && e.title.lowercased() == "front" ? "what context knows about you" : e.title)
                                .font(Face.said(34)).tracking(-0.6).lineSpacing(-2).foregroundStyle(Ink.ink)
                                .fixedSize(horizontal: false, vertical: true)
                                .probe("wiki.title", .text, group: "wiki.head", scrolls: true)
                                .accessibilityAddTraits(.isHeader)
                                .padding(.top, Space.s)
                            // on one line where it fits; otherwise broken where the sense breaks, not in the middle of a figure
                            ViewThatFits(in: .horizontal) {
                                Text(parts.dropFirst().joined(separator: "  ·  ")).lineLimit(1).fixedSize()
                                VStack(alignment: .leading, spacing: 3) {
                                    Text(parts.dropFirst().prefix(1).joined(separator: "  ·  ")).lineLimit(1)
                                    if parts.count > 2 { Text(parts.dropFirst(2).joined(separator: "  ·  ")).lineLimit(1) }
                                }
                            }
                            .font(.system(size: Face.small)).monospacedDigit().foregroundStyle(Ink.soft)
                            .accessibilityLabel(e.meta)
                            .probe("wiki.meta", .block, group: "wiki.head", scrolls: true)
                            .padding(.top, Space.m)
                            HStack(spacing: Space.l) {
                                Button("ask about this page") { model.askAbout(page: e) }.buttonStyle(QuietButton(size: Face.small))
                                    .help("a new chat, narrowed to this page where it can be")
                                    .probe("wiki.ask", .button, group: "wiki.acts", scrolls: true)
                                Button(copied ? "copied" : "copy as markdown") { Clip.copy(page.raw); copied = true }.buttonStyle(QuietButton(size: Face.small))
                                    .probe("wiki.copy", .button, group: "wiki.acts", scrolls: true)
                                Spacer(minLength: 0)
                            }
                            .padding(.top, Space.l)
                            Rectangle().fill(Ink.line).frame(height: 1).padding(.top, Space.l).padding(.bottom, Space.xl + 4)
                        }
                        ForEach(Array(page.blocks.enumerated()), id: \.element.id) { n, b in
                            // the page's own first heading repeats its name: the name is already set above
                            if !(n == 0 && b.md.kind == .heading && b.md.level == 1) {
                                WikiLine(page: e.id, block: b, first: n == page.blocks.firstIndex { $0.md.kind == .paragraph })
                                    .padding(.top, n == 0 || (n == 1 && page.blocks[0].md.kind == .heading && page.blocks[0].md.level == 1) ? 0 : WikiLine.gap(b, after: page.blocks[n - 1]))
                                    .id(b.id)
                            }
                        }
                    }
                    .frame(maxWidth: WikiReader.measure, alignment: .leading)
                    .padding(.horizontal, 40).padding(.top, 36).padding(.bottom, 72)
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
                .onChange(of: model.wiki.jump) { _, id in
                    if let id { model.wiki.jump = nil; withAnimation(NSWorkspace.shared.accessibilityDisplayShouldReduceMotion ? nil : .easeOut(duration: 0.18)) { proxy.scrollTo(id, anchor: .top) } }
                }
            }
            if outline, heads.count >= 2 {
                ScrollView {
                    VStack(alignment: .leading, spacing: 0) {
                        Text("on this page").font(.system(size: 11, weight: .semibold)).foregroundStyle(Ink.soft).padding(.bottom, 6)
                            .accessibilityAddTraits(.isHeader)
                        ForEach(heads, id: \.id) { h in
                            Button { model.wiki.jump = h.id } label: {
                                Text(h.title).font(.system(size: Face.small)).foregroundStyle(Ink.soft).lineLimit(2).multilineTextAlignment(.leading)
                                    .fixedSize(horizontal: false, vertical: true)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                    .padding(.leading, h.level > 2 ? 10 : 0).padding(.vertical, 4)
                                    .contentShape(Rectangle())
                            }
                            .buttonStyle(.plain).ring(4, inset: 2)
                            .probe("wiki.outline", .block, group: "wiki.outline", scrolls: true)
                        }
                    }
                    .padding(.trailing, 20).padding(.top, 34).padding(.bottom, 20)
                }
                .frame(width: WikiReader.outline)
            }
        }
        .onChange(of: page.entry.id) { _, _ in copied = false }
    }
}

/// One block of a page. A paragraph is one text, so it wraps, selects and is read as one thing; the rows and
/// conversations it rests on are small quiet chips at its end.
struct WikiLine: View {
    @Environment(AppModel.self) private var model
    let page: String
    let block: WikiBlock
    var first = false
    @State private var hover = false
    @FocusState private var focused: Bool
    private static let turn = Turn(id: -9, q: "")
    private static let answer = Answer(["answer": "wiki"], tag: "wiki")!

    static func gap(_ b: WikiBlock, after a: WikiBlock) -> CGFloat {
        if b.md.kind == .heading { return a.md.kind == .heading ? 8 : (b.md.level <= 2 ? 30 : 22) }
        if a.md.kind == .heading { return 9 }
        if b.md.kind == .item, a.md.kind == .item { return 7 }
        return 14
    }

    var body: some View {
        let b = block.md
        switch b.kind {
        case .heading:
            Text(block.text).fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
                .probe("wiki.text", .text, group: "wiki.lines", scrolls: true)
                .accessibilityAddTraits(.isHeader)
        case .paragraph:
            prose.probe("wiki.para", .block, group: "wiki.lines", scrolls: true)
        case .item:
            HStack(alignment: .firstTextBaseline, spacing: 9) {
                Text(b.marker).font(.system(size: 16, design: .serif)).monospacedDigit().foregroundStyle(Ink.soft).frame(minWidth: 12, alignment: .trailing).accessibilityHidden(true)
                prose
            }
            .padding(.leading, CGFloat(b.level) * 20)
            .probe("wiki.para", .block, group: "wiki.lines", scrolls: true)
        case .quote:
            prose.padding(.leading, 14)
                .overlay(alignment: .leading) { RoundedRectangle(cornerRadius: 1).fill(Ink.line).frame(width: 2) }
                .probe("wiki.para", .block, group: "wiki.lines", scrolls: true)
        case .code:
            CodeBlock(code: b.code, lang: b.lang)
        case .table:
            TableBlock(block: b, turn: WikiLine.turn, answer: WikiLine.answer, key: "wiki/\(page)/\(b.id)")
        case .rule:
            Rectangle().fill(Ink.line).frame(height: 1).padding(.vertical, 6)
        }
    }

    private var prose: some View { proseBare.modifier(ParaEdit(page: page, anchor: block.anchor, plain: block.plain)) }

    private var proseBare: some View {
        let wrong = model.profile.isWrong(block.plain, on: page)
        let editable = !block.anchor.isEmpty && model.wiki.para(page, anchor: block.anchor) != nil     // then the four actions of ParaEdit take this one's place
        return VStack(alignment: .leading, spacing: 6) {
            Text(block.text).lineSpacing(5.5).fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
                .opacity(wrong ? 0.5 : 1)
                .probe("wiki.text", .text, scrolls: true)
            if !block.refs.isEmpty { WikiRefs(refs: block.refs).padding(.trailing, 96) }
        }
        // said of this paragraph alone: it sits at the end of the line of chips, or in the air under a paragraph that has none
        .overlay(alignment: .bottomTrailing) {
            Group {
                if wrong {
                    Button("wrong · undo") { model.profile.mark(block.plain, on: page, wrong: false) }
                        .buttonStyle(QuietButton(size: 11))
                        .accessibilityLabel("marked wrong. undo")
                } else if !editable {
                    Button("this is wrong") { model.profile.mark(block.plain, on: page, wrong: true) }
                        .buttonStyle(QuietButton(size: 11))
                        .focused($focused)
                        .opacity(hover || focused || (Probe.on && first) ? 1 : 0)
                        .help("say this paragraph is wrong. it is kept on this mac, and the next time the page is written it is left out.")
                        .accessibilityLabel("this is wrong: " + String(block.plain.prefix(80)))
                }
            }
            .probe("wiki.wrong", .button, scrolls: true)
            .offset(y: block.refs.isEmpty ? 15 : 1)
        }
        .contentShape(Rectangle())
        .onHover { hover = $0 }
    }
}

/// What a paragraph rests on, as chips: a conversation is a small speech mark and its number, a row is its number.
struct WikiRefs: View {
    let refs: [WikiRef]
    @State private var all = false
    static let most = 8

    var body: some View {
        let shown = all ? refs : Array(refs.prefix(WikiRefs.most))
        Flow(spacing: 4, lineSpacing: 4) {
            ForEach(Array(shown.enumerated()), id: \.element.id) { i, r in WikiRefChip(ref: r, number: i + 1) }
            if refs.count > shown.count {
                Button("+\(refs.count - shown.count)") { all = true }
                    .buttonStyle(.plain).font(.system(size: 9.5, weight: .bold, design: .rounded)).monospacedDigit().foregroundStyle(Ink.soft)
                    .padding(.horizontal, 5).frame(height: 16)
                    .accessibilityLabel("\(refs.count - shown.count) more sources")
            }
        }
        .probe("wiki.refs", .block, scrolls: true)
    }
}

struct WikiRefChip: View {
    @Environment(AppModel.self) private var model
    let ref: WikiRef
    let number: Int
    @State private var hover = false

    var body: some View {
        Button { model.openRef(ref) } label: {
            HStack(spacing: 2.5) {
                if !ref.row { Image(systemName: "bubble.left.fill").font(.system(size: 6.5)).accessibilityHidden(true) }
                Text("\(number)").font(.system(size: 9.5, weight: .bold, design: .rounded)).monospacedDigit()
            }
            .foregroundStyle(hover ? Ink.paper : Ink.soft)
            .padding(.horizontal, 5).frame(minWidth: 16).frame(height: 16)
            .background(hover ? Ink.ink : Ink.wash, in: RoundedRectangle(cornerRadius: Radius.chip, style: .continuous))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
        .ring(5, inset: 1)
        .help(ref.row ? "the message this rests on" : "the conversation this rests on")
        .accessibilityLabel(ref.row ? "source \(number): a message" : "source \(number): a conversation")
        .probe("wiki.ref", .block, group: "wiki.refs", scrolls: true)
    }
}

extension AppModel {
    /// A chip at the end of a paragraph, opened in the panel on the right: a row as the message in its conversation,
    /// a conversation as the card the read-through wrote for it.
    func openRef(_ ref: WikiRef) {
        people.close()
        if ref.row {
            wiki.card = nil
            let hit = Hit(id: "wiki:0:" + ref.key, src: "", kind: "message", ts: "", thread: "", threadID: "", who: "", sender: "", text: "", url: "", offset: 0)
            ask.peekThread(hit, turn: -9, engine)
            return
        }
        ask.closeThread()
        wiki.card = WikiCard(key: ref.key)
        guard !Engine.debug else { return }
        let key = ref.key, file = engine.home.appendingPathComponent("memory/cards/\(ref.key).json")
        DispatchQueue.global(qos: .userInitiated).async {
            let d = (try? Data(contentsOf: file)).flatMap { try? JSONSerialization.jsonObject(with: $0) } as? [String: Any]
            DispatchQueue.main.async {
                guard self.wiki.card?.key == key else { return }
                if let d { self.wiki.card = WikiCard(key: key, d) } else { self.wiki.card?.found = false }
            }
        }
    }
}

/// A conversation's card in the panel: what it was, how much of it there is, what it settled and what it left open.
struct WikiCardPane: View {
    let card: WikiCard

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    if !card.src.isEmpty { SourceIcon(id: card.src, size: 16).alignmentGuide(.firstTextBaseline) { $0[.bottom] - 3 } }
                    Text(card.title.isEmpty ? (card.found ? "a conversation" : "this conversation's card is gone") : card.title)
                        .font(.system(size: 19, weight: .semibold, design: .serif)).foregroundStyle(Ink.ink)
                        .fixedSize(horizontal: false, vertical: true)
                        .probe("refs.card.title", .text, scrolls: true)
                        .accessibilityAddTraits(.isHeader)
                }
                if !card.meta.isEmpty {
                    Text(card.meta).font(.system(size: 11, weight: .medium)).monospacedDigit().foregroundStyle(Ink.soft).lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true).padding(.top, 5)
                        .probe("refs.card.meta", .text, scrolls: true)
                }
                if !card.found {
                    Text("the read-through has written it again since this page was made. rebuilding the wiki brings the page up to date.")
                        .font(.system(size: 12)).foregroundStyle(Ink.soft).lineSpacing(2).fixedSize(horizontal: false, vertical: true).padding(.top, 8)
                }
                if !card.about.isEmpty {
                    Text(card.about).font(.system(size: 14, design: .serif)).foregroundStyle(Ink.ink.opacity(0.88)).lineSpacing(3.5)
                        .fixedSize(horizontal: false, vertical: true).textSelection(.enabled).padding(.top, 12)
                        .probe("refs.card.about", .text, scrolls: true)
                }
                list("what it holds", card.facts)
                list("left open", card.open)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 16).padding(.top, 16).padding(.bottom, 24)
        }
    }

    @ViewBuilder private func list(_ title: String, _ lines: [String]) -> some View {
        if !lines.isEmpty {
            Text(title).font(.system(size: 11, weight: .semibold)).foregroundStyle(Ink.soft).padding(.top, 22).padding(.bottom, 6)
                .accessibilityAddTraits(.isHeader)
            ForEach(Array(lines.prefix(12).enumerated()), id: \.offset) { _, l in
                Text(l).font(.system(size: 13)).foregroundStyle(Ink.ink.opacity(0.9)).lineSpacing(2.5)
                    .fixedSize(horizontal: false, vertical: true).frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.vertical, 7)
                    .overlay(alignment: .bottom) { Rectangle().fill(Ink.line).frame(height: 1) }
                    .probe("refs.card.line", .text, group: "refs.card.lines", scrolls: true)
            }
        }
    }
}

// MARK: checks, on a made-up wiki

extension LayoutTest {
    static let wikiDay = "2026-11-14"

    static let wikiPages: [(String, String, WikiEntry.Kind, String, String)] = [
        ("front", "front", .front, "Who you are, in one read: the studio, the flat, the plot, and the people each rests on.", """
        # what context knows about you

        You run a two-person studio that builds small tools for allotment societies, and you have lived in the flat on Marsh Lane since 2019. [[c:whatsapp-sam-landlord]] [[r:W1021]] The studio is you and [[p:people/maya-lindqvist|Maya Lindqvist]]; the flat is you and Ines Marchetti; the plot is yours alone. [[c:slack-studio]] [[r:N88]]

        my read: you keep each of the three small on purpose. You have turned down two offers to grow the studio, and both times the reason you gave was time on the lower field. [[r:E412]] [[r:E640]]

        ## the shape of a week

        You write most mornings before nine and answer messages in batches after lunch. Fridays are for the plot, and nobody at the studio expects an answer then. [[c:slack-studio]] [[r:S2210]] [[r:S2214]] [[r:S2377]] [[r:S2391]] [[r:S2402]] [[r:S2410]] [[r:S2415]] [[r:S2418]] [[r:S2431]] [[r:S2440]]

        ## what is open now

        - The lease renewal with Sam Okafor: he has asked twice. [[r:W1044]]
        - The pricing page you owe Maya Lindqvist. [[r:S2502]]
        - The committee's water rota for spring. [[c:whatsapp-committee]]

        ## how this was written

        Every paragraph ends with what it rests on. A line that starts "my read:" is a conclusion drawn for you, not something you said.
        """),
        ("people/sam-okafor", "Sam Okafor", .person, "Your landlord since 2019. Plain and fair; asks twice before he chases.", """
        # Sam Okafor

        Your landlord since 2019. Plain and fair with you; he asks twice before he chases, and he has never raised the rent without a month's warning. [[c:whatsapp-sam-landlord]] [[r:W1021]] [[r:W1044]]

        ## the lease

        The renewal is open between you. He first raised it on the fourth of November and again six days later, when he also asked whether the deposit carries over. You told Ines Marchetti you would decide by the end of the month. [[r:W1044]] [[r:W1050]] [[r:I77]]

        > the lease renewal is due on the first. can you let me know by then whether you are staying?

        my read: he would rather keep you than find someone new. Both times he mentioned the rent he offered to hold it. [[r:E412]]

        ## repairs

        1. The boiler, in 2022: fixed inside a week, at his cost. [[r:W310]]
        2. The window latch, in 2024: you fixed it yourself and told him after. [[r:W702]]

        | when | what | who paid |
        | --- | --- | --- |
        | 2022 | boiler | Sam |
        | 2024 | window latch | you |
        """),
        ("people/ines-marchetti", "Ines Marchetti", .person, "You share the flat. She would rather not move in January.", "# Ines Marchetti\n\nYou share the flat. She would rather not move in January, and she pays the heating. [[c:imessage-ines]] [[r:I77]]\n\n## what she asks of you\n\nA decision by the end of the month, and that the rent does not jump again. [[r:I80]]\n"),
        ("people/maya-lindqvist", "Maya Lindqvist", .person, "Design partner at the studio since 2022.", "# Maya Lindqvist\n\nDesign partner at the studio since 2022. You owe her the pricing page. [[c:slack-studio]] [[r:S2502]]\n\n## how you work together\n\nShe draws first and you cut. When you disagree it is settled by whoever has to maintain the thing. [[r:S1200]]\n"),
        ("people/jonas-weber", "Jonas Weber", .person, "Runs the print shop; an introduction you promised.", "# Jonas Weber\n\nRuns the print shop on the canal. You promised to introduce him to Maya. [[r:W1500]]\n"),
        ("people/priya-raman", "Priya Raman", .person, "Chairs the committee in the years you do not.", "# Priya Raman\n\nChairs the allotment committee in the years you do not. [[c:whatsapp-committee]]\n"),
        ("people/the-allotment-committee", longName, .person, "The group, not a person: nine of you, since 2021.", "# \(longName)\n\nNine of you, since 2021. The water rota is decided here every spring. [[c:whatsapp-committee]]\n"),
        ("projects/plot-planner", "the plot planner", .project, "A booking tool for shared tools and water slots. Forty societies use it.", "# the plot planner\n\nA booking tool for shared tools and water slots. Shipped in March; forty societies use it. [[c:slack-studio]] [[r:S900]]\n\n## pricing\n\nYearly on by default, two months free. Decided in March and not reopened. [[r:N88]]\n\n## the checkout bug\n\nVerify the signature on the raw body, before parsing. Fixed twice. [[r:C12]]\n"),
        ("projects/seed-swap", "seed swap", .project, "An idea from 2024 that never left the notes.", "# seed swap\n\nAn idea from 2024 that never left the notes: a ledger of who has which seed. [[r:N140]]\n"),
        ("projects/water-rota", "the water rota", .project, "A spreadsheet that wants to be an app.", "# the water rota\n\nA spreadsheet that wants to be an app. [[c:whatsapp-committee]]\n"),
        ("years/2025", "2025", .year, "The year the planner found its users.", "# 2025\n\nThe year the planner found its users: from six societies in January to thirty-one by December. [[c:slack-studio]]\n\n## spring\n\nYou chaired the committee and wrote less code than in any quarter since 2022. [[r:S1700]]\n\n## autumn\n\nThe second offer to grow the studio, turned down in a week. [[r:E640]]\n"),
        ("years/2026", "2026", .year, "The planner shipped; the lease came up.", "# 2026\n\nThe plot planner shipped in March. The lease came up in November. [[r:S900]] [[r:W1044]]\n"),
        ("themes/how-you-work", "how you work", .theme, "Mornings for writing, batches for messages, Fridays for the plot.", "# how you work\n\nMornings for writing, batches for messages, Fridays for the plot. [[r:S2210]]\n\n## deciding\n\nYou decide slowly and then do not go back. *Money* decisions wait for the weekend; **people** decisions wait for a walk. [[r:N20]]\n"),
        ("themes/money", "money and deals", .theme, "Two offers turned down; one loan repaid early.", "# money and deals\n\nTwo offers to grow the studio, both turned down. One loan from 2021, repaid a year early. [[r:E412]] [[r:E640]] [[r:N301]]\n"),
        ("themes/voice", "your voice, by audience", .theme, "Full sentences, signed with initials: Portuguese to family, English to clients.", "# your voice, by audience\n\nFull sentences, with capitals and a greeting, and you sign off with your initials. [[r:W10]]\n\n## to family\n\nIn Portuguese, longer and warmer. [[r:W12]]\n\n## to clients\n\nIn English: three lines and a date. [[r:E412]]\n\n```\nI will check with the others and come back to you on Friday.\nR.C.\n```\n"),
    ]

    static func wikiEntries() -> [WikiEntry] {
        wikiPages.enumerated().map { i, p in
            WikiEntry(id: p.0, title: p.1, kind: p.2, updated: i % 3 == 0 ? wikiDay : "2026-11-0\(1 + i % 9)", words: p.4.split { $0 == " " || $0 == "\n" }.count * (p.2 == .front ? 9 : 14),
                      conversations: [40, 10, 5, 8, 1, 3, 2, 20, 2, 6, 150, 90, 60, 15, 30][i % 15], rows: 500 + i * 40, summary: p.3, rank: i)
        }
    }

    /// Four hundred pages for the list, and a page of two thousand words: what a real wiki weighs.
    static func bigWiki() -> [WikiEntry] {
        var out = wikiEntries()
        let first = ["Ada", "Bela", "Chidi", "Dara", "Emre", "Farah", "Goran", "Hana", "Ivo", "Jun"], last = ["Abara", "Brandt", "Castell", "Dvorak", "Eze", "Falk", "Greco", "Haas", "Ito", "Jansen", "Kovac", "Lund"]
        for i in 0..<300 { out.append(WikiEntry(id: "people/p\(i)", title: "\(first[i % 10]) \(last[(i / 10 + i) % 12]) \(i / 120 == 0 ? "" : "the \(i / 120 + 1)")".trimmingCharacters(in: .whitespaces), kind: .person, updated: wikiDay, words: 600 + i, conversations: 1 + i % 30, rank: 100 + i)) }
        for i in 0..<60 { out.append(WikiEntry(id: "projects/x\(i)", title: "project number \(i + 1)", kind: .project, updated: wikiDay, words: 900, rank: 500 + i)) }
        for y in 2011...2026 { out.append(WikiEntry(id: "years/\(y)", title: "\(y)", kind: .year, updated: wikiDay, words: 3_000, rank: 700 + y)) }
        for i in 0..<10 { out.append(WikiEntry(id: "themes/t\(i)", title: "a theme with a fairly long name, number \(i + 1)", kind: .theme, updated: wikiDay, words: 8_000, rank: 900 + i)) }
        return out
    }

    static let longPage: String = "# a long page\n\n" + (1...34).map { i in
        (i % 6 == 1 ? "## part \((i + 5) / 6): what happened next\n\n" : "")
            + "Paragraph \(i). Sam Okafor wrote again that week to say the paperwork was ready, and that the rent stays where it is for the term; Ines Marchetti read it the same evening and asked only that the boiler is looked at before winter. "
            + "You said you would answer both of them by the weekend, and then the committee met, the rota slipped, and the pricing page for Maya Lindqvist took the days you had kept for it. [[c:whatsapp-sam-landlord]] [[r:W\(1000 + i)]] [[r:I\(70 + i)]]"
    }.joined(separator: "\n\n")

    static func wikiScreens(_ m: AppModel, main: @escaping (Tab) -> Void) -> [(String, () -> Void)] {
        func wiki(_ id: String, big: Bool = false, _ more: () -> Void = {}) {
            main(.profile)
            m.wiki.take(big ? bigWiki() : wikiEntries())
            if let e = m.wiki.entries.first(where: { $0.id == id }), let text = wikiPages.first(where: { $0.0 == id })?.4 { m.wiki.set(e, text: text) }
            more()
        }
        var out: [(String, () -> Void)] = []
        out.append(("wiki-front", { wiki("front") }))
        out.append(("wiki-person", { wiki("people/sam-okafor") }))
        out.append(("wiki-long-name", { wiki("people/the-allotment-committee") { m.wiki.sort = .name; m.wiki.folded = ["project"] } }))
        out.append(("wiki-theme", { wiki("themes/voice") { m.wiki.folded = ["person", "project"] } }))
        out.append(("wiki-filter", {
            wiki("people/sam-okafor") {
                m.wiki.filter = "lease"
                m.wiki.hits = [WikiHit(id: "people/sam-okafor", line: "The renewal is open between you. He first raised it on the fourth of November and again six days later, when he also asked whether the deposit carries over."),
                               WikiHit(id: "years/2026", line: "The plot planner shipped in March. The lease came up in November."),
                               WikiHit(id: "front", line: "The lease renewal with Sam Okafor: he has asked twice.")]
            }
        }))
        out.append(("wiki-filter-none", { wiki("front") { m.wiki.filter = "zeppelin"; m.wiki.hits = [] } }))
        out.append(("wiki-big", {                       // four hundred pages in the list, two thousand words on the page
            wiki("front", big: true)
            let e = WikiEntry(id: "themes/t0", title: "a theme with a fairly long name, number 1", kind: .theme, updated: wikiDay, words: 2_100, conversations: 150, rank: 900)
            m.wiki.set(e, text: longPage)
        }))
        out.append(("wiki-building", {                  // the wiki being written: the foot of the list says how far, and its own page says all of it
            wiki("front")
            m.wiki.building = true
            m.wikiBuild.status = WikiBuild.status(["built": true, "pages": ["front": 1, "people": 30], "words": 50_000, "spent": ["calls": 100, "secs": 4_800]])
            m.wikiBuild.running = true
            m.wikiBuild.progress = WikiBuild.Progress(n: 30, of: 250, kind: "people")
        }))
        out.append(("wiki-build-estimate", {            // what the rest would take, before it starts
            wiki("people/sam-okafor")
            m.wiki.building = true
            m.wikiBuild.status = WikiBuild.status(["built": true, "pages": ["front": 1, "people": 10, "projects": 5, "years": 2, "themes": 4], "words": 35_000, "spent": ["calls": 160, "secs": 2_100]])
            m.wikiBuild.estimate = WikiBuild.estimate(["estimate": ["pages_to_write": ["people, the closest": 50, "people, the rest": 200, "projects": 12, "quarters": 20, "years": 8, "themes": 5],
                                                                    "calls_total": 700, "hours_at_5_workers": 3.0, "plan": "your claude plan"]])
        }))
        out.append(("wiki-build-paused", {              // stopped by them: the list still reads, the foot says paused
            wiki("people/sam-okafor")
            m.wikiBuild.status = WikiBuild.status(["built": true, "pages": ["front": 1, "people": 30], "words": 50_000, "spent": ["calls": 100, "secs": 4_800]])
            m.wikiBuild.paused = true
        }))
        out.append(("wiki-offer", {                     // before any page of the wiki exists: offered on the short pages, with its cost
            main(.profile)
            m.profile.pages = ProfilePage.order.compactMap { id in profilePages[id].map { ProfilePage(id: id, text: $0, rebuilt: nil) } }
            m.wikiBuild.status = WikiBuild.status(["built": false, "pages": [String: Any](), "words": 0, "spent": ["secs": 0]])
            m.wikiBuild.estimate = WikiBuild.estimate(["estimate": ["pages_to_write": ["front": 1, "people, the closest": 50, "people, the rest": 220, "projects": 12, "years": 8, "themes": 5],
                                                                    "calls_total": 720, "hours_at_5_workers": 3.5, "plan": "your claude plan"]])
        }))
        out.append(("wiki-briefing", {                  // the five short pages, reached from the wiki
            wiki("front")
            m.profile.pages = ProfilePage.order.compactMap { id in profilePages[id].map { ProfilePage(id: id, text: $0, rebuilt: nil) } }
            m.wiki.briefing = true
        }))
        out.append(("wiki-ref-row", {                   // a row chip pressed: the message in its conversation, in the panel
            wiki("people/sam-okafor") {
                let hit = Hit(id: "wiki:0:W1044", src: "whatsapp", kind: "message", ts: "2026-11-10T10:00:00Z", thread: "sam (landlord)", threadID: "t", who: "them", sender: "sam", text: "", url: "", offset: 0)
                var peek = ThreadPeek(hit: hit, turn: -9, number: 1)
                let rows: [[String: Any]] = [
                    ["id": "W1043", "sender": "sam", "me": false, "ts": "2026-11-04T10:00:00Z", "text": "the lease renewal is due on the first."],
                    ["id": "W1044", "sender": "sam", "me": false, "ts": "2026-11-10T10:00:00Z", "text": "did you see my message about the renewal? i also need to know about the deposit.", "here": true],
                    ["id": "W1045", "sender": "me", "me": true, "ts": "2026-11-10T10:20:00Z", "text": "I will check with the others and come back to you."]]
                peek.take(["src": "whatsapp", "title": "sam (landlord)", "rows": rows])
                m.ask.thread = peek
            }
        }))
        out.append(("wiki-ref-card", {                  // a conversation chip pressed: its card
            wiki("people/sam-okafor") {
                m.wiki.card = WikiCard(key: "whatsapp-sam-landlord", ["_title": "sam (landlord)", "_src": "whatsapp", "_from": "2019-03-02", "_to": "2026-11-11", "_n": 450, "_mine": 200,
                    "about": "Rent, repairs and the renewal of the lease on the flat on Marsh Lane, between you and your landlord, since the month you moved in.",
                    "facts": ["The rent has been held twice at renewal.", "The boiler was replaced in 2022 at his cost.", longName + " is the group he asks about when the bins are missed."],
                    "open": [["what": "whether you are staying another year", "when": "2026-11"], ["what": "whether the deposit carries over"]]])
            }
        }))
        out.append(("wiki-wrong", {                     // a paragraph the owner said is wrong
            wiki("people/sam-okafor") { m.profile.wrong = ["people/sam-okafor": ["Your landlord since 2019. Plain and fair with you; he asks twice before he chases, and he has never raised the rent without a month's warning."]] }
        }))
        out.append(("wiki-person-panel", { wiki("people/sam-okafor") { m.people.list = peopleList; m.people.open = personPage } }))
        return out
    }

    /// The reader against the engine's own made-up wiki (tests/fixtures/wiki, when the sources are beside the build):
    /// the index as it is really written, every page taken apart, every mark of evidence and every link understood.
    static func wikiShapeFaults() -> [String] {
        let dir = LayoutTest.sourcesDir.deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("tests/fixtures/wiki")
        guard let data = try? Data(contentsOf: dir.appendingPathComponent("index.json")), let obj = try? JSONSerialization.jsonObject(with: data) else { return [] }
        var more: [String] = []
        let list = WikiModel.entries(obj)
        let raw = ((obj as? [String: Any])?["pages"] as? [[String: Any]]) ?? []
        if list.count != raw.count || list.isEmpty { more.append("wiki shape: the index lists \(raw.count) pages and the reader takes \(list.count)") }
        for (e, d) in zip(list, raw) {
            let kind = d["kind"] as? String ?? ""
            let want: WikiEntry.Kind? = ["front": .front, "people": .person, "projects": .project, "years": .year, "quarters": .year, "themes": .theme][kind]
            if want != e.kind { more.append("wiki shape: a page of kind \(kind) is filed under \(e.kind.group)") }
            if e.words == 0 || e.updated.isEmpty || e.summary.isEmpty || e.conversations == 0 { more.append("wiki shape: the index entry \(e.id) lost its words, date, summary or sources") }
        }
        let model = WikiModel(home: dir)
        model.take(list)
        FileHandle.standardError.write("wiki shape: reading \(list.count) pages of the engine's fixture, \(list.filter(\.isName).count) of them people by name\n".data(using: .utf8)!)
        // a person's title is lower case in the engine's index: it must still be a name the prose can be linked by
        let people = list.filter { $0.kind == .person }
        if !people.isEmpty, model.names.list.count != people.filter(\.isName).count || model.names.list.isEmpty { more.append("wiki shape: people with pages are not found as names (\(model.names.list.count) of \(people.count))") }
        let years = model.list(.year).map(\.title)
        if years != years.sorted(by: { $0.localizedStandardCompare($1) == .orderedDescending }) { more.append("wiki shape: years are not listed newest first: \(years)") }
        for e in list {
            guard let text = try? String(contentsOf: dir.appendingPathComponent(e.path), encoding: .utf8) else { more.append("wiki shape: \(e.id) has no file at \(e.path)"); continue }
            let blocks = WikiText.parse(text, names: model.names, pages: model.personPages)
            if blocks.isEmpty { more.append("wiki shape: \(e.id) parses to nothing"); continue }
            if blocks.first?.md.kind != .heading { more.append("wiki shape: \(e.id) does not open on its title") }
            for b in blocks where b.plain.contains("[[") || b.plain.contains("]]") { more.append("wiki shape: \(e.id) shows a raw mark in \u{201C}\(b.plain.prefix(40))\u{201D}"); break }
            let marks = text.components(separatedBy: "[[r:").count + text.components(separatedBy: "[[c:").count - 2
            let refs = blocks.reduce(0) { $0 + $1.refs.count }
            if marks > 0, refs == 0 { more.append("wiki shape: \(e.id) cites \(marks) rows and conversations and the reader finds none") }
            let links = text.components(separatedBy: "[[p:").count - 1
            let linked = blocks.reduce(0) { n, b in n + b.text.runs.filter { $0.link?.scheme == "ctxwiki" && $0.link?.host == "page" }.count }
            if links > 0, linked < links { more.append("wiki shape: \(e.id) links to \(links) pages and the reader makes \(linked) links") }
            for run in blocks.flatMap({ Array($0.text.runs) }) where run.link?.scheme == "ctxwiki" && run.link?.host == "page" {
                let id = String(run.link!.path.dropFirst())
                if !list.contains(where: { $0.id == id }) { more.append("wiki shape: \(e.id) links to \(id), which is not a page") }
            }
        }
        return Array(Set(more)).sorted()
    }

    static func wikiCheck(_ screen: String, _ at: String, _ size: CGSize, _ found: [ProbeInfo]) -> [String] {
        guard screen.hasPrefix("wiki-") else { return [] }
        var more: [String] = []
        let m = AppModel.shared
        func count(_ n: String) -> Int { Set(found.filter { $0.name == n }.map { "\(Int($0.frame.minX)),\(Int($0.frame.minY))" }).count }
        // the wiki's writing: its own page says what exists and carries the one button; the list's foot says it in a line
        if ["wiki-building", "wiki-build-estimate"].contains(screen) {
            if count("wiki.build") != 1 || count("wiki.build.title") != 1 { more.append("\(at): the wiki's writing is not shown in the page's place") }
            if !found.contains(where: { $0.name == "setting.control" }) { more.append("\(at): the wiki's writing has no button") }
            return more
        }
        if screen == "wiki-offer" {
            if count("profile.wiki") != 1 || count("wiki.build") != 1 { more.append("\(at): the wiki is not offered before it is written") }
            return more
        }
        if size.width >= 900, m.people.open == nil, screen != "wiki-briefing", count("wiki.build.foot") != 1 { more.append("\(at): the list of pages does not say where the writing stands") }
        if screen != "wiki-briefing" {
            if count("wiki.title") != 1 || count("wiki.meta") != 1 { more.append("\(at): the page has no title and no line saying where it came from") }
            if count("wiki.ask") != 1 || count("wiki.copy") != 1 { more.append("\(at): the page does not offer ask about this page and copy as markdown") }
        }
        if let index = found.first(where: { $0.name == "wiki.index" }) {
            for p in found where (p.name == "wiki.text" || p.name == "wiki.title" || p.name == "wiki.para") && p.frame.minX < index.frame.maxX + 20 { more.append("\(at): the page's text starts under the list of pages"); break }
            for p in found where p.name == "wiki.row" && p.frame.maxX > index.frame.maxX + 0.5 { more.append("\(at): a row of the list runs out of it"); break }
        } else if size.width >= 900, m.people.open == nil, screen != "wiki-briefing" { more.append("\(at): the list of pages is not shown") }
        // a comfortable measure: no line of the page wider than it
        for p in found where p.name == "wiki.text" && p.frame.width > WikiReader.measure + 1 { more.append("\(at): a paragraph is \(Int(p.frame.width)) wide, wider than the reading measure"); break }
        let right = found.first(where: { $0.name == "refs.panel" })?.frame.minX ?? size.width
        for p in found where p.name == "wiki.text" && p.frame.maxX > right - 16 { more.append("\(at): a paragraph reaches \(Int(p.frame.maxX)) of \(Int(right)): it touches the edge"); break }
        if screen == "wiki-front" {
            if size.height >= 900, count("wiki.head") != 4 { more.append("\(at): the list is not people, projects, years and themes: \(count("wiki.head")) groups") }
            if size.height >= 900, count("wiki.row") != 15 { more.append("\(at): fifteen pages are \(count("wiki.row")) rows") }
            if count("wiki.ref") < 6 { more.append("\(at): the paragraphs do not end in their evidence") }
            if m.wiki.list(.year).map(\.title) != ["2026", "2025"] { more.append("\(at): the years are not newest first") }
        }
        if screen == "wiki-theme", size.width >= 900, count("wiki.row") != 6 { more.append("\(at): folding people and projects does not leave six rows: \(count("wiki.row"))") }
        if screen == "wiki-long-name", m.wiki.list(.person).first?.title != "Ines Marchetti" { more.append("\(at): people by name do not start with ines") }
        if screen == "wiki-filter", size.width >= 900, count("wiki.row") != 3 || count("wiki.head") != 0 { more.append("\(at): the filter does not show its three pages alone") }
        if screen == "wiki-filter-none", size.width >= 900, count("wiki.none") != 1 { more.append("\(at): a filter that finds nothing does not say so") }
        if screen == "wiki-big" {
            if size.width >= 1300, count("wiki.outline") < 5 { more.append("\(at): a wide window does not show the page's headings beside it") }
            if size.width < 1000, count("wiki.outline") > 0 { more.append("\(at): the headings are shown where there is no room for them") }
            // two thousand words are taken apart in well under a frame's patience
            let t = Date()
            let blocks = WikiText.parse(longPage, names: m.wiki.names, pages: m.wiki.personPages)
            let ms = Date().timeIntervalSince(t) * 1000
            if ms > 400 { more.append("\(at): a two thousand word page takes \(Int(ms)) ms to take apart") }
            if blocks.filter({ $0.md.kind == .paragraph }).count != 34 || blocks.contains(where: { $0.md.kind == .paragraph && $0.refs.count != 3 }) { more.append("\(at): the long page is not 34 paragraphs with three sources each") }
            if longPage.split(whereSeparator: { $0 == " " || $0 == "\n" }).count < 2000 { more.append("\(at): the long page is under two thousand words") }
        }
        if screen == "wiki-ref-row", !found.contains(where: { $0.name == "peek.card" }) || !found.contains(where: { $0.name == "refs.panel" }) { more.append("\(at): a row chip does not open the message in its conversation beside the page") }
        if screen == "wiki-ref-card", count("refs.card.title") != 1 || count("refs.card.line") != 5 { more.append("\(at): a conversation chip does not open its card: \(count("refs.card.line")) lines") }
        if screen == "wiki-wrong" || screen == "wiki-person", count("wiki.wrong") < 1 { more.append("\(at): a paragraph cannot be said to be wrong") }
        if screen == "wiki-person" {
            m.openRef(WikiRef(row: true, key: "W1044"))
            if m.ask.thread?.hit.id != "wiki:0:W1044" || AskModel.rowID(m.ask.thread!.hit) != "W1044" { more.append("\(at): pressing a row chip does not ask for that row's thread") }
            m.ask.closeThread()
            m.openRef(WikiRef(row: false, key: "slack-studio"))
            if m.wiki.card?.key != "slack-studio" { more.append("\(at): pressing a conversation chip does not open its card") }
            m.wiki.card = nil
        }
        if screen == "wiki-briefing", !found.contains(where: { $0.name == "profile.tab" }) || !found.contains(where: { $0.name == "wiki.back" }) { more.append("\(at): the briefing does not show the five pages and the way back") }
        if screen == "wiki-person" {
            // a name in the prose is one link to that person's page
            let b = m.wiki.page?.blocks.first { $0.plain.contains("Ines Marchetti") }
            let linked = b.map { blk in blk.text.runs.contains { $0.link?.absoluteString.contains("ines-marchetti") == true && String(blk.text[$0.range].characters) == "Ines Marchetti" } } ?? false
            if !linked { more.append("\(at): a person named in a page is not one link to their page") }
        }
        return more
    }
}
