import AppKit
import SwiftUI

/// The morning card: one thing from their own history, new each day, with one action. No card on a day when nothing is
/// strong enough: the engine decides that, and an empty slot is better than a weak card.
struct Card: Equatable {
    let id: String
    let kind: String          // promised, years_ago, saved
    let line: String
    var state: String         // unread, read, done
    let cite: Hit?
    let action: String        // reply, open, ask
    let open: String
    let q: String

    init?(_ d: [String: Any]?) {
        guard let d, let id = d["id"] as? String, let line = d["line"] as? String, !line.isEmpty else { return nil }
        self.id = id
        self.line = line
        kind = d["kind"] as? String ?? ""
        state = d["state"] as? String ?? "unread"
        cite = (d["cite"] as? [String: Any]).flatMap { c in
            var c = c
            if c["text"] == nil { c["text"] = c["quote"] }
            return Answer.cite(c, 0, prefix: "card")
        }
        let a = d["action"] as? [String: Any] ?? [:]
        action = a["label"] as? String ?? "open"
        open = a["open"] as? String ?? ""
        q = a["q"] as? String ?? ""
    }

    var kindWord: String {
        switch kind {
        case "promised": return "you said you would"
        case "years_ago": return "on this day"
        case "saved": return "you saved this"
        default: return "from your history"
        }
    }
    var actionWord: String { action == "ask" ? "ask about it" : (action == "reply" ? "see it, and reply" : "see it") }
}

extension AppModel {
    /// Reads the card the daily run left. It never makes one here: that takes a model call, and belongs to the run.
    func loadCard() {
        guard !Engine.debug, saved.onboarded else { return }
        guard saved.morningCard else { card = nil; return }
        engine.client.today(cached: true) { [weak self] d in
            guard let self else { return }
            let next = Card(d?["card"] as? [String: Any])
            if next != self.card { withAnimation(Motion.tray(false)) { self.card = next } }
        }
    }

    /// The card's one action: the message in its conversation, its own page, or a question about it. Then it is done for today.
    func actOnCard() {
        guard let c = card else { return }
        if c.action == "ask", !c.q.isEmpty {
            tab = .home
            ask.ask(engine, c.q)
        } else if let u = Answer.web(c.open) {
            if !Probe.on { NSWorkspace.shared.open(u) }
        } else if let hit = c.cite {
            ask.peekThread(hit, turn: -1, engine)
        }
        card?.state = "done"
        if !Engine.debug { engine.client.today(mark: c.id, done: true) }
    }

    func dismissCard() {
        guard let c = card else { return }
        card = nil
        if !Engine.debug { engine.client.today(mark: c.id, done: false) }
    }
}

struct MorningCard: View {
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduce
    let card: Card

    var body: some View {
        let shape = RoundedRectangle(cornerRadius: Radius.card, style: .continuous)
        let done = card.state == "done"
        HStack(alignment: .top, spacing: 0) {
            VStack(alignment: .leading, spacing: 8) {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text(done ? "done for today" : card.kindWord).font(.system(size: 12, weight: .semibold)).foregroundStyle(Ink.soft).lineLimit(1).fixedSize()
                        .probe("card.kind", .line)
                    if let c = card.cite, !done {
                        SourceIcon(id: c.src, size: 14).alignmentGuide(.firstTextBaseline) { $0[.bottom] - 2 }
                        Text((c.thread.isEmpty ? Catalog.info(c.src).name : c.thread.lowercased()) + "  ·  " + Words.ago(c.ts))
                            .font(.system(size: 12, weight: .medium)).foregroundStyle(Ink.faint).lineLimit(1).truncationMode(.middle)
                    }
                }
                Text(card.line)
                    .font(.system(size: done ? 14 : 18, weight: .regular, design: .serif)).lineSpacing(3)
                    .foregroundStyle(done ? Ink.soft : Ink.ink)
                    .fixedSize(horizontal: false, vertical: true)
                    .probe("card.line", .text)
                if !done {
                    HStack(spacing: 16) {
                        Button(card.actionWord) { withAnimation(Motion.tray(reduce)) { model.actOnCard() } }.buttonStyle(QuietButton(size: 13)).fixedSize()
                            .probe("card.act", .button)
                        Button("not today") { withAnimation(reduce ? .easeOut(duration: 0.1) : .easeOut(duration: 0.18)) { model.dismissCard() } }
                            .buttonStyle(QuietButton(size: 13)).fixedSize()
                    }
                    .padding(.top, 2)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 18).padding(.vertical, 14)
        .frame(maxWidth: 620, alignment: .leading)
        .background(Ink.raised, in: shape)
        .overlay { shape.strokeBorder(Ink.ink.opacity(0.09), lineWidth: 1) }
        // unread: the one live mark on the page
        .overlay(alignment: .leading) {
            if card.state == "unread" { RoundedRectangle(cornerRadius: 1).fill(Ink.ember).frame(width: 2).padding(.vertical, 14) }
        }
        .shadow(color: .black.opacity(Probe.on ? 0 : 0.05), radius: 10, y: 3)
        .probe("card.block", .block, group: "home.column")
    }
}

/// One short sound, made here so no audio file ships: two soft notes, a fifth apart, gone in a third of a second.
/// Played when an answer lands while the owner is elsewhere, and when the first read is done. Nothing else makes a noise.
enum Tick {
    private static let sound: NSSound? = {
        let rate = 44100.0, length = 0.34
        let n = Int(rate * length)
        var pcm = Data(capacity: n * 2)
        for i in 0..<n {
            let t = Double(i) / rate
            let a = sin(2 * .pi * 660 * t) * exp(-t * 18)
            let b = t > 0.09 ? sin(2 * .pi * 990 * (t - 0.09)) * exp(-(t - 0.09) * 14) : 0
            let v = Int16(max(-1, min(1, (a + b) * 0.22)) * 32767)
            withUnsafeBytes(of: v.littleEndian) { pcm.append(contentsOf: $0) }
        }
        var wav = Data()
        func put32(_ v: UInt32) { withUnsafeBytes(of: v.littleEndian) { wav.append(contentsOf: $0) } }
        func put16(_ v: UInt16) { withUnsafeBytes(of: v.littleEndian) { wav.append(contentsOf: $0) } }
        wav.append("RIFF".data(using: .ascii)!); put32(UInt32(36 + pcm.count)); wav.append("WAVEfmt ".data(using: .ascii)!)
        put32(16); put16(1); put16(1); put32(UInt32(rate)); put32(UInt32(rate) * 2); put16(2); put16(16)
        wav.append("data".data(using: .ascii)!); put32(UInt32(pcm.count)); wav.append(pcm)
        return NSSound(data: wav)
    }()

    static func play() {
        guard !Engine.debug, !AppModel.shared.saved.soundOff else { return }
        sound?.stop()
        sound?.play()
    }
}
