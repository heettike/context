import Foundation
import Observation
import SwiftUI

/// The writing of the wiki: what exists, what it would cost to write the rest, and the run itself. Read from
/// `wiki --status` and `wiki --estimate`; `wiki --build` is the run, told in lines `@{"src":"wiki","rows":n,"of":m,"label":…}`.
/// Stopping it ends the process: every page is written whole or not at all, and the next run carries on from there.
/// Settings and the about-you page show this one object, so they never disagree.
@Observable final class WikiBuild {
    struct Status: Equatable {
        var built = false
        var pages: [String: Int] = [:]      // by kind
        var words = 0
        var calls = 0
        var secs = 0
        var total: Int { pages.values.reduce(0, +) }
    }
    struct Estimate: Equatable {
        var toWrite: [String: Int] = [:]    // by kind, as the engine names them
        var calls = 0
        var hours = 0.0
        var plan = ""
        var pages: Int { toWrite.values.reduce(0, +) }
    }
    struct Progress: Equatable { var n: Int; var of: Int; var kind: String }

    var status: Status?
    var estimate: Estimate?
    var estimating = false
    var running = false
    var paused = false                  // the owner stopped it: what is written stays
    var progress: Progress?
    var failed = ""                     // the engine's last line about a page it could not write
    @ObservationIgnored weak var engine: Engine?
    @ObservationIgnored var onDone: (() -> Void)?
    @ObservationIgnored var onProgress: (() -> Void)?      // every few pages, so the list of pages can be read again
    @ObservationIgnored private var process: Process?

    init() {}

    static func status(_ d: [String: Any]) -> Status {
        let spent = d["spent"] as? [String: Any] ?? [:]
        var pages: [String: Int] = [:]
        for (k, v) in d["pages"] as? [String: Any] ?? [:] { if let n = (v as? NSNumber)?.intValue, n > 0 { pages[k] = n } }
        return Status(built: d["built"] as? Bool ?? false, pages: pages, words: (d["words"] as? NSNumber)?.intValue ?? 0,
                      calls: (spent["calls"] as? NSNumber)?.intValue ?? 0, secs: (spent["secs"] as? NSNumber)?.intValue ?? 0)
    }

    static func estimate(_ d: [String: Any]) -> Estimate? {
        guard let e = d["estimate"] as? [String: Any] ?? (d["pages_to_write"] != nil ? d : nil) else { return nil }
        var to: [String: Int] = [:]
        for (k, v) in e["pages_to_write"] as? [String: Any] ?? [:] { if let n = (v as? NSNumber)?.intValue, n > 0 { to[k.lowercased()] = n } }
        return Estimate(toWrite: to, calls: (e["calls_total"] as? NSNumber)?.intValue ?? 0, hours: (e["hours_at_5_workers"] as? NSNumber)?.doubleValue ?? 0,
                        plan: (e["plan"] as? String ?? "").lowercased())
    }

    /// `@{"src":"wiki","rows":30,"of":250,"label":"people: …"}`. The label names a page; only its kind is kept.
    static func progress(_ line: String) -> (progress: Progress?, failed: String)? {
        guard line.hasPrefix("@"), let d = (try? JSONSerialization.jsonObject(with: Data(line.dropFirst().utf8))) as? [String: Any], d["src"] as? String == "wiki" else { return nil }
        if let phase = d["phase"] as? String { return (nil, phase.hasPrefix("failed") ? "a page could not be written and will be tried again." : "") }
        guard let of = (d["of"] as? NSNumber)?.intValue, of > 0 else { return nil }
        let label = (d["label"] as? String ?? "").lowercased()
        let kind = label.split(separator: ":").first.map { $0.trimmingCharacters(in: .whitespaces) } ?? ""
        return (Progress(n: (d["rows"] as? NSNumber)?.intValue ?? 0, of: of, kind: kind), "")
    }

    func load() {
        engine?.json(["wiki", "--status"], timeout: 60) { [weak self] obj in if let obj { self?.status = WikiBuild.status(obj) } }
    }

    /// What writing the rest would take, before anything is spent. It reads the archive, so it takes a moment.
    func loadEstimate() {
        guard !estimating, let engine else { return }
        estimating = true
        engine.json(["wiki", "--estimate"], timeout: 600) { [weak self] obj in
            self?.estimating = false
            if let obj, let e = WikiBuild.estimate(obj) { self?.estimate = e }
        }
    }

    func start() {
        guard !running, let engine else { return }
        running = true
        paused = false
        failed = ""
        progress = nil
        process = engine.stream(["wiki", "--build"], line: { [weak self] line in
            guard let self, let got = WikiBuild.progress(line) else { return }
            if let p = got.progress {
                if p.n != self.progress?.n, p.n % 4 == 0 { self.onProgress?() }
                self.progress = p
            }
            if !got.failed.isEmpty { self.failed = got.failed }
        }, done: { [weak self] in
            guard let self else { return }
            self.running = false
            self.process = nil
            self.estimate = nil             // what is left has changed
            self.engine?.json(["wiki", "--status"], timeout: 60) { [weak self] obj in
                if let obj { self?.status = WikiBuild.status(obj) }
                self?.onDone?()
            }
        })
        if process == nil { running = false }
    }

    func pause() {
        guard running else { return }
        paused = true
        process?.terminate()
    }

    // MARK: in words

    /// "people", "the front page": a kind as it is said in a sentence.
    static func kindWord(_ k: String, _ n: Int = 2) -> String {
        switch k {
        case "front": return "the front page"
        case "people": return n == 1 ? "person" : "people"
        case "projects": return n == 1 ? "project" : "projects"
        case "years": return n == 1 ? "year" : "years"
        case "quarters": return n == 1 ? "quarter" : "quarters"
        case "themes": return n == 1 ? "theme" : "themes"
        default: return k
        }
    }
    static let order = ["front", "people", "projects", "years", "quarters", "themes"]

    static func list(_ by: [String: Int]) -> String {
        // "people, the closest" and "people, the rest" are one kind to a reader
        var merged: [String: Int] = [:]
        for (k, n) in by { merged[k.split(separator: ",").first.map(String.init) ?? k, default: 0] += n }
        let keys = order.filter { merged[$0] != nil } + merged.keys.filter { !order.contains($0) }.sorted()
        return keys.map { $0 == "front" ? kindWord($0) : "\(Words.count(merged[$0]!)) \(kindWord($0, merged[$0]!))" }.joined(separator: ", ")
    }

    /// "22 pages: the front page, 10 people, 5 projects, 2 years, 4 themes · 35,000 words"
    var exists: String {
        guard let s = status, s.total > 0 else { return status == nil ? "" : "nothing is written yet." }
        return "\(Words.count(s.total)) page\(s.total == 1 ? "" : "s") written: \(WikiBuild.list(s.pages))  ·  \(Words.count(s.words)) words."
    }

    /// "spent so far: 160 calls, 35 min of model time"
    var spent: String {
        guard let s = status, s.calls > 0 else { return "" }
        return "spent so far: \(Words.count(s.calls)) call\(s.calls == 1 ? "" : "s"), \(WikiBuild.time(Double(s.secs))) of model time."
    }

    static func time(_ secs: Double) -> String {
        secs < 90 ? "\(Int(secs)) s" : (secs < 5400 ? "\(Int((secs / 60).rounded())) min" : String(format: "%.1f hours", secs / 3600))
    }

    /// What the rest would cost, as a sentence, once the engine has worked it out.
    var cost: String {
        guard let e = estimate else { return "" }
        if e.pages == 0 { return "nothing is left to write: every page is up to date." }
        let long = e.hours * 3600
        return "\(Words.count(e.pages)) page\(e.pages == 1 ? " is" : "s are") missing or out of date: \(WikiBuild.list(e.toWrite)). writing \(e.pages == 1 ? "it" : "them") takes "
            + (long >= 60 ? "about \(WikiBuild.time(long))" : "a few minutes") + " on \(e.plan.isEmpty ? "your own plan" : e.plan) (\(Words.count(e.calls)) calls). it costs nothing extra: it uses part of your plan's allowance."
    }

    /// "writing people: 30 of 250"
    var doing: String {
        guard running else { return paused ? "paused. what is written stays; it carries on from there." : "" }
        guard let p = progress else { return "starting: reading what there is to write about." }
        let what = p.kind.isEmpty || p.kind == "reading" ? "reading" : "writing " + WikiBuild.kindWord(p.kind)
        return "\(what): \(Words.count(p.n)) of \(Words.count(p.of))"
    }

    var pill: (String, Tone) {
        if running { return ("writing", .good) }
        if paused { return ("paused", .quiet) }
        guard let s = status else { return ("checking", .quiet) }
        return s.total > 0 ? ("\(Words.count(s.total)) pages", .good) : ("not written", .quiet)
    }
}

/// The state of the wiki's writing, the same in settings and on the about-you page: what exists, what it is doing,
/// what the rest would cost before it starts, and the one button for where it stands.
struct WikiBuildBlock: View {
    @Environment(AppModel.self) private var model
    var probeName = "setting"

    var body: some View {
        let b = model.wikiBuild
        VStack(alignment: .leading, spacing: 6) {
            if !b.exists.isEmpty { SetText.about(b.exists) }
            if b.running || b.paused {
                SetText.about(b.doing, Ink.ink)
                if b.running, let p = b.progress, p.of > 0 { Meter(part: Double(p.n) / Double(p.of)).padding(.vertical, 2) }
                if !b.failed.isEmpty { SetText.about(b.failed) }
            }
            if !b.running {
                if b.estimating { SetText.about("working out what it would take. this reads the archive and spends nothing.") }
                else if !b.cost.isEmpty { SetText.about(b.cost, Ink.ink) }
            }
            if !b.spent.isEmpty { SetText.about(b.spent) }
            HStack(spacing: 14) {
                if b.running {
                    SetButton(word: "pause") { b.pause() }
                } else if let e = b.estimate {
                    if e.pages > 0 {
                        SetButton(word: b.paused || (b.status?.total ?? 0) > 0 ? "carry on writing" : "start writing") { b.start() }
                        Button("not now") { b.estimate = nil }.buttonStyle(QuietButton(size: 12)).fixedSize()
                    }
                } else if !b.estimating {
                    SetButton(word: (b.status?.total ?? 0) > 0 ? "see what the rest would cost" : "see what it would cost") { b.loadEstimate() }
                }
            }
            .padding(.top, 4)
        }
        .probe("wiki.build", .block, scrolls: true)
    }
}

/// A thin bar: how far along.
struct Meter: View {
    let part: Double
    var body: some View {
        GeometryReader { g in
            ZStack(alignment: .leading) {
                Capsule().fill(Ink.line)
                Capsule().fill(Ink.ember).frame(width: max(4, g.size.width * min(1, max(0, part))))
            }
        }
        .frame(height: 3).frame(maxWidth: 320)
        .accessibilityLabel("\(Int(part * 100)) percent")
    }
}
