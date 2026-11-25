import AppKit
import SwiftUI

// MARK: an answer written in markdown, taken apart for the page

/// A run of an answer's text in one style.
struct Styled: Equatable {
    var text: String
    var bold = false
    var italic = false
    var code = false
    var strike = false
    var link: String?
}

/// A piece of a line: styled words, or a pointer to one of the rows the answer rests on (1-based).
enum Bit: Equatable {
    case span(Styled)
    case cite(Int)
}

/// One block of an answer: a heading, a paragraph, a list line, a quote, code, a table, a rule.
struct MDBlock: Identifiable, Equatable {
    enum Kind: Equatable { case heading, paragraph, item, quote, code, table, rule }
    let id: Int
    var kind: Kind
    var bits: [Bit] = []
    var level = 0               // heading 1 to 4; list depth from 0
    var marker = ""             // "–" or "3."
    var lead = false            // a short first sentence that stands alone
    var code = ""
    var lang = ""
    var header: [[Bit]] = []
    var rows: [[[Bit]]] = []

    var hasCites: Bool { bits.contains { if case .cite = $0 { return true } else { return false } } }
    var plain: String { MD.plain(bits) }
}

/// One word as it is set in a line: its style, the citations that follow it, and whether it sits tight against the word before.
struct MDWord: Equatable {
    var text: String
    var span: Styled
    var cites: [Int] = []
    var glue = false
}

enum MD {
    static func plain(_ bits: [Bit]) -> String {
        bits.compactMap { if case .span(let s) = $0 { return s.text } else { return nil } }.joined()
    }

    private static let structure = try! NSRegularExpression(
        pattern: #"(^|\n)\s{0,3}(#{1,4}\s|```|>\s|\|.+\||\d+[.)]\s|[-*_]{3,}\s*(\n|$))|\n\s*\n|\*\*[^*\n]+\*\*|`[^`\n]+`|\]\(https?://"#)

    /// Whether the text was written as markdown. A plain run of sentences is set the older way: short paragraphs, the first sentence alone.
    static func isMarkdown(_ s: String) -> Bool {
        structure.firstMatch(in: s, range: NSRange(s.startIndex..., in: s)) != nil
    }

    // MARK: inline

    /// Bold, italic, code, strike, links and `[n]` markers. Anything left open is kept as it was typed: half a line
    /// arrives before its end while an answer is being written.
    static func inline(_ s: String, cites: Int, style: Styled = Styled(text: "")) -> [Bit] {
        let c = Array(s)
        var out: [Bit] = []
        var buf = ""
        func flush() {
            guard !buf.isEmpty else { return }
            var sp = style
            sp.text = buf
            out.append(.span(sp))
            buf = ""
        }
        func find(_ mark: [Character], from: Int) -> Int? {
            guard from < c.count else { return nil }
            var i = from
            while i + mark.count <= c.count {
                if c[i] == "\n" && mark.count == 1 { return nil }
                if Array(c[i..<(i + mark.count)]) == mark, i > from { return i }
                i += 1
            }
            return nil
        }
        var i = 0
        while i < c.count {
            let ch = c[i]
            if ch == "\\", i + 1 < c.count, "*_`[]~#>|".contains(c[i + 1]) { buf.append(c[i + 1]); i += 2; continue }
            if ch == "`", !style.code, let end = find(["`"], from: i + 1) {
                flush()
                var sp = style
                sp.text = String(c[(i + 1)..<end])
                sp.code = true
                out.append(.span(sp))
                i = end + 1
                continue
            }
            if (ch == "*" || ch == "_"), i + 1 < c.count, c[i + 1] == ch, i + 2 < c.count, !c[i + 2].isWhitespace, let end = find([ch, ch], from: i + 2) {
                flush()
                var sp = style
                sp.bold = true
                out += inline(String(c[(i + 2)..<end]), cites: cites, style: sp)
                i = end + 2
                continue
            }
            if ch == "~", i + 1 < c.count, c[i + 1] == "~", let end = find(["~", "~"], from: i + 2) {
                flush()
                var sp = style
                sp.strike = true
                out += inline(String(c[(i + 2)..<end]), cites: cites, style: sp)
                i = end + 2
                continue
            }
            if ch == "*" || ch == "_", i + 1 < c.count, !c[i + 1].isWhitespace, c[i + 1] != ch,
               ch == "*" || i == 0 || !(c[i - 1].isLetter || c[i - 1].isNumber),
               let end = find([ch], from: i + 1), !c[end - 1].isWhitespace,
               ch == "*" || end + 1 >= c.count || !(c[end + 1].isLetter || c[end + 1].isNumber) {
                flush()
                var sp = style
                sp.italic = true
                out += inline(String(c[(i + 1)..<end]), cites: cites, style: sp)
                i = end + 1
                continue
            }
            if ch == "[" {
                // [n]: a row the answer rests on. one past the list is dropped, as it always was
                if let close = c[i...].firstIndex(of: "]"), close > i + 1, close - i <= 3, c[(i + 1)..<close].allSatisfy(\.isNumber), let n = Int(String(c[(i + 1)..<close])) {
                    while buf.last?.isWhitespace == true, buf.last != "\n" { buf.removeLast() }
                    flush()
                    if n >= 1, n <= cites { out.append(.cite(n)) }
                    i = close + 1
                    if i < c.count, !c[i].isWhitespace, !c[i].isPunctuation, c[i] != "[" { buf.append(" ") }
                    continue
                }
                // [words](address)
                if let close = c[i...].firstIndex(of: "]"), close + 1 < c.count, c[close + 1] == "(", let end = c[close...].firstIndex(of: ")"),
                   !c[(i + 1)..<close].contains("\n") {
                    let url = String(c[(close + 2)..<end]).trimmingCharacters(in: .whitespaces)
                    let words = String(c[(i + 1)..<close])
                    if buf.last == "!" {
                        // ![words](address) is a picture in markdown. nothing is ever fetched to draw an answer: the words
                        // stay as plain text and the address is dropped, so a picture can carry nothing out
                        buf.removeLast()
                        buf.append(contentsOf: words)
                        i = end + 1
                        continue
                    }
                    if let u = Answer.web(url) {
                        // only http and https ever become a link (Answer.web): no file:, no data:, no app schemes. the words
                        // of a link can say anything, so the real host is written after them, read before the click
                        flush()
                        var sp = style
                        let host = (u.host ?? "").lowercased()
                        sp.text = words.lowercased().contains(host) || host.isEmpty ? words : words + " (" + host + ")"
                        sp.link = url
                        out.append(.span(sp))
                        i = end + 1
                        continue
                    }
                }
            }
            buf.append(ch)
            i += 1
        }
        flush()
        return out
    }

    /// The bits as words to set one by one. Punctuation straight after a marker joins the word before it: "him [1]." reads "him.¹"
    static func words(_ bits: [Bit]) -> [MDWord] {
        var out: [MDWord] = []
        var open = false            // the text so far ended without a space: the next word sits tight against it
        for b in bits {
            switch b {
            case .cite(let n):
                if out.isEmpty { out.append(MDWord(text: "", span: Styled(text: ""), cites: [n])) } else { out[out.count - 1].cites.append(n) }
            case .span(var sp):
                if let last = out.last, !last.cites.isEmpty, !sp.code {
                    let lead = sp.text.prefix { ".,;:!?)]\u{2019}\u{201D}\"'".contains($0) }
                    if !lead.isEmpty { out[out.count - 1].text += lead; sp.text = String(sp.text.dropFirst(lead.count)) }
                }
                guard !sp.text.isEmpty else { continue }
                let startsTight = !(sp.text.first?.isWhitespace ?? true)
                let parts: [String] = sp.code && sp.text.count <= 48 ? [sp.text] : sp.text.split(whereSeparator: \.isWhitespace).map(String.init)
                for (k, w) in parts.enumerated() {
                    var one = sp
                    one.text = w
                    out.append(MDWord(text: w, span: one, glue: k == 0 && open && startsTight && !out.isEmpty))
                }
                open = !(sp.text.last?.isWhitespace ?? true)
            }
        }
        return out
    }

    // MARK: blocks

    private static let listMark = try! NSRegularExpression(pattern: #"^(\s*)([-*•–+]|\d{1,3}[.)])\s+(.*)$"#)
    private static let tableRule = try! NSRegularExpression(pattern: #"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$"#)

    static func cells(_ line: String) -> [String] {
        var t = line.trimmingCharacters(in: .whitespaces)
        if t.hasPrefix("|") { t.removeFirst() }
        if t.hasSuffix("|") { t.removeLast() }
        return t.components(separatedBy: "|").map { $0.trimmingCharacters(in: .whitespaces) }
    }

    static func parse(_ text: String, cites: Int) -> [MDBlock] {
        var out: [MDBlock] = []
        var para: [String] = []
        func add(_ b: MDBlock) { var b = b; b = MDBlock(id: out.count, kind: b.kind, bits: b.bits, level: b.level, marker: b.marker, lead: b.lead, code: b.code, lang: b.lang, header: b.header, rows: b.rows); out.append(b) }
        func flush() {
            guard !para.isEmpty else { return }
            let bits = inline(para.joined(separator: " "), cites: cites)
            if !bits.isEmpty { add(MDBlock(id: 0, kind: .paragraph, bits: bits)) }
            para = []
        }
        let lines = text.components(separatedBy: "\n")
        var i = 0
        while i < lines.count {
            let raw = lines[i]
            let line = raw.trimmingCharacters(in: .whitespaces)
            if line.hasPrefix("```") {
                flush()
                let lang = String(line.dropFirst(3)).trimmingCharacters(in: .whitespaces)
                var body: [String] = []
                i += 1
                while i < lines.count, !lines[i].trimmingCharacters(in: .whitespaces).hasPrefix("```") { body.append(lines[i]); i += 1 }
                i += 1
                add(MDBlock(id: 0, kind: .code, code: body.joined(separator: "\n"), lang: lang.lowercased()))
                continue
            }
            if line.isEmpty { flush(); i += 1; continue }
            if line.hasPrefix("#"), let sp = line.firstIndex(of: " "), line[..<sp].allSatisfy({ $0 == "#" }), line[..<sp].count <= 4 {
                flush()
                add(MDBlock(id: 0, kind: .heading, bits: inline(String(line[line.index(after: sp)...]).trimmingCharacters(in: CharacterSet(charactersIn: " #")), cites: cites), level: line[..<sp].count))
                i += 1
                continue
            }
            if line.count >= 3, Set(line.replacingOccurrences(of: " ", with: "")).count == 1, let f = line.first, "-*_".contains(f) {
                flush()
                add(MDBlock(id: 0, kind: .rule))
                i += 1
                continue
            }
            if line.contains("|"), i + 1 < lines.count, tableRule.firstMatch(in: lines[i + 1], range: NSRange(lines[i + 1].startIndex..., in: lines[i + 1])) != nil, lines[i + 1].contains("-") {
                flush()
                let head = cells(line).map { inline($0, cites: cites) }
                var rows: [[[Bit]]] = []
                i += 2
                while i < lines.count, lines[i].contains("|"), !lines[i].trimmingCharacters(in: .whitespaces).isEmpty {
                    var r = cells(lines[i]).map { inline($0, cites: cites) }
                    while r.count < head.count { r.append([]) }
                    rows.append(Array(r.prefix(head.count)))
                    i += 1
                }
                add(MDBlock(id: 0, kind: .table, header: head, rows: rows))
                continue
            }
            if line.hasPrefix(">") {
                flush()
                var body: [String] = []
                while i < lines.count, lines[i].trimmingCharacters(in: .whitespaces).hasPrefix(">") {
                    body.append(String(lines[i].trimmingCharacters(in: .whitespaces).dropFirst()).trimmingCharacters(in: .whitespaces))
                    i += 1
                }
                add(MDBlock(id: 0, kind: .quote, bits: inline(body.joined(separator: " "), cites: cites)))
                continue
            }
            if let m = listMark.firstMatch(in: raw, range: NSRange(raw.startIndex..., in: raw)),
               let lead = Range(m.range(at: 1), in: raw), let mark = Range(m.range(at: 2), in: raw), let rest = Range(m.range(at: 3), in: raw) {
                flush()
                var body = String(raw[rest])
                // a line that goes on under its item belongs to it
                while i + 1 < lines.count, lines[i + 1].hasPrefix("  "), !lines[i + 1].trimmingCharacters(in: .whitespaces).isEmpty,
                      listMark.firstMatch(in: lines[i + 1], range: NSRange(lines[i + 1].startIndex..., in: lines[i + 1])) == nil {
                    body += " " + lines[i + 1].trimmingCharacters(in: .whitespaces)
                    i += 1
                }
                let m = String(raw[mark])
                add(MDBlock(id: 0, kind: .item, bits: inline(body, cites: cites), level: min(3, raw[lead].reduce(0) { $0 + ($1 == "\t" ? 2 : 1) } / 2),
                            marker: m.first?.isNumber == true ? m.replacingOccurrences(of: ")", with: ".") : "–"))
                i += 1
                continue
            }
            para.append(line)
            i += 1
        }
        flush()
        return out
    }
}

extension Answer {
    /// The answer as blocks for the page. Markdown is set as written. A plain run of sentences is set in short
    /// paragraphs, the first sentence alone, as it always was.
    var md: [MDBlock] {
        if MD.isMarkdown(text) { return MD.parse(text, cites: cites.count) }
        return blocks.map { b in
            let line = b.pieces.map { p -> String in
                switch p {
                case .text(let t): return t
                case .cite(let n): return "[\(n)]"
                }
            }.joined()
            return MDBlock(id: b.id, kind: b.bullet ? .item : .paragraph, bits: MD.inline(line, cites: cites.count), marker: b.bullet ? "–" : "", lead: b.lead)
        }
    }

    /// The answer as plain words: no markers, no markdown signs. For the corner of a list, a title, a first line.
    var gist: String {
        md.first { !$0.bits.isEmpty }.map { $0.plain.trimmingCharacters(in: .whitespaces) } ?? Answer.strip(text)
    }
}

// MARK: the page

/// The answer, set from its blocks. Citations stay small raised numbers in the line; while it is being written the
/// last line ends in a caret.
struct AnswerText: View {
    let turn: Turn
    let answer: Answer
    var writing = false

    var body: some View {
        let blocks = answer.md
        VStack(alignment: .leading, spacing: 0) {
            ForEach(Array(blocks.enumerated()), id: \.element.id) { n, block in
                let caret = writing && n == blocks.count - 1
                MDBlockView(block: block, turn: turn, answer: answer, caret: caret)
                    .padding(.top, n == 0 ? 0 : MDBlockView.gap(before: block, after: blocks[n - 1]))
            }
        }
    }
}

struct MDBlockView: View {
    let block: MDBlock
    let turn: Turn
    let answer: Answer
    var caret = false

    /// The air above a block: more before a heading, less between the lines of one list.
    static func gap(before b: MDBlock, after a: MDBlock) -> CGFloat {
        if b.kind == .heading { return a.kind == .heading ? 8 : 22 }
        if a.kind == .heading { return 8 }
        if b.kind == .item, a.kind == .item { return 7 }
        if b.kind == .table || b.kind == .code || a.kind == .table || a.kind == .code { return 16 }
        return 12
    }

    var body: some View {
        let key = "\(turn.id)/\(block.id)"
        switch block.kind {
        case .heading:
            let size: CGFloat = [22, 22, 19, 17, 16][min(block.level, 4)]
            InlineFlow(bits: block.bits, size: size, weight: .medium, color: Ink.ink, turn: turn, answer: answer, key: key, caret: caret)
                .frame(maxWidth: .infinity, alignment: .leading)
                .probe("chat.answer", .text, group: "chat.turn\(turn.id)", scrolls: true)
                .probe("chat.answer.edge", .edge, group: "chat.left", scrolls: true)
                .accessibilityAddTraits(.isHeader)
        case .paragraph:
            InlineFlow(bits: block.bits, size: block.lead ? 21 : 16, color: block.lead ? Ink.ink : Ink.ink.opacity(0.86), turn: turn, answer: answer, key: key, caret: caret)
                .frame(maxWidth: .infinity, alignment: .leading)
                .probe("chat.answer", .text, group: "chat.turn\(turn.id)", scrolls: true)
                .probe("chat.answer.edge", .edge, group: "chat.left", scrolls: true)
        case .item:
            HStack(alignment: .firstTextBaseline, spacing: 9) {
                Text(block.marker).font(.system(size: 16, weight: .regular, design: .serif)).monospacedDigit().foregroundStyle(Ink.faint)
                    .frame(minWidth: 12, alignment: .trailing)
                InlineFlow(bits: block.bits, size: 16, color: Ink.ink.opacity(0.86), turn: turn, answer: answer, key: key, caret: caret)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .probe("chat.answer", .text, group: "chat.turn\(turn.id)", scrolls: true)
            }
            .padding(.leading, CGFloat(block.level) * 20)
        case .quote:
            InlineFlow(bits: block.bits, size: 16, italic: true, color: Ink.soft, turn: turn, answer: answer, key: key, caret: caret)
                .frame(maxWidth: .infinity, alignment: .leading)
                .probe("chat.answer", .text, group: "chat.turn\(turn.id)", scrolls: true)
                .padding(.leading, 14)
                .overlay(alignment: .leading) { RoundedRectangle(cornerRadius: 1).fill(Ink.line).frame(width: 2) }
        case .code:
            CodeBlock(code: block.code, lang: block.lang)
                .probe("chat.code", .block, group: "chat.turn\(turn.id)", scrolls: true)
        case .table:
            TableBlock(block: block, turn: turn, answer: answer, key: key)
                .probe("chat.table", .block, group: "chat.turn\(turn.id)", scrolls: true)
        case .rule:
            Rectangle().fill(Ink.line).frame(height: 1).padding(.vertical, 4)
        }
    }
}

/// One line of an answer. With nothing in it to press, it is plain text that can be selected. With citations or
/// links, its words are set one by one so each number sits in the line and can be pointed at.
struct InlineFlow: View {
    let bits: [Bit]
    var size: CGFloat = 16
    var weight: Font.Weight = .regular
    var italic = false
    var design: Font.Design = .serif
    var color: Color = Ink.ink
    let turn: Turn
    let answer: Answer
    let key: String
    var caret = false

    var body: some View {
        // a known person's name in the line is a thing to press: it opens that person
        let people = AppModel.shared.people
        let (words, who) = InlineFlow.named(MD.words(bits), people)
        let pressable = caret || !who.isEmpty || bits.contains { b in
            switch b {
            case .cite: return true
            case .span(let s): return s.link != nil || s.text.contains("http://") || s.text.contains("https://")
            }
        }
        if pressable {
            WordFlow(space: Typeset.space(size), lineSpacing: size > 18 ? 5 : 5) {
                let backs = InlineFlow.backs(words.map(\.word))
                ForEach(Array(words.enumerated()), id: \.offset) { n, item in
                    let w = item.word, i = item.at
                    MDWordView(word: w, size: size, weight: weight, italic: italic, design: design, color: color, turn: turn, answer: answer, key: "\(key)/\(i)", person: who[n], backs: backs[n], gap: Typeset.space(size))
                        .layoutValue(key: Glue.self, value: w.glue)
                }
                if caret { Caret(height: size * 1.05) }
            }
        } else {
            Text(attributed).lineSpacing(5)
                .fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
        }
    }

    /// For each word, the numbers of the evidence its sentence rests on: a sentence runs from the word after the last
    /// full stop or citation to the word that carries the numbers. A sentence with no number has none.
    static func backs(_ words: [MDWord]) -> [[Int]] {
        var out = Array(repeating: [Int](), count: words.count), start = 0
        for (i, w) in words.enumerated() {
            if !w.cites.isEmpty {
                for k in start...i { out[k] = w.cites }
                start = i + 1
            } else if let last = w.text.last, ".!?".contains(last) {
                start = i + 1
            }
        }
        return out
    }

    /// The words of a line with each mention of a known person folded into one: "Sam" and "Okafor" become the one
    /// thing "Sam Okafor", so it is one button with one label, and goes to the next line whole. `at` is the place of
    /// the word's last part in the line as written, which is what its citations are keyed by.
    static func named(_ words: [MDWord], _ people: PeopleModel) -> (words: [(word: MDWord, at: Int)], who: [Int: String]) {
        var runs = people.isEmpty ? [] : people.runs(words.map { $0.span.code || $0.span.link != nil ? "" : $0.text })
        // the words of one link are one link, in the same way
        var k = 0
        while k < words.count {
            var n = 1
            if let l = words[k].span.link { while k + n < words.count, words[k + n].span.link == l, words[k + n - 1].cites.isEmpty { n += 1 } }
            if n > 1 { runs.append((k, n, "")) }
            k += n
        }
        runs.sort { $0.at < $1.at }
        guard !runs.isEmpty else { return (words.enumerated().map { ($0.element, $0.offset) }, [:]) }
        var out: [(word: MDWord, at: Int)] = [], who: [Int: String] = [:]
        var i = 0
        for r in runs {
            while i < r.at { out.append((words[i], i)); i += 1 }
            var one = words[r.at]
            for k in (r.at + 1)..<(r.at + r.count) { one.text += " " + words[k].text; one.cites += words[k].cites }
            one.span.text = one.text
            if !r.name.isEmpty { who[out.count] = r.name }
            out.append((one, r.at + r.count - 1))
            i = r.at + r.count
        }
        while i < words.count { out.append((words[i], i)); i += 1 }
        return (out, who)
    }

    private func font(_ s: Styled) -> Font {
        if s.code { return .system(size: size * 0.86, weight: .regular, design: .monospaced) }
        let f = Font.system(size: size, weight: s.bold ? .semibold : weight, design: design)
        return s.italic || italic ? f.italic() : f
    }

    private var attributed: AttributedString {
        var out = AttributedString()
        for b in bits {
            guard case .span(let s) = b else { continue }
            var a = AttributedString(s.text)
            a.font = font(s)
            a.foregroundColor = color
            if s.code { a.backgroundColor = Ink.wash }
            if s.strike { a.strikethroughStyle = .single }
            out += a
        }
        return out
    }
}

struct Glue: LayoutValueKey { static let defaultValue = false }

/// The live edge of an answer being written.
struct Caret: View {
    var height: CGFloat = 17
    @Environment(\.accessibilityReduceMotion) private var reduce
    var body: some View {
        TimelineView(.periodic(from: .now, by: 0.53)) { t in
            let on = Probe.on || reduce || Int(t.date.timeIntervalSinceReferenceDate / 0.53) % 2 == 0
            RoundedRectangle(cornerRadius: 1).fill(Ink.ember).frame(width: 2, height: height).opacity(on ? 1 : 0.15)
                .animation(.easeOut(duration: 0.12), value: on)
        }
        .probe("chat.caret", .block, scrolls: true)
        .accessibilityHidden(true)
    }
}

/// One word of an answer in its style, with the numbers of the rows that back the sentence it ends.
struct MDWordView: View {
    let word: MDWord
    let size: CGFloat
    var weight: Font.Weight = .regular
    var italic = false
    var design: Font.Design = .serif
    let color: Color
    let turn: Turn
    let answer: Answer
    let key: String
    var person: String? = nil
    var backs: [Int] = []       // the evidence the sentence this word is in rests on
    var gap: CGFloat = 4
    @State private var hover = false
    @State private var arrived = false
    @Environment(\.streaming) private var streaming
    @Environment(\.evidence) private var evidence
    @Environment(\.accessibilityReduceMotion) private var reduce

    var body: some View {
        let s = word.span
        // with citations quiet or off the text carries no numbers at all
        let chips = evidence == "on" ? word.cites.reduce(CGFloat(0)) { $0 + Chip.width($1) + 1.5 } : 0
        let ask = AppModel.shared.ask
        let marked = !backs.isEmpty && ask.chosen.map { $0.turn == turn.id && backs.contains($0.n) } == true
        Group {
            if let link = s.link, let url = Answer.web(link) {
                Text(word.text).underline(true, color: hover ? Ink.ink : Ink.faint)
                    .contentShape(Rectangle())
                    .onTapGesture { if !Probe.on { NSWorkspace.shared.open(url) } }
                    .onHover { hover = $0 }
                    .help(link)
                    .accessibilityAddTraits(.isLink)
            } else if !s.code, let link = Answer.link(in: word.text) {
                // an address in the answer is a real link: short enough to read, and it opens in the browser
                HStack(alignment: .firstTextBaseline, spacing: 0) {
                    if word.text.hasPrefix("(") { Text("(") }
                    LinkWord(url: link.url, size: size, design: design)
                    Text(link.tail)
                }
            } else if let person {
                PersonName(name: person, text: word.text).probe("chat.person", .block, scrolls: true)
            } else if s.code {
                Text(word.text)
                    .padding(.horizontal, 4).padding(.vertical, 1)
                    .background(Ink.wash, in: RoundedRectangle(cornerRadius: Radius.chip, style: .continuous))
            } else {
                Text(word.text.isEmpty ? " " : word.text).strikethrough(s.strike, color: Ink.faint)
            }
        }
        .font(font(s)).foregroundStyle(color)
        .fixedSize(horizontal: false, vertical: true)
        .padding(.trailing, chips)
        // the sentence a chosen piece of evidence supports stands on a soft ground, which runs under the spaces too
        .background { if marked { Ink.mark.padding(.horizontal, -gap / 2 - 0.5).padding(.vertical, -1.5) } }
        .animation(Motion.lit(Probe.still || reduce), value: marked)
        .onHover { inside in
            guard let n = backs.first else { return }
            let me = Pick(turn: turn.id, n: n)
            if inside { ask.hoverPick = me } else if ask.hoverPick == me { ask.hoverPick = nil }
        }
        // the newest words of an answer being written fade in; nothing before them moves
        .opacity(streaming && !arrived && !Probe.still && !reduce ? 0 : 1)
        .onAppear {
            if streaming, !Probe.still, !reduce { withAnimation(Motion.words(false)) { arrived = true } } else { arrived = true }
        }
        .overlay(alignment: .topTrailing) {
            HStack(spacing: 1.5) {
                ForEach(Array(word.cites.enumerated()), id: \.offset) { j, n in
                    if evidence == "on", n >= 1, n <= answer.cites.count { Chip(number: n, hit: answer.cites[n - 1], turn: turn.id, key: "\(key)/\(j)") }
                }
            }
            .offset(y: size > 18 ? 0 : -2)
        }
    }

    private func font(_ s: Styled) -> Font {
        if s.code { return .system(size: size * 0.86, weight: .regular, design: .monospaced) }
        let f = Font.system(size: size, weight: s.bold ? .semibold : weight, design: design)
        return s.italic || italic ? f.italic() : f
    }
}

/// Code as it was written: one face, no wrapping, its own scroll, and a way to copy it.
struct CodeBlock: View {
    let code: String
    let lang: String
    @State private var copied = false

    var body: some View {
        let shape = RoundedRectangle(cornerRadius: Radius.card, style: .continuous)
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 8) {
                Text(lang.isEmpty ? "code" : lang).font(.system(size: 11, weight: .medium)).foregroundStyle(Ink.soft).lineLimit(1)
                Spacer(minLength: 8)
                Button(copied ? "copied" : "copy") { Clip.copy(code); copied = true }.buttonStyle(QuietButton(size: 11))
                    .probe("chat.code.copy", .button, scrolls: true)
            }
            .padding(.horizontal, 12).frame(height: 30)
            Rectangle().fill(Ink.line).frame(height: 1)
            ScrollView(.horizontal, showsIndicators: false) {
                Text(code).font(.system(size: 12, design: .monospaced)).lineSpacing(3.5).foregroundStyle(Ink.ink)
                    .fixedSize().textSelection(.enabled)
                    .padding(.horizontal, 12).padding(.vertical, 11)
            }
        }
        .background(Ink.wash.opacity(0.7), in: shape)
        .overlay(shape.strokeBorder(Ink.line, lineWidth: 1))
    }
}

/// A table: hairlines, a quiet head, cells that wrap and keep their citations. One too wide for the column scrolls sideways.
struct TableBlock: View {
    let block: MDBlock
    let turn: Turn
    let answer: Answer
    let key: String

    var body: some View {
        let cols = max(1, block.header.count)
        ViewThatFits(in: .horizontal) {
            grid.frame(minWidth: CGFloat(cols) * 96)
            ScrollView(.horizontal, showsIndicators: false) { grid.frame(width: CGFloat(cols) * 150) }
        }
    }

    private var grid: some View {
        let shape = RoundedRectangle(cornerRadius: Radius.card, style: .continuous)
        let cols = max(1, block.header.count)
        return SwiftUI.Grid(alignment: .topLeading, horizontalSpacing: 0, verticalSpacing: 0) {
            GridRow {
                ForEach(Array(block.header.enumerated()), id: \.offset) { c, bits in
                    InlineFlow(bits: bits, size: 12, weight: .semibold, design: .default, color: Ink.soft, turn: turn, answer: answer, key: "\(key)/h\(c)")
                        .padding(.horizontal, 11).padding(.vertical, 8)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            .background(Ink.wash.opacity(0.6))
            ForEach(Array(block.rows.enumerated()), id: \.offset) { r, row in
                Rectangle().fill(Ink.line).frame(height: 1).gridCellColumns(cols)
                GridRow {
                    ForEach(Array(row.enumerated()), id: \.offset) { c, bits in
                        InlineFlow(bits: bits, size: 14, design: .default, color: Ink.ink.opacity(0.9), turn: turn, answer: answer, key: "\(key)/r\(r)c\(c)")
                            .padding(.horizontal, 11).padding(.vertical, 8)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .probe("chat.cell", .text, scrolls: true)
                    }
                }
            }
        }
        .clipShape(shape)
        .overlay(shape.strokeBorder(Ink.line, lineWidth: 1))
    }
}
