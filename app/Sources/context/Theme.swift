import AppKit
import SwiftUI

extension NSColor {
    convenience init(hex: UInt32) {
        self.init(srgbRed: CGFloat((hex >> 16) & 0xFF) / 255, green: CGFloat((hex >> 8) & 0xFF) / 255,
                  blue: CGFloat(hex & 0xFF) / 255, alpha: 1)
    }
    static func dyn(_ light: UInt32, _ dark: UInt32) -> NSColor {
        NSColor(name: nil) { $0.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua ? NSColor(hex: dark) : NSColor(hex: light) }
    }
}

extension Color {
    init(_ light: UInt32, _ dark: UInt32) { self.init(nsColor: .dyn(light, dark)) }
}

/// The whole palette. Colour outside this file belongs to a source mark.
enum Ink {
    /// (light, dark). every level of text, and every ground text is set on, is here so the build can measure them.
    static let hex: [String: (UInt32, UInt32)] = [
        "paper": (0xF5F4F0, 0x131414), "raised": (0xFBFAF7, 0x1A1B1B), "wash": (0xE8E7E0, 0x1D1E1E), "side": (0xEFEEE9, 0x181919),
        "mark": (0xFBEFC2, 0x3A3212),
        "ink": (0x17181A, 0xEDECE8), "soft": (0x55565A, 0xA8A8A4), "faint": (0x6E6F6D, 0x858683),
    ]
    static let paperNS = NSColor.dyn(0xF5F4F0, 0x131414)
    static let paper = Color(nsColor: paperNS)
    static let ink = Color(0x17181A, 0xEDECE8)
    /// the two dimmer levels of text. both read at 4.5:1 or better on paper and on a raised card, light and dark;
    /// soft does on the wash too. faint is never set on the wash.
    static let soft = Color(hex["soft"]!.0, hex["soft"]!.1)
    static let faint = Color(hex["faint"]!.0, hex["faint"]!.1)

    /// WCAG contrast between two colours given as 0xRRGGBB.
    static func contrast(_ a: UInt32, _ b: UInt32) -> Double {
        func lum(_ v: UInt32) -> Double {
            func ch(_ c: UInt32) -> Double { let x = Double(c) / 255; return x <= 0.03928 ? x / 12.92 : pow((x + 0.055) / 1.055, 2.4) }
            return 0.2126 * ch((v >> 16) & 0xFF) + 0.7152 * ch((v >> 8) & 0xFF) + 0.0722 * ch(v & 0xFF)
        }
        let la = lum(a), lb = lum(b)
        return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)
    }

    /// Every pairing of a text level with a ground it is used on that falls short of 4.5:1, as plain lines.
    static func contrastFaults() -> [String] {
        var out: [String] = []
        for (text, grounds) in [("ink", ["paper", "raised", "wash", "side", "mark"]), ("soft", ["paper", "raised", "wash", "side"]), ("faint", ["paper", "raised"])] {
            for g in grounds {
                for (mode, pick) in [("light", { (p: (UInt32, UInt32)) in p.0 }), ("dark", { (p: (UInt32, UInt32)) in p.1 })] {
                    let c = contrast(pick(hex[text]!), pick(hex[g]!))
                    if c < 4.5 { out.append("contrast: \(text) on \(g), \(mode): \(String(format: "%.2f", c)) is under 4.5") }
                }
            }
        }
        return out
    }
    static let line = Color(0xDAD9D1, 0x272828)
    /// the soft ground behind the sentence a chosen piece of evidence supports. only ink is set on it.
    static let mark = Color(hex["mark"]!.0, hex["mark"]!.1)
    static let wash = Color(0xE8E7E0, 0x1D1E1E)
    /// the sidebar's ground: half a step off the paper. like the wash, faint is never set on it.
    static let side = Color(hex["side"]!.0, hex["side"]!.1)
    /// the one accent. it means "live, or yours, right now": the caret, the writing edge, the row the keys are on.
    /// never a fill behind text, never a button.
    static let ember = Color(0xE8502A, 0xFF6A3D)
    static let emberNS = NSColor.dyn(0xE8502A, 0xFF6A3D)
    /// one step up from the ground: a card that has been opened in place
    static let raised = Color(0xFBFAF7, 0x1A1B1B)
}

// MARK: the system
// one scale of type, one of space, one set of corners, one vocabulary of motion. a new screen takes its numbers
// from here; a number that is not here is a fault. (DESIGN.md.)

/// Type. Sans for the interface, serif for anything said to them or about them. No half sizes.
/// Weights: regular for what is read, medium for the name of a thing or the one that is chosen, semibold only for
/// a small heading. Bold is for figures.
enum Face {
    static let tiny: CGFloat = 10       // a key, a count in a badge
    static let micro: CGFloat = 11      // a heading over a list, a key hint
    static let small: CGFloat = 12      // what stands beside or under a name
    static let label: CGFloat = 13      // a row, a control, a name
    static let body: CGFloat = 15       // their own words, the input
    static let read: CGFloat = 16       // serif: an answer, a page
    static let head: CGFloat = 19       // serif: a heading in a page, a sentence that stands over one
    static let title: CGFloat = 30      // serif: a page's name, the line home says
    static let figure: CGFloat = 44     // the one big number

    /// the serif, for a line said to them: a page's name, home's greeting, a pane's name.
    static func said(_ size: CGFloat) -> Font { .system(size: size, weight: .regular, design: .serif) }
    /// a measure: a date, a count, a kind, a key. the mono, small. three voices in all: serif for what is said,
    /// sans for the name of a thing, mono for what is measured.
    static let meta = Font.system(size: 10.5, design: .monospaced)
    /// a small heading over a list or a group: the only place the interface is semibold.
    static let heading = Font.system(size: micro, weight: .semibold)
}

/// Space, in points. Gaps and paddings come from this run and from nowhere else.
enum Space {
    static let hair: CGFloat = 2, xs: CGFloat = 4, s: CGFloat = 8, m: CGFloat = 12, l: CGFloat = 16, xl: CGFloat = 24, xxl: CGFloat = 32, page: CGFloat = 48
}

/// Corners. Four, by what the thing is; a capsule is only for a thing that is pressed like a key (send, a switch).
enum Radius {
    static let chip: CGFloat = 5       // a citation number, a key, a mark in the text
    static let row: CGFloat = 8        // a row, a small button, a field in a list
    static let card: CGFloat = 12      // a raised card, a table, a tile
    static let field: CGFloat = 18     // the input, their message, a floating panel
}

/// Motion. Five words, each with one job. Everything honours Reduce Motion: a move becomes a short fade.
/// - snap: rows and words changing place. 420 ms unless a caller says otherwise, fast out, long soft landing. no overshoot.
///   a hover is `hover`, 150 ms.
/// - tray: anything that changes size or place. a spring that can be turned round mid-flight.
/// - pop: the one overshoot, kept for a citation landing or opening.
/// - page: a page arriving. the page before it is cut, not faded: two pages are never read through each other.
/// - enter / exit: a panel or a card. arriving is quick; leaving is quicker.
enum Motion {
    static func spring(_ reduce: Bool) -> Animation {
        reduce ? .easeOut(duration: 0.12) : .spring(response: 0.5, dampingFraction: 0.86)
    }
    /// words and rows changing place: fast out of the gate, a long soft landing, no overshoot.
    /// the curve: cubic-bezier(.24, 1, .29, 1).
    static func snap(_ reduce: Bool, _ duration: Double = 0.42) -> Animation {
        reduce ? .easeOut(duration: 0.1) : .timingCurve(0.24, 1, 0.29, 1, duration: duration)
    }
    static func quick(_ reduce: Bool) -> Animation {
        reduce ? .easeOut(duration: 0.1) : .spring(response: 0.32, dampingFraction: 0.88)
    }
    /// anything that changes size or place. it can be turned round mid-flight.
    static func tray(_ reduce: Bool) -> Animation {
        reduce ? .easeOut(duration: 0.12) : .spring(response: 0.38, dampingFraction: 0.86)
    }
    /// the one overshoot in the app: a citation landing in the text.
    static func pop(_ reduce: Bool) -> Animation {
        reduce ? .easeOut(duration: 0.1) : .spring(response: 0.28, dampingFraction: 0.72)
    }
    /// a page arriving: 220 ms on the long-landing curve, cubic-bezier(.19, 1, .22, 1).
    static func page(_ reduce: Bool) -> Animation {
        reduce ? .easeOut(duration: 0.1) : .timingCurve(0.19, 1, 0.22, 1, duration: 0.22)
    }
    // the line, the desk and the page (DESIGN.md). each has one job; with Reduce Motion each is instant, with no movement.
    /// ribbon.draw: the line of the ribbon drawing left to right while evidence is looked for. 600 ms.
    static func draw(_ reduce: Bool) -> Animation? { reduce ? nil : .timingCurve(0.22, 1, 0.36, 1, duration: 0.6) }
    /// ribbon.dot: one piece of evidence landing on the ribbon; also the chosen dot growing. a small overshoot.
    static func dot(_ reduce: Bool) -> Animation? { reduce ? nil : .spring(response: 0.3, dampingFraction: 0.62) }
    /// words.in: the newest words of an answer being written. 180 ms ease-out, opacity only: nothing before them moves.
    static func words(_ reduce: Bool) -> Animation? { reduce ? nil : .easeOut(duration: 0.18) }
    /// note.in: a margin note arriving beside its sentence: 8 pt from the right with a fade, 40 ms after the one above.
    static func note(_ reduce: Bool, _ index: Int) -> Animation? { reduce ? nil : .timingCurve(0.25, 1, 0.5, 1, duration: 0.3).delay(Double(min(index, 8)) * 0.04) }
    static let noteSlide: CGFloat = 8
    /// note.lit: the chosen note moving 2 pt and taking its accent rule; the sentence's ground. 140 ms.
    static func lit(_ reduce: Bool) -> Animation? { reduce ? nil : .timingCurve(0.25, 1, 0.5, 1, duration: 0.14) }
    /// desk.settle: a line of home settling in, 35 ms after the one before it. also the roll of its number.
    static func settle(_ reduce: Bool, _ index: Int) -> Animation? { reduce ? nil : .timingCurve(0.19, 1, 0.22, 1, duration: 0.42).delay(0.05 + Double(min(index, 12)) * 0.035) }
    /// strip.grow: the archive's strip of months rising from its baseline, left to right, once. 700 ms in all.
    static func grow(_ reduce: Bool, _ fraction: Double) -> Animation? { reduce ? nil : .timingCurve(0.22, 1, 0.36, 1, duration: 0.4).delay(0.1 + fraction * 0.3) }
    /// lift: the question leaving the ask field for the top of the conversation: one move, on a spring.
    static func lift(_ reduce: Bool) -> Animation? { reduce ? nil : .spring(response: 0.46, dampingFraction: 0.84) }
    /// desk.out: the desk falling back and fading as the question lifts. 120 ms, so it is gone before the answer is read.
    static func deskOut(_ reduce: Bool) -> Animation? { reduce ? nil : .easeOut(duration: 0.12) }
    /// unfold: a message opening out of its note, and closing back into it. the tray spring.
    static func unfold(_ reduce: Bool) -> Animation? { reduce ? nil : .spring(response: 0.38, dampingFraction: 0.86) }

    /// what the pointer is over: 150 ms ease-out (things' own hover).
    static let hover = Animation.easeOut(duration: 0.15)
    /// arriving is quick; leaving is quicker.
    static let enter = Animation.timingCurve(0.24, 1, 0.29, 1, duration: 0.12)
    static let exit = Animation.easeOut(duration: 0.09)
    /// how far a page rises as it arrives, and how far a pressed thing gives.
    static let rise: CGFloat = 6
    /// how far a pressed thing gives. with Reduce Motion it does not give at all.
    static var press: CGFloat { NSWorkspace.shared.accessibilityDisplayShouldReduceMotion ? 1 : 0.97 }
}

/// A page arriving in the main area. The page before it has already gone (nothing fades out under this one), so at
/// no moment are two pages legible on top of each other. With Reduce Motion it is a short fade and no rise.
struct PageIn: ViewModifier {
    @State private var shown = Probe.still
    @Environment(\.accessibilityReduceMotion) private var reduce
    func body(content: Content) -> some View {
        content
            .opacity(shown ? 1 : 0)
            .offset(y: shown || reduce ? 0 : Motion.rise)
            .onAppear {
                if Probe.still || shown { shown = true; return }
                withAnimation(Motion.page(reduce)) { shown = true }
            }
    }
}

/// The same arrival for a view that stays while what it shows is swapped (one conversation for another): at the
/// change it is cut to nothing and the new content arrives. Nothing of the old is left under the new.
struct Arrive<V: Equatable>: ViewModifier {
    let value: V
    @State private var shown = true
    @Environment(\.accessibilityReduceMotion) private var reduce
    func body(content: Content) -> some View {
        content
            .opacity(shown ? 1 : 0)
            .offset(y: shown || reduce ? 0 : Motion.rise)
            .onChange(of: value) { _, _ in
                guard !Probe.still else { return }
                var cut = Transaction(); cut.disablesAnimations = true
                withTransaction(cut) { shown = false }
                DispatchQueue.main.async { withAnimation(Motion.page(reduce)) { shown = true } }
            }
    }
}

/// A question that has just been sent: it rises from where the input is to its place at the top, in one move.
/// Only a question with no answer yet does this; one read back from a saved chat is simply there.
struct Lift: ViewModifier {
    let on: Bool
    @State private var up = false
    @Environment(\.accessibilityReduceMotion) private var reduce
    static let from: CGFloat = 260
    func body(content: Content) -> some View {
        let rest = up || !on || reduce || Probe.still
        content
            .offset(y: rest ? 0 : Lift.from)
            .scaleEffect(rest ? 1 : 0.98, anchor: .bottomTrailing)
            .onAppear {
                guard on, !reduce, !Probe.still else { up = true; return }
                withAnimation(Motion.lift(false)) { up = true }
            }
    }
}

extension View {
    /// This view is a page of the main area: it arrives by itself and is cut when it leaves.
    func pageIn() -> some View { modifier(PageIn()).transition(.identity) }
    /// What this view shows was swapped for something else: it arrives again.
    func arrives<V: Equatable>(on value: V) -> some View { modifier(Arrive(value: value)) }
}

extension View {
    /// Bold, tight, lowercase display type.
    func display(_ size: CGFloat, weight: Font.Weight = .bold) -> some View {
        font(.system(size: size, weight: weight)).tracking(-size * 0.034)
    }
}

/// A line that arrives a moment after the one above it.
struct Reveal: ViewModifier {
    let order: Int
    @State private var shown = Probe.on        // a layout check measures where things come to rest: there from the first pass
    @Environment(\.accessibilityReduceMotion) private var reduce
    func body(content: Content) -> some View {
        content
            .opacity(shown ? 1 : 0)
            .offset(y: shown || reduce ? 0 : 14)
            .blur(radius: shown || reduce ? 0 : 5)
            .onAppear {
                if Probe.on { shown = true; return }      // a layout check measures where things come to rest
                withAnimation(Motion.spring(reduce).delay(reduce ? 0 : 0.06 + Double(order) * 0.05)) { shown = true }
            }
    }
}

extension View {
    func reveal(_ order: Int) -> some View { modifier(Reveal(order: order)) }
}

/// A number that rolls to its value.
struct Ticker: View, Animatable {
    var value: Double
    var animatableData: Double {
        get { value }
        set { value = newValue }
    }
    var body: some View {
        Text(Int(value.rounded()).formatted(.number.grouping(.automatic).locale(Locale(identifier: "en_US"))))
            .monospacedDigit()
    }
}

/// The one filled control on a screen.
struct PrimaryButton: ButtonStyle {
    var hint: String? = "return"
    @Environment(\.isEnabled) private var enabled
    func makeBody(configuration: Configuration) -> some View {
        HStack(spacing: 10) {
            configuration.label.font(.system(size: 15, weight: .semibold))
            if let hint {
                Text(hint).font(.system(size: 12, weight: .medium)).opacity(0.45)
            }
        }
        .lineLimit(1).fixedSize()     // the rail next to it must never squeeze the label
        .foregroundStyle(Ink.paper)
        .padding(.horizontal, 20).padding(.vertical, 11)
        .background(Ink.ink.opacity(enabled ? 1 : 0.3), in: Capsule())
        .probe("primary button", .button)
        .scaleEffect(configuration.isPressed ? Motion.press : 1)
        .animation(.spring(response: 0.25, dampingFraction: 0.7), value: configuration.isPressed)
    }
}

/// A row or a tile that gives a little under the press and comes back: the same for every pressable thing that
/// is not a word (things' 0.98, a touch more because these are small).
struct Pressable: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? Motion.press : 1)
            .animation(.spring(response: 0.22, dampingFraction: 0.8), value: configuration.isPressed)
    }
}

/// A figure that stands at its value the moment it is drawn, and runs only from one real value to the next.
/// It never counts up from nothing: a number seen rising from zero is a number that was wrong for a moment.
struct Figure: View {
    let target: Int
    @State private var shown: Int?
    @Environment(\.accessibilityReduceMotion) private var reduce
    var body: some View {
        Ticker(value: Double(shown ?? target))
            .onChange(of: target) { old, new in
                if reduce || Probe.on { shown = new; return }
                if shown == nil { shown = old }
                withAnimation(.timingCurve(0.19, 1, 0.22, 1, duration: 0.6)) { shown = new }
            }
    }
}

/// A plain word that darkens on hover.
struct QuietButton: ButtonStyle {
    var size: CGFloat = 14
    func makeBody(configuration: Configuration) -> some View { QuietLabel(configuration: configuration, size: size) }
    struct QuietLabel: View {
        let configuration: Configuration
        let size: CGFloat
        @State private var hover = false
        var body: some View {
            configuration.label.lineLimit(1).fixedSize()
                .font(.system(size: size, weight: .medium))
                .foregroundStyle(hover ? Ink.ink : Ink.soft)
                .opacity(configuration.isPressed ? 0.6 : 1)
                .contentShape(Rectangle())
                .onHover { hover = $0 }
                .animation(.easeOut(duration: 0.12), value: hover)
        }
    }
}

/// A key name set small beside an action.
struct KeyHint: View {
    let key: String
    var body: some View {
        Text(key)
            .font(.system(size: 11, weight: .semibold, design: .rounded))
            .foregroundStyle(Ink.soft)
            .padding(.horizontal, 5).padding(.vertical, 1.5)
            .background(Ink.wash, in: RoundedRectangle(cornerRadius: Radius.chip, style: .continuous))
    }
}

// MARK: marks

/// A rounded slab whose corner and proportion animate, so one source can turn into the next.
struct MarkShape: Shape {
    var corner: CGFloat   // 0 square, 1 fully round
    var aspect: CGFloat   // width over height
    var animatableData: AnimatablePair<CGFloat, CGFloat> {
        get { AnimatablePair(corner, aspect) }
        set { corner = newValue.first; aspect = newValue.second }
    }
    func path(in rect: CGRect) -> Path {
        let side = min(rect.width, rect.height)
        let w = aspect >= 1 ? side : side * aspect
        let h = aspect >= 1 ? side / aspect : side
        let r = CGRect(x: rect.midX - w / 2, y: rect.midY - h / 2, width: w, height: h)
        return Path(roundedRect: r, cornerRadius: min(w, h) / 2 * corner, style: corner > 0.6 ? .circular : .continuous)
    }
}

enum MarkMood { case idle, waiting, reading, done, blocked }

struct Mark: View {
    let source: SourceInfo
    var mood: MarkMood = .done
    var size: CGFloat = 12
    @State private var breathe = false
    @Environment(\.accessibilityReduceMotion) private var reduce

    var body: some View {
        let shape = MarkShape(corner: source.corner, aspect: source.aspect)
        let fill: Double = mood == .blocked ? 0 : (mood == .waiting ? 0.22 : 1)
        ZStack {
            shape.fill(source.color).opacity(fill)
            shape.stroke(source.color, style: StrokeStyle(lineWidth: max(1.2, size / 110), lineCap: .round,
                                                           dash: size > 40 ? [1, size / 22] : []))
                .opacity(mood == .blocked ? 0.8 : 0)
        }
        .frame(width: size, height: size)
        .rotationEffect(.degrees(source.turn))
        .scaleEffect(mood == .reading && breathe && !reduce ? 1.04 : 1)
        .onChange(of: mood, initial: true) { _, m in
            if m == .reading && !reduce {
                withAnimation(.easeInOut(duration: 1.4).repeatForever(autoreverses: true)) { breathe = true }
            } else {
                withAnimation(Motion.spring(reduce)) { breathe = false }
            }
        }
    }
}

// MARK: words for dates

enum Words {
    static let months = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]

    /// "2023-07-11..." -> (2023, 7, 11)
    static func parts(_ iso: String) -> (y: Int, m: Int, d: Int)? {
        let p = iso.prefix(10).split(separator: "-")
        guard p.count == 3, let y = Int(p[0]), let m = Int(p[1]), let d = Int(p[2]), (1...12).contains(m) else { return nil }
        return (y, m, d)
    }

    static let monthsLong = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
                             "november", "december"]

    /// "2024-03" -> "march 2024"
    static func monthLong(_ ym: String) -> String {
        let p = ym.split(separator: "-")
        guard p.count >= 2, let m = Int(p[1]), (1...12).contains(m) else { return ym }
        return "\(monthsLong[m - 1]) \(p[0])"
    }

    static func monthYear(_ iso: String) -> String {
        guard let p = parts(iso) else { return "" }
        return "\(months[p.m - 1]) \(p.y)"
    }

    static func day(_ iso: String) -> String {
        guard let p = parts(iso) else { return "" }
        let thisYear = Calendar.current.component(.year, from: Date())
        return p.y == thisYear ? "\(p.d) \(months[p.m - 1])" : "\(p.d) \(months[p.m - 1]) \(p.y)"
    }

    static func range(_ a: String, _ b: String) -> String {
        let today = isoDay(Date())
        let end = b.prefix(7) == today.prefix(7) ? "today" : monthYear(b)
        let start = monthYear(a)
        return start.isEmpty ? "" : (start == end ? start : "\(start) → \(end)")
    }

    static func isoDay(_ d: Date) -> String {
        let c = Calendar.current.dateComponents([.year, .month, .day], from: d)
        return String(format: "%04d-%02d-%02d", c.year ?? 0, c.month ?? 0, c.day ?? 0)
    }

    static func ago(_ iso: String) -> String {
        guard let p = parts(iso),
              let d = Calendar.current.date(from: DateComponents(year: p.y, month: p.m, day: p.d)) else { return iso }
        let days = Calendar.current.dateComponents([.day], from: d, to: Calendar.current.startOfDay(for: Date())).day ?? 0
        switch days {
        case ..<1: return "today"
        case 1: return "yesterday"
        case 2..<14: return "\(days) days ago"
        case 14..<60: return "\(days / 7) weeks ago"
        default: return day(iso)
        }
    }

    static func since(_ date: Date?) -> String {
        guard let date else { return "never" }
        let s = Int(Date().timeIntervalSince(date))
        switch s {
        case ..<60: return "just now"
        case 60..<3600: return "\(s / 60) min ago"
        case 3600..<86400: return s < 7200 ? "1 hour ago" : "\(s / 3600) hours ago"
        default: return s < 172800 ? "yesterday" : "\(s / 86400) days ago"
        }
    }

    static func count(_ n: Int) -> String {
        n.formatted(.number.grouping(.automatic).locale(Locale(identifier: "en_US")))
    }
}

// MARK: the keyboard's place

/// Where the keyboard is, drawn our way: a thin ember line round the control, in place of the system's blue glow.
/// The ember means "yours, right now", which is what focus is.
struct Ring: ViewModifier {
    var radius: CGFloat
    var inset: CGFloat
    @FocusState private var on: Bool
    func body(content: Content) -> some View {
        let show = on && KeyNav.shared.on
        content.focused($on).focusEffectDisabled()
            .overlay {
                RoundedRectangle(cornerRadius: radius, style: .continuous).strokeBorder(Ink.ember, lineWidth: 1.5)
                    .padding(-inset).opacity(show ? 1 : 0).allowsHitTesting(false)
            }
            .background { if show { Color.clear.probe("focus.ring", .block, scrolls: true) } }
    }
}

/// Whether the owner is walking the window with the keyboard. The ring is drawn only then: macos gives some control the
/// focus when a window opens and after a click, and a line round it then says something nobody asked.
@Observable final class KeyNav {
    static let shared = KeyNav()
    var on = false

    /// A key went down in the window. Tab always starts a walk; an arrow does when the cursor is not in a field.
    func key(_ code: UInt16, typing: Bool) {
        let walks = code == 48 || (!typing && (123...126).contains(Int(code)))
        if walks, !on { on = true }
    }

    /// The mouse was pressed: the walk is over.
    func mouse() { if on { on = false } }

    /// The rule, run dry: nothing at launch, on after tab, off again at a click, and an arrow in a field is typing.
    static func faults() -> [String] {
        let k = KeyNav()
        var out: [String] = []
        if k.on { out.append("focus: the ring is on at launch, before any key") }
        k.key(125, typing: true)
        if k.on { out.append("focus: an arrow key in a field starts the ring") }
        k.key(0, typing: false)
        if k.on { out.append("focus: a letter starts the ring") }
        k.key(48, typing: true)
        if !k.on { out.append("focus: tab does not start the ring") }
        k.mouse()
        if k.on { out.append("focus: the ring stays after a click") }
        k.key(126, typing: false)
        if !k.on { out.append("focus: an arrow outside a field does not start the ring") }
        return out
    }
}

extension View {
    /// The focus ring for a control with this corner. A capsule passes a large radius.
    func ring(_ radius: CGFloat = 8, inset: CGFloat = 2) -> some View { modifier(Ring(radius: radius, inset: inset)) }
}

/// The same line for a control drawn by a button style, which cannot hold the focus itself: it reads whether the
/// button it is the face of has the keyboard.
struct FocusMark: View {
    var radius: CGFloat
    @Environment(\.isFocused) private var on
    var body: some View {
        RoundedRectangle(cornerRadius: radius, style: .continuous).strokeBorder(Ink.ember, lineWidth: 1.5).opacity(on && KeyNav.shared.on ? 1 : 0).allowsHitTesting(false)
    }
}
