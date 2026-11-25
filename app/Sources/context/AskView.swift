import SwiftUI

func marked(_ s: String, words: [String], tint: Color, base: Color = Ink.soft) -> AttributedString {
    var a = AttributedString(s)
    a.foregroundColor = base
    for w in words where !w.isEmpty {
        var from = s.startIndex
        while from < s.endIndex, let r = s.range(of: w, options: .caseInsensitive, range: from..<s.endIndex) {
            // whole words only, as the search itself matches
            let before = r.lowerBound > s.startIndex ? s[s.index(before: r.lowerBound)] : " "
            let after = r.upperBound < s.endIndex ? s[r.upperBound] : " "
            if !(before.isLetter || before.isNumber), !(after.isLetter || after.isNumber), let ar = Range(r, in: a) {
                a[ar].foregroundColor = Ink.ink
                a[ar].backgroundColor = tint.opacity(0.26)
            }
            from = r.upperBound
        }
    }
    return a
}

struct HitRow: View {
    let hit: Hit
    let words: [String]
    let tint: Color
    let selected: Bool
    @State private var hover = false

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 16) {
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 7) {
                    Text(hit.thread.isEmpty ? "untitled" : hit.thread)
                        .font(.system(size: 14, weight: .semibold)).foregroundStyle(Ink.ink).lineLimit(1)
                        .probe("ask.row", .edge, group: "ask.left", scrolls: true)
                    if let tag {
                        Text(tag).font(.system(size: 12, weight: .medium)).foregroundStyle(Ink.faint)
                    }
                }
                Text(marked(hit.snippet.split(whereSeparator: \.isWhitespace).joined(separator: " "), words: words, tint: tint))
                    .font(.system(size: 14)).lineSpacing(2).lineLimit(2).fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
            Text(Words.day(hit.ts)).font(.system(size: 12, weight: .medium)).monospacedDigit().foregroundStyle(Ink.faint)
        }
        .padding(.horizontal, 14).padding(.vertical, 9)
        .background(selected ? Ink.wash : (hover ? Ink.wash.opacity(0.5) : .clear),
                    in: RoundedRectangle(cornerRadius: Radius.row, style: .continuous))
        .contentShape(Rectangle())
        .onHover { hover = $0 }
    }

    private var tag: String? {
        switch hit.kind {
        case "message": return hit.who == "me" ? "you" : (hit.sender.isEmpty || hit.sender.allSatisfy(\.isNumber) ? nil : hit.sender)   // id fragments are not names
        case "prompt": return "you typed"
        case "session": return "session"
        default: return nil
        }
    }
}

struct ThreadPane: View {
    @Environment(AppModel.self) private var model
    let hit: Hit
    let rows: [Hit]
    let words: [String]

    var body: some View {
        let info = Catalog.info(hit.src)
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 8) {
                SourceIcon(id: hit.src, size: 14)
                Text(info.name).font(.system(size: 12, weight: .semibold)).foregroundStyle(Ink.soft)
                Spacer()
                Button("close") { _ = model.ask.close() }.buttonStyle(QuietButton(size: 12))
                KeyHint(key: "esc")
            }
            Text(hit.thread.isEmpty ? "untitled" : hit.thread)
                .display(22).foregroundStyle(Ink.ink).lineLimit(2).padding(.top, 10)
            Text(Words.day(hit.ts)).font(.system(size: 12, weight: .medium)).foregroundStyle(Ink.faint).padding(.top, 2)

            ScrollViewReader { proxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: 12) {
                        if hit.kind == "message" {
                            ForEach(rows) { r in
                                VStack(alignment: .leading, spacing: 2) {
                                    Text((r.who == "me" ? "you" : (r.sender.isEmpty ? "them" : r.sender)) + "  ·  " + Words.day(r.ts))
                                        .font(.system(size: 11, weight: .semibold)).foregroundStyle(Ink.faint)
                                    Text(r.id == hit.id ? marked(r.text, words: words, tint: info.color, base: Ink.ink)
                                         : AttributedString(String(r.text.prefix(1200))))
                                        .font(.system(size: 14)).lineSpacing(3)
                                        .foregroundStyle(r.who == "me" ? Ink.ink : Ink.soft)
                                        .textSelection(.enabled)
                                }
                                .padding(.leading, 12)
                                .overlay(alignment: .leading) {
                                    if r.id == hit.id { Circle().fill(info.color).frame(width: 5, height: 5).offset(y: -1) }
                                }
                                .id(r.id)
                            }
                        } else {
                            Text(marked(String(hit.text.prefix(6000)), words: words, tint: info.color, base: Ink.ink))
                                .font(.system(size: 14)).lineSpacing(4).textSelection(.enabled)
                            if !hit.url.isEmpty {
                                Text(hit.url).font(.system(size: 12)).foregroundStyle(Ink.faint).textSelection(.enabled)
                            }
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.top, 18).padding(.bottom, 30)
                }
                .onChange(of: rows.count, initial: true) { _, _ in proxy.scrollTo(hit.id, anchor: .center) }
            }
        }
        .padding(.horizontal, 26).padding(.top, 34)
    }
}
