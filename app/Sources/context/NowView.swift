import SwiftUI

/// The nudge itself: a sentence said to you, the reason under it, and what you can do about it.
struct NudgeBlock: View {
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduce
    let nudge: Nudge?
    var size: CGFloat = 30
    var compact = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if let n = nudge {
                VStack(alignment: .leading, spacing: compact ? 6 : 10) {
                    Text(n.text)
                        .font(.system(size: size, weight: .regular, design: .serif)).lineSpacing(size * 0.12)
                        .foregroundStyle(Ink.ink)
                        .fixedSize(horizontal: false, vertical: true)
                        .probe("nudge.text", .text, group: "nudge", scrolls: true)
                    if !n.detail.isEmpty {
                        Text(n.detail).font(.system(size: compact ? 12 : 14, weight: .medium)).foregroundStyle(Ink.soft).lineSpacing(2)
                            .fixedSize(horizontal: false, vertical: true)
                            .probe("nudge.detail", .text, group: "nudge", scrolls: true)
                    }
                    HStack(spacing: compact ? 14 : 20) {
                        do {
                            act(n.loop != nil ? "done" : "got it", "return") { model.coach.answer(.ok, n) }
                            act(n.loop != nil ? "not real" : "not useful", "x") { model.coach.answer(.no, n) }
                            act("tomorrow", "s") { model.coach.answer(.later, n) }
                            if !n.query.isEmpty { act("show me", "o") { model.show(n) } }
                        }
                    }
                    .padding(.top, compact ? 4 : 8)
                }
                .id(n.id)
                .transition(reduce ? .opacity : .asymmetric(
                    insertion: .opacity.combined(with: .offset(y: 12)),
                    removal: .opacity.combined(with: .offset(y: -10)).animation(.easeIn(duration: 0.12))))
            } else {
                Text("nothing to flag.")
                    .font(.system(size: size, weight: .regular, design: .serif)).foregroundStyle(Ink.faint)
                    .transition(.opacity)
            }
        }
        .animation(Motion.spring(reduce), value: nudge?.id)
    }

    private func act(_ word: String, _ key: String, _ run: @escaping () -> Void) -> some View {
        Button(action: run) {
            HStack(spacing: 6) { Text(word); if !compact { KeyHint(key: key) } }
        }
        .buttonStyle(QuietButton(size: 13))
    }
}

/// The optional pill: one line that floats above everything, bottom right.
struct PillView: View {
    let nudge: Nudge
    let open: () -> Void
    let dismiss: () -> Void
    @State private var hover = false

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Circle().fill(Ink.paper).frame(width: 6, height: 6).offset(y: -2)
            Text(nudge.text)
                .font(.system(size: 14, weight: .regular, design: .serif)).lineSpacing(2)
                .foregroundStyle(Ink.paper).lineLimit(3)
                .fixedSize(horizontal: false, vertical: true)
            if hover {
                Button(action: dismiss) { Text("got it").font(.system(size: 12, weight: .semibold)).foregroundStyle(Ink.paper.opacity(0.6)) }
                    .buttonStyle(.plain).fixedSize()
            }
        }
        .padding(.horizontal, 16).padding(.vertical, 11)
        .frame(width: 340, alignment: .leading)
        .background(Ink.ink, in: RoundedRectangle(cornerRadius: Radius.field, style: .continuous))
        .contentShape(Rectangle())
        .onTapGesture(perform: open)
        .onHover { hover = $0 }
    }
}
