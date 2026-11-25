import SwiftUI

/// Something that is running, or has finished, away from where the owner is looking: an answer being read, a question
/// waiting behind it, a source being worked out.
struct Job: Identifiable, Equatable {
    enum State: Equatable { case running, waiting, done }
    enum What: Equatable { case add, sync }
    let id: String
    let what: What
    var title: String
    var line: String
    var since: Date?
    var state: State
}

extension AppModel {
    /// What runs outside the chats and cannot be seen from here: a source being worked out, and, with the sidebar
    /// folded, a read of the archive. A chat being answered is not here: its row in the list turns, then shows a dot.
    var jobs: [Job] {
        guard saved.onboarded else { return [] }
        var out: [Job] = []
        if let a = adding, addHidden {
            let name = a.picked?.name ?? "a source"
            switch a.stage {
            case .working: out.append(Job(id: "add", what: .add, title: "adding \(name)", line: a.phases.last ?? "working out how to read it", since: a.since, state: .running))
            case .result(let r):
                let said = r.state == "ready" ? "ready to add" : (r.state == "needs_you" ? "needs something from you" : "cannot be read yet")
                out.append(Job(id: "add", what: .add, title: name, line: said, since: nil, state: .done))
            default: break
            }
        }
        return out
    }

    /// A click on a pill: go to the thing.
    func open(_ job: Job) {
        switch job.what {
        case .add: addHidden = false
        case .sync: go(.sources)
        }
    }

    /// The small x: stop what is running, or put away what is done.
    func dismiss(_ job: Job) {
        switch job.what {
        case .add: closeAdd()
        case .sync: break
        }
    }
}

/// The corner of the window: up to three pills, then how many more.
struct JobPills: View {
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduce

    var body: some View {
        let jobs = model.jobs
        VStack(alignment: .trailing, spacing: 8) {
            if jobs.count > 3 {
                Text("+\(jobs.count - 3)").font(.system(size: 12, weight: .semibold)).monospacedDigit().foregroundStyle(Ink.soft)
                    .padding(.horizontal, 9).frame(height: 22)
                    .background(Ink.wash, in: Capsule())
                    .probe("job.more", .line)
            }
            ForEach(jobs.prefix(3)) { job in
                JobPill(job: job)
                    .transition(reduce ? .opacity : .opacity.combined(with: .offset(y: 10)))
            }
        }
        .animation(Motion.snap(reduce, 0.3), value: jobs.map(\.id))
    }
}

struct JobPill: View {
    @Environment(AppModel.self) private var model
    let job: Job
    @State private var hover = false

    var body: some View {
        HStack(alignment: .center, spacing: 10) {
            Group {
                switch job.state {
                case .running: Mark(source: Catalog.neutral, mood: .reading, size: 8)
                case .waiting: Circle().strokeBorder(Ink.faint, lineWidth: 1.5).frame(width: 8, height: 8)
                case .done: Circle().fill(LogoMark.dot).frame(width: 8, height: 8)
                }
            }
            .frame(width: 10)
            VStack(alignment: .leading, spacing: 2) {
                Text(JobPill.short(job.title)).font(.system(size: 13, weight: .semibold)).foregroundStyle(Ink.ink).lineLimit(1)
                HStack(spacing: 6) {
                    Text(job.line).font(.system(size: 12)).foregroundStyle(Ink.soft).lineLimit(1).truncationMode(.tail)
                    if let since = job.since {
                        TimelineView(.periodic(from: since, by: 1)) { t in
                            Text("\(max(0, Int(t.date.timeIntervalSince(since)))) s").font(.system(size: 12, weight: .medium)).monospacedDigit()
                                .foregroundStyle(Ink.faint).fixedSize()
                        }
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            Button { model.dismiss(job) } label: {
                Image(systemName: "xmark").font(.system(size: 9, weight: .bold)).foregroundStyle(hover ? Ink.ink : Ink.faint)
                    .frame(width: 20, height: 20).contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .help(job.state == .running ? "stop it" : "put it away")
        }
        .padding(.leading, 13).padding(.trailing, 7).frame(width: 290, height: 46)
        .background(Ink.paper, in: RoundedRectangle(cornerRadius: Radius.card, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: Radius.card, style: .continuous).strokeBorder(Ink.line, lineWidth: 1))
        .shadow(color: .black.opacity(0.10), radius: 14, y: 5)
        .contentShape(Rectangle())
        .onTapGesture { model.open(job) }
        .onHover { hover = $0 }
        .help(job.title)
        .probe("job.pill", .block, group: "job.pills")
    }

    /// The first words of a question, cut at a word.
    static func short(_ s: String, max: Int = 34) -> String {
        guard s.count > max else { return s }
        var out = ""
        for w in s.split(separator: " ") {
            if out.count + w.count + 1 > max - 1 { break }
            out += (out.isEmpty ? "" : " ") + w
        }
        return (out.isEmpty ? String(s.prefix(max - 1)) : out) + "…"
    }
}

// MARK: a job that has left the window shows in the menu bar

extension AppModel {
    /// What is running where the owner cannot see it, in a few words, or nil. While the main window is in front the window
    /// itself says it (a row that turns, the pill in the corner, the sources line); once the window is closed or
    /// behind other apps, the menu-bar mark takes over.
    func awayWork(windowSeen: Bool, at now: Date = Date()) -> String? {
        guard saved.onboarded, !windowSeen else { return nil }
        if let a = adding, a.stage == .working { return "adding \(a.picked?.name ?? "a source")" }
        if !ask.busy.isEmpty { return ask.busy.count == 1 ? "answering a question" : "answering \(ask.busy.count) questions" }
        if profile.rebuilding { return "reading your history through" }
        return engine.doing(at: now)
    }
}

extension LogoMark {
    /// The menu-bar mark while work goes on out of sight: the same brackets, and the dot between them swells and
    /// settles over eight steps, like something breathing. A template, like the resting mark.
    static let busyRadii: [CGFloat] = [2.0, 1.6, 1.2, 0.9, 1.2, 1.6, 2.0, 2.4]
    static func menuBarBusyImage(step: Int) -> NSImage {
        let image = NSImage(size: NSSize(width: 18, height: 18), flipped: false) { rect in
            drawMenuBarMark(in: rect, ink: .black, dot: .black, dotRadius: busyRadii[((step % 8) + 8) % 8])
            return true
        }
        image.isTemplate = true
        return image
    }
}

extension AppDelegate {
    /// One soft pulse of the menu-bar mark: down to a third and back in 0.9 s. Nothing with Reduce Motion.
    func pulseMark() {
        guard let button = statusItem?.button, !NSWorkspace.shared.accessibilityDisplayShouldReduceMotion else { return }
        button.wantsLayer = true
        let a = CAKeyframeAnimation(keyPath: "opacity")
        a.values = [1, 0.35, 1]
        a.keyTimes = [0, 0.45, 1]
        a.duration = 0.9
        a.timingFunction = CAMediaTimingFunction(name: .easeInEaseOut)
        button.layer?.add(a, forKey: "landed")
    }

    /// Called once a second. No window is made and nothing flies across the screen: the status item, which is
    /// already there, changes its own picture and its tooltip, and changes back when the work lands.
    func reconcileMenuBar() {
        guard !Engine.debug, let button = statusItem?.button else { return }
        let seen = window.isVisible && window.isKeyWindow && NSApp.isActive
        let said = model.awayWork(windowSeen: seen) ?? ""
        guard said != busySaid else { return }
        // an answer that was being written out of sight has landed: the mark pulses once, softly
        if said.isEmpty, busySaid.hasPrefix("answering") { pulseMark() }
        busySaid = said
        busyTimer?.invalidate()
        busyTimer = nil
        if said.isEmpty {
            button.image = attention ? LogoMark.menuBarAttentionImage() : LogoMark.menuBarImage()
            button.toolTip = "context"
            return
        }
        button.toolTip = "context  ·  " + said
        button.image = LogoMark.menuBarBusyImage(step: busyStep)
        if NSWorkspace.shared.accessibilityDisplayShouldReduceMotion { return }
        busyTimer = Timer.scheduledTimer(withTimeInterval: 0.18, repeats: true) { [weak self] _ in
            guard let self, let button = self.statusItem?.button else { return }
            self.busyStep += 1
            button.image = LogoMark.menuBarBusyImage(step: self.busyStep)
        }
    }
}
