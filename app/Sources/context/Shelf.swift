import AppKit
import SwiftUI

/// A soft starter under the field.
struct Starter: ButtonStyle {
    var quiet = false
    var lead = false          // the one chip that is meant to stand out: ink on paper, reversed
    func makeBody(configuration: Configuration) -> some View { Label(configuration: configuration, quiet: quiet, lead: lead) }
    struct Label: View {
        let configuration: Configuration
        let quiet: Bool
        let lead: Bool
        @State private var hover = false
        var body: some View {
            HStack(spacing: 6) {
                if quiet { Circle().fill(hover ? Ink.ink : Ink.soft).frame(width: 4, height: 4) }
                configuration.label.font(.system(size: Face.label, weight: lead ? .medium : .regular)).lineLimit(1).fixedSize()
            }
                // a starter is a few words on the paper with a hairline round them: no filled pill. every one is set
                // the same, so none looks chosen; under the pointer the line and the words darken together
                .foregroundStyle(lead ? Ink.paper : (hover ? Ink.ink : Ink.soft))
                .padding(.horizontal, Space.m).frame(height: 28)
                .background(lead ? Ink.ink.opacity(hover ? 0.85 : 1) : (hover ? Ink.wash.opacity(0.6) : .clear), in: RoundedRectangle(cornerRadius: Radius.row, style: .continuous))
                .overlay { if !lead { RoundedRectangle(cornerRadius: Radius.row, style: .continuous).strokeBorder(hover ? Ink.soft.opacity(0.55) : Ink.line, lineWidth: 1) } }
                .overlay(FocusMark(radius: Radius.row))
                .scaleEffect(configuration.isPressed ? Motion.press : 1)
                .onHover { hover = $0 }
                .animation(.spring(response: 0.22, dampingFraction: 0.8), value: configuration.isPressed)
                .animation(Motion.hover, value: hover)
        }
    }
}

/// Lays children out left to right and wraps, like words in a paragraph.
struct Flow: Layout {
    var spacing: CGFloat = 8
    var lineSpacing: CGFloat = 16
    var centred = false      // each line stands in the middle of the width, so a last word alone does not hang at the left

    /// What was worked out for a width, kept until the children change. A flow inside a flow is asked the same
    /// question many times in one pass; without this the shelf takes seconds to lay out.
    struct Cache { var fits: [CGFloat: CGSize] = [:] }
    func makeCache(subviews: Subviews) -> Cache { Cache() }
    func updateCache(_ cache: inout Cache, subviews: Subviews) { cache = Cache() }

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout Cache) -> CGSize {
        let key = proposal.width ?? -1
        if let hit = cache.fits[key] { return hit }
        let rows = arrange(proposal.width ?? .infinity, subviews)
        let width = rows.map { $0.width }.max() ?? 0
        let height = rows.reduce(0) { $0 + $1.height } + CGFloat(max(0, rows.count - 1)) * lineSpacing
        let size = CGSize(width: centred ? (proposal.width ?? width) : (proposal.width.map { min($0, width) } ?? width), height: height)
        cache.fits[key] = size
        return size
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout Cache) {
        var y = bounds.minY
        for row in arrange(bounds.width, subviews) {
            var x = bounds.minX + (centred ? max(0, (bounds.width - row.width) / 2) : 0)
            for i in row.items {
                let size = subviews[i].sizeThatFits(ProposedViewSize(width: bounds.width, height: nil))
                subviews[i].place(at: CGPoint(x: x, y: y), anchor: .topLeading, proposal: ProposedViewSize(size))
                x += size.width + spacing
            }
            y += row.height + lineSpacing
        }
    }

    private func arrange(_ width: CGFloat, _ subviews: Subviews) -> [(items: [Int], width: CGFloat, height: CGFloat)] {
        var rows: [(items: [Int], width: CGFloat, height: CGFloat)] = []
        var cur: [Int] = [], w: CGFloat = 0, h: CGFloat = 0
        for i in subviews.indices {
            let size = subviews[i].sizeThatFits(ProposedViewSize(width: width.isFinite ? width : nil, height: nil))
            if !cur.isEmpty, w + spacing + size.width > width {
                rows.append((cur, w, h))
                cur = []; w = 0; h = 0
            }
            w += (cur.isEmpty ? 0 : spacing) + size.width
            h = max(h, size.height)
            cur.append(i)
        }
        if !cur.isEmpty { rows.append((cur, w, h)) }
        return rows
    }
}

/// One thing on the shelf: a source that has been read, or something that is waiting on you.
struct ShelfItem: Identifiable, Equatable {
    let id: String
    var name: String
    var source: String = ""        // catalog id, for the mark and the app icon
    var rows = 0
    var live = false               // being read right now
    var action = ""                // for a waiting item: the two words under it
    var line = ""                  // what the top line says when this one has the focus
    var kind = ""                  // fix: what a click does
    var stale = false              // holds rows from last time, but cannot be read now
}

/// Every source as an object, on one shelf: its own app icon (or our mark) with its number under it.
/// What needs you sits together at the end, each with the one thing it needs.
struct Shelf: View {
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduce

    var body: some View {
        let groups = model.shelf
        let focus = groups.flatMap(\.items).first { $0.id == model.shelfFocus }
        VStack(alignment: .leading, spacing: Space.xl) {
            // one sentence: the total, or, while something has the focus, that thing
            Flap(text: focus?.line ?? model.shelfTotal, font: Face.said(Face.head), color: Ink.ink)
                .frame(height: 26, alignment: .leading)
                .padding(.leading, ShelfTile.inset)
                .probe("shelf.line", .line, scrolls: true)
            // every tile is one width and clusters sit edge to edge, so the whole shelf is one grid of columns
            Flow(spacing: 0, lineSpacing: 14) {
                ForEach(Array(groups.enumerated()), id: \.element.name) { g, group in
                    VStack(alignment: .leading, spacing: 7) {
                        Text(group.name).font(Face.heading).foregroundStyle(Ink.faint)
                            .lineLimit(1).fixedSize().padding(.leading, ShelfTile.inset)
                        Flow(spacing: 0, lineSpacing: 8) {
                            ForEach(group.items) { item in
                                ShelfTile(item: item, focused: model.shelfFocus == item.id)
                            }
                            if group.name == "waiting on you" || g == groups.count - 1 && !groups.contains(where: { $0.name == "waiting on you" }) {
                                AddTile()
                            }
                        }
                    }
                    .probe("shelf.cluster", .block, group: "shelf.clusters", scrolls: true)
                    .reveal(6 + g)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.leading, -ShelfTile.inset)      // the first icon of each row stands on the left edge, like everything above it
        .animation(Motion.spring(reduce), value: groups.map { $0.items.map(\.id) })
    }
}

struct ShelfTile: View {
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduce
    let item: ShelfItem
    let focused: Bool
    static let width: CGFloat = 70                         // one column width for the whole shelf
    static let inset: CGFloat = (width - 32) / 2           // from a tile's edge to its icon
    static let nameHeight: CGFloat = 27                    // room for a name on two lines, on every tile, so numbers line up

    var body: some View {
        let waiting = !item.action.isEmpty
        Button { model.shelfAct(item) } label: {
            VStack(spacing: 0) {
                SourceIcon(id: item.source, size: 32, name: item.name, muted: waiting)
                    .overlay(alignment: .topTrailing) {
                        // kept from last time and not readable now: one small dot, the colour the app uses when it needs you
                        if item.stale {
                            Circle().fill(Color(0xE5673A, 0xF07A4E)).frame(width: 7, height: 7)
                                .overlay(Circle().strokeBorder(Ink.paper, lineWidth: 1.5).padding(-1.5))
                                .offset(x: 2, y: -1)
                        }
                    }
                    // being read right now: a hairline sweeps under the icon. it does not pulse or breathe
                    .overlay(alignment: .bottom) { if item.live { Sweep().frame(width: 32, height: 1.5).offset(y: 4) } }
                    .offset(y: focused && !reduce ? -3 : 0)                 // the one in focus lifts
                    .scaleEffect(focused && !reduce ? 1.08 : 1)
                // the number sits right under the icon on every tile; the name, which may take two lines, comes last
                Group {
                    if waiting {
                        Text(item.action).font(.system(size: 10, weight: .semibold)).foregroundStyle(focused ? Ink.ink : Ink.soft)
                    } else if item.live {
                        Text("reading").font(.system(size: 10, weight: .semibold)).foregroundStyle(Ink.soft)
                    } else if let n = model.engine.fresh[item.source] {
                        // what the read that just ended brought in: shown for a moment, in the one accent, then the total again
                        Text("+" + ShelfTile.short(n)).font(.system(size: 10, weight: .bold)).monospacedDigit().foregroundStyle(Ink.ember)
                            .transition(.opacity)
                    } else {
                        Text(ShelfTile.short(item.rows)).font(.system(size: 10, weight: .semibold)).monospacedDigit()
                            .foregroundStyle(Ink.ink).contentTransition(.numericText(value: Double(item.rows)))
                            .animation(Motion.snap(reduce, 0.5), value: item.rows)
                            .transition(.opacity)
                    }
                }
                .lineLimit(1).fixedSize().probe("shelf.label", .line, scrolls: true)
                .padding(.top, 6)
                // always the name: an icon and a bare number is a puzzle. a long one wraps between its words
                Text(item.name).font(.system(size: 10, weight: .medium)).foregroundStyle(focused ? Ink.ink : Ink.soft)
                    .multilineTextAlignment(.center).lineLimit(2).lineSpacing(-1)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(width: ShelfTile.width - 6)
                    .probe("shelf.name", .text, scrolls: true)
                    .frame(height: ShelfTile.nameHeight, alignment: .top)
                    .padding(.top, 1)
            }
            .frame(width: ShelfTile.width)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(item.action.isEmpty ? "\(item.name), \(item.live ? "being read now" : "\(item.rows) things")" : "\(item.name): \(item.action)")
        .accessibilityAddTraits(.isButton)
        // a tile takes the line above only when the pointer is moved onto it: one that happens to be under a pointer
        // at rest when the window opens says nothing, and the line stays the total
        .onContinuousHover { phase in
            switch phase {
            case .active: if model.pointerMoved(NSEvent.mouseLocation) { model.shelfFocus = item.id }
            case .ended: if model.shelfFocus == item.id { model.shelfFocus = nil }; if model.shelfArmed == item.id { model.shelfArmed = nil }
            }
        }
        .animation(Motion.quick(reduce), value: focused)
        .animation(Motion.quick(reduce), value: item.rows)
        .probe("shelf.tile", .block, group: "shelf.tiles", scrolls: true)
        .accessibilityLabel(item.line)
    }

    /// 120,400 reads as 120k on the shelf; the exact number is in the line above when it has the focus.
    static func short(_ n: Int) -> String {
        switch n {
        case ..<10_000: return Words.count(n)
        case ..<1_000_000: return "\(Int((Double(n) / 1000).rounded()))k"
        default: return String(format: "%.1fm", Double(n) / 1_000_000)
        }
    }
}

/// The last tile: connect something that is not on the list.
struct AddTile: View {
    @Environment(AppModel.self) private var model
    @State private var hover = false
    var body: some View {
        Button { model.openAdd() } label: {
            VStack(spacing: 5) {
                ZStack {
                    RoundedRectangle(cornerRadius: Radius.row, style: .continuous).strokeBorder(hover ? Ink.soft : Ink.line, style: StrokeStyle(lineWidth: 1.5, dash: [3, 3]))
                    Text("+").font(.system(size: 17, weight: .medium)).foregroundStyle(hover ? Ink.ink : Ink.soft).offset(y: -1)
                }
                .frame(width: 28, height: 28).frame(width: 32, height: 32)
                Text("add").font(.system(size: 10, weight: .semibold)).foregroundStyle(Ink.soft).lineLimit(1).fixedSize().padding(.top, 1)
                Text("a source").font(.system(size: 10, weight: .medium)).foregroundStyle(Ink.faint).lineLimit(1).fixedSize().padding(.top, -4)
                    .frame(height: ShelfTile.nameHeight, alignment: .top)
            }
            .frame(width: ShelfTile.width)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
        .help("connect another app or service")
        .probe("shelf.add", .block, group: "shelf.tiles", scrolls: true)
    }
}

/// Where the pointer was resting, and whether it has left that spot.
struct AppModelPointer {
    var rest = CGPoint(x: 10, y: 10)
    func moved(_ now: CGPoint) -> Bool { abs(now.x - rest.x) > 3 || abs(now.y - rest.y) > 3 }
}

extension AppModel {
    struct ShelfGroup: Equatable { let name: String; var items: [ShelfItem] }

    /// "170,000 things since june 2012, from 12 sources"
    var shelfTotal: String {
        let e = engine
        guard e.totalRows > 0 else { return "nothing read yet." }
        let since = e.spans.values.map(\.first).filter { $0 > "1990" }.min()
        return "\(Words.count(e.totalRows)) things" + (since.map { " since " + Words.monthLong(String($0.prefix(7))) } ?? "")
            + ", from \(e.readCount) source\(e.readCount == 1 ? "" : "s")."      // what is being read right now is said in the top bar, not here
    }

    /// The shelf: what has been read, in three clusters, and at the end what is waiting on you.
    /// A source that is simply not on this mac is left off: there is nothing to do about it here.
    var shelf: [ShelfGroup] {
        let e = engine
        var read: [String: [ShelfItem]] = [:]
        var waiting: [ShelfItem] = []
        var locked: [String] = []          // names of the sources full disk access would unlock
        var lockedFix = ""
        for id in e.order {
            let info = Catalog.info(id)
            let state = e.state(id)
            let rows = state == .reading ? (e.live[id] ?? 0) : state.rows
            let why: String? = { switch state { case .skipped(let w), .kept(_, let w): return w; default: return nil } }()
            let blocked = why.flatMap { info.via == .archive ? nil : Blocked($0, info) }
            let onShelf = rows > 0 || state == .reading
            if onShelf {
                var line = "\(info.name)  ·  \(Words.count(rows)) \(info.noun)"
                if let s = e.spans[id] { line += "  ·  since \(Words.monthYear(s.first))" }
                var stale = false
                if case .kept = state, let b = blocked, !b.notHere, !(b.fix == .settings && access) {
                    line += "  ·  kept from last time. " + b.line
                    stale = true
                }
                let cluster = info.group == "messages" ? "people" : (info.group == "agents" ? "work" : "saved")
                // a source is on the shelf once. when it cannot be read now it keeps its tile, with a dot, and a click fixes it
                read[cluster, default: []].append(ShelfItem(id: id, name: info.name, source: id, rows: rows, live: state == .reading, line: line,
                                                            kind: stale ? "fix:" + id : "open", stale: stale))
            }
            guard let b = blocked, !b.notHere else { continue }
            if b.fix == .settings {            // one cause, one item, however many sources it holds back
                // only when macos really keeps this app out. a note from an older read that says so is not proof:
                // with access on, the source is read again (see `heal`) and nobody is asked to switch on what is on
                if !access {
                    locked.append(info.name)
                    if lockedFix.isEmpty { lockedFix = id }
                }
                continue
            }
            if onShelf { continue }
            let action: String
            switch b.fix {
            case .settings: action = "switch on"
            case .automation: action = "allow it"
            case .signIn: action = "sign in"
            case .browser: action = b.fixLabel
            case .daily: action = "read now"
            case nil: action = "look"
            }
            waiting.append(ShelfItem(id: "wait:" + id, name: info.name, source: id, action: action, line: "\(info.name)  ·  \(b.line)", kind: "fix:" + id))
        }
        if !locked.isEmpty {
            // it was on before: a rebuilt copy of the app loses it while settings still shows the switch on
            let how = saved.hadDisk ? "macos has it off for this copy of context: switch it off and on again" : "switch on"
            waiting.insert(ShelfItem(id: "wait:disk", name: "full disk access", source: "_key", action: saved.hadDisk ? "switch again" : "switch on",
                                     line: "full disk access  ·  \(how)  ·  unlocks " + locked.joined(separator: ", "), kind: "fix:" + lockedFix), at: 0)
        }
        // exports: one tile per service that needs them, not one per source it feeds
        for s in requests.services {
            let action: String
            switch s.state {
            case .needsYou: action = s.asksFor == "password" ? "enter password" : (s.asksFor == "code" ? "enter code" : "open tab")
            case .idle: action = shelfArmed == "export:" + s.id ? "ask now" : "ask for it"
            case .failed: action = shelfArmed == "export:" + s.id ? "ask now" : "try again"
            default: continue
            }
            let (_, line) = requests.words(s)
            waiting.append(ShelfItem(id: "export:" + s.id, name: s.name + " export", source: s.mark.id, action: action,
                                     line: shelfArmed == "export:" + s.id ? "ask \(s.name) for your archive? it may email you. press again to ask."
                                         : "\(s.name) export  ·  " + (line.isEmpty || s.state == .idle ? "not asked for yet." : line), kind: "export:" + s.id))
        }
        if bridge == false {
            waiting.append(ShelfItem(id: "bridge", name: "extension", source: "_window", action: "load it",
                                     line: "browser extension  ·  not connected. slack, drive and x bookmarks come through it.", kind: "sources"))
        }
        if let p = plan, !p.ready {
            waiting.append(ShelfItem(id: "plan", name: "your ai", source: "_", action: "sign in",
                                     line: "your ai  ·  no plan is signed in, so answers are off. " + p.line, kind: "sources"))
        }
        // the biggest first in each cluster, so a source with four rows is not in the middle of the row
        var out = ["people", "work", "saved"].compactMap { n in read[n].map { ShelfGroup(name: n, items: $0.sorted { $0.rows > $1.rows }) } }
        if !waiting.isEmpty { out.append(ShelfGroup(name: "waiting on you", items: waiting)) }
        if out.isEmpty { out = [ShelfGroup(name: "sources", items: [])] }
        return out
    }

    /// A click, or return with the focus on it: the one thing that item needs, or its detail.
    func shelfAct(_ item: ShelfItem) {
        if item.kind.hasPrefix("fix:") {
            let id = String(item.kind.dropFirst(4))
            let why: String? = { switch engine.state(id) { case .skipped(let w), .kept(_, let w): return w; default: return nil } }()
            if let why { let b = Blocked(why, Catalog.info(id)); if b.fix != nil { b.run(); return } }
        }
        if item.kind.hasPrefix("export:") {
            let id = String(item.kind.dropFirst(7))
            if let s = requests.service(id), s.state != .needsYou {
                // asking a site for an archive goes out from this mac and may bring an email: the first press only says so
                guard shelfArmed == item.id else { shelfArmed = item.id; return }
                shelfArmed = nil
                requests.request(id)
                return
            }
            let name = (requests.browser?.name ?? "").lowercased()
            NSWorkspace.shared.runningApplications.first { ($0.localizedName ?? "").lowercased() == name }?.activate()
            return
        }
        tab = .sources
    }

    /// True once the pointer has left the spot it was resting on when home came up.
    func pointerMoved(_ now: CGPoint) -> Bool {
        let p = AppModelPointer(rest: restPointer)
        if p.moved(now) { restPointer = CGPoint(x: -9999, y: -9999); return true }
        return false
    }

    /// Sources a past read marked as locked out, while macos in fact lets this app in.
    var staleUnlocked: [String] {
        guard access else { return [] }
        return engine.order.filter { id in
            switch engine.state(id) {
            case .skipped(let w), .kept(_, let w): return Catalog.info(id).via != .archive && Blocked(w, Catalog.info(id)).fix == .settings
            default: return false
            }
        }
    }

    /// Reads those again, each once per stretch of access being on. Runs at launch, when the app comes forward and each minute.
    func heal() {
        let was = access
        if !Engine.debug {
            access = Access.fullDisk
            if !engine.syncing { engine.loadStatus() }       // another refresh may have rewritten it since this app last looked
        }
        if access, !was { healed = [] }
        guard !Engine.debug, saved.onboarded, !engine.syncing else { return }
        for id in staleUnlocked where !healed.contains(id) {
            healed.insert(id)
            engine.readRun.remove(id)
            engine.read(id)
        }
    }

    func shelfMove(_ by: Int) {
        let all = shelf.flatMap(\.items)
        guard !all.isEmpty else { return }
        let i = all.firstIndex { $0.id == shelfFocus } ?? (by > 0 ? -1 : all.count)
        shelfFocus = all[max(0, min(all.count - 1, i + by))].id
    }
}

/// A short bright stretch running along a hairline, left to right, for something being read at this moment.
struct Sweep: View {
    @Environment(\.accessibilityReduceMotion) private var reduce
    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 30, paused: reduce || Probe.on)) { t in
            GeometryReader { g in
                let phase = reduce || Probe.on ? 0.3 : t.date.timeIntervalSinceReferenceDate.truncatingRemainder(dividingBy: 1.6) / 1.6
                ZStack(alignment: .leading) {
                    Capsule().fill(Ink.ink.opacity(0.10))
                    Capsule().fill(Ink.ember).frame(width: g.size.width * 0.4).offset(x: (g.size.width * 1.4) * phase - g.size.width * 0.4)
                }
                .clipShape(Capsule())
            }
        }
    }
}
