import Security
import AppKit
import Foundation
import Observation

enum SourceState: Equatable {
    case idle
    case waiting
    case reading
    case done(rows: Int, secs: Double)
    /// could not be read this time; these are the rows from the last good read, and why.
    case kept(rows: Int, why: String)
    case skipped(String)

    var finished: Bool {
        switch self {
        case .done, .skipped, .kept: return true
        default: return false
        }
    }
    var rows: Int {
        switch self {
        case .done(let r, _), .kept(let r, _): return r
        default: return 0
        }
    }
}

struct DateSpan: Equatable {
    var first: String
    var last: String
    mutating func take(_ d: String) {
        if d < first { first = d }
        if d > last { last = d }
    }
}

/// The three refresh tiers, as the engine reports them.
struct Schedule: Equatable {
    struct Tier: Equatable { var last: Double; var nextIn: Double; var due: Bool; var sources: [String]; var results: [String: Result] }
    struct Result: Equatable { var state: String; var detail: String }
    struct Export: Equatable { var every: String; var last: Double; var nextIn: Double? }
    var fast: Tier
    var daily: Tier
    var weekly: [String: Export]
    var at = Date()

    init?(_ d: [String: Any]) {
        func tier(_ k: String) -> Tier? {
            guard let t = d[k] as? [String: Any] else { return nil }
            var results: [String: Result] = [:]
            for (name, v) in (t["results"] as? [String: Any]) ?? [:] {
                if let r = v as? [String: Any] { results[name] = Result(state: r["state"] as? String ?? "", detail: (r["detail"] as? String ?? "").lowercased()) }
            }
            return Tier(last: (t["last"] as? NSNumber)?.doubleValue ?? 0, nextIn: (t["next_in"] as? NSNumber)?.doubleValue ?? 0,
                        due: t["due"] as? Bool ?? false, sources: t["sources"] as? [String] ?? [], results: results)
        }
        guard let f = tier("fast"), let dl = tier("daily") else { return nil }
        fast = f
        daily = dl
        weekly = [:]
        for (id, v) in (d["weekly"] as? [String: Any]) ?? [:] {
            guard let w = v as? [String: Any] else { continue }
            weekly[id] = Export(every: w["every"] as? String ?? "weekly", last: (w["last"] as? NSNumber)?.doubleValue ?? 0,
                                nextIn: (w["next_in"] as? NSNumber)?.doubleValue)
        }
    }

    /// "every 15 min · 6 min ago", "daily · next in 14 h"
    static func words(_ every: String, _ t: Tier, since: Date) -> String {
        let left = max(0, t.nextIn - Date().timeIntervalSince(since))
        if t.last <= 0 { return every + "  ·  not run yet" }
        if every.hasPrefix("every") { return every + "  ·  " + Words.since(Date(timeIntervalSince1970: t.last)) }
        return every + "  ·  " + (left < 60 ? "due now" : "next in " + (left >= 3600 ? "\(Int(left / 3600)) h" : "\(Int(left / 60)) min"))
    }
}

/// One progress line from the collector: how far, where in time, what it is reading.
struct Sample: Equatable {
    var rows: Int
    var at: String       // "2024-03", or empty
    var label: String    // a thread, a title
    var phase: String    // set when the source is in a named stage
}

/// Finds the Python engine, runs `python3 -m ctx collect`, and follows it line by line.
@Observable final class Engine {
    let repo: URL?
    var fresh: [String: Int] = [:]      // rows that arrived in the read that just ended, by source, for a few seconds
    @ObservationIgnored lazy var client = EngineClient(self)
    let home: URL

    var order: [String] = Catalog.order
    /// what each source held after the last read, shown while it waits for this one.
    var previous: [String: Int] = [:]
    /// the sources that get a setup step. fixed while a sync runs so the step you are on does not move.
    var stepOrder: [String] = Catalog.order.filter { Catalog.isStep($0, rows: 0) }
    private func refreshSteps() { stepOrder = order.filter { Catalog.isStep($0, rows: state($0).rows) } }
    var states: [String: SourceState] = [:]
    var live: [String: Int] = [:]
    var spans: [String: DateSpan] = [:]
    var current: String?
    var syncing = false
    var lastSync: Date?
    var failure: String?
    var onFinish: (() -> Void)?

    // setup reads one source at a time, each with its own process
    var log: [String: [Sample]] = [:]          // every progress line of this run, thinned, so a step can replay a read it missed
    var running: Set<String> = []
    var landed: Set<String> = []               // sources whose last line has come in the run in progress
    var scanned: [String: Int] = [:]           // "found 12,345 emails": what a slow source said it has to go through
    var phaseSince: [String: Date] = [:]       // when a source last said what stage it is in
    var readRun: Set<String> = []              // asked for in this setup run
    var onRead: ((String) -> Void)?
    @ObservationIgnored private var queued: [String] = []
    @ObservationIgnored private var readers: [String: Process] = [:]
    static let maxReads = 2

    // what the running refresh is doing right now, for the one small indicator and the sources heading
    var heard: String?                         // the source, or "understand", the last progress line was about
    var heardAt = Date.distantPast
    var readThrough: (n: Int, of: Int)?        // the read-through, when that is what is running

    /// What is really being read at this moment, in a few words, or nil. A refresh that is only waiting on a slow
    /// app says nothing: the indicator is for work, not for a process that happens to be alive.
    func doing(at now: Date = Date()) -> String? {
        let live = order.filter { states[$0] == .reading }
        if !live.isEmpty {
            let first = Catalog.info(live[0]).name
            return "reading " + (live.count == 1 ? first : "\(first) and \(live.count - 1) more")
        }
        guard syncing, let heard, now.timeIntervalSince(heardAt) < 20 else { return nil }
        if heard == "understand" { return readThrough.map { "read-through \($0.n) of \($0.of)" } ?? "read-through" }
        return "reading " + Catalog.info(heard).name
    }

    /// The same, in a sentence, for the pointer resting on the indicator.
    func doingDetail(at now: Date = Date()) -> String {
        let live = order.filter { states[$0] == .reading }.map { Catalog.info($0).name }
        if !live.isEmpty { return "reading " + live.joined(separator: ", ") + " now." }
        if heard == "understand", let r = readThrough { return "the read-through: \(r.n) of \(r.of) conversations and projects read, on your own plan." }
        if let d = doing(at: now) { return d + (ticking ? ", as part of the regular refresh." : ".") }
        return ""
    }

    var schedule: Schedule?
    var ticking = false                        // the run in progress is a refresh, not the first full read
    @ObservationIgnored private var process: Process?
    @ObservationIgnored private var sawSource = false
    @ObservationIgnored private var pending = Data()
    @ObservationIgnored private var tail: Tail?

    /// True for development runs and offscreen renders. Those keep everything in memory: no saved state is written.
    static let debug = ProcessInfo.processInfo.environment["CONTEXT_DEBUG"] != nil

    init() {
        _ = Engine.python      // found now, once: looking for it waits on a process, which must never happen inside a view update
        let env = ProcessInfo.processInfo.environment
        // a development run (CONTEXT_DEBUG) with no folder of its own gets a throwaway one, never the real archive
        home = URL(fileURLWithPath: env["CTX_HOME"].map { ($0 as NSString).expandingTildeInPath }
            ?? (Engine.debug ? NSTemporaryDirectory() + "context-debug" : NSHomeDirectory() + "/.context/v2"))
        repo = Engine.findRepo(Engine.devEngine)
        loadStatus()
        refreshSteps()
        refreshSpans()
        loadSchedule()
    }

    /// True for the copy the owner uses: one that sits in an Applications folder. Only that copy is held to the
    /// engine inside its own bundle; a build-folder run may be pointed at a working copy.
    static let installed: Bool = {
        let path = Bundle.main.bundleURL.resolvingSymlinksInPath().path
        return path.hasPrefix("/Applications/") || path.hasPrefix(NSHomeDirectory() + "/Applications/")
    }()

    static var bundledEngine: URL? { Bundle.main.resourceURL?.appendingPathComponent("engine") }

    /// Every file in the bundle is still the file that was signed, the engine's included.
    static let sealIntact: Bool = {
        var code: SecStaticCode?
        guard SecStaticCodeCreateWithPath(Bundle.main.bundleURL as CFURL, [], &code) == errSecSuccess, let code else { return false }
        return SecStaticCodeCheckValidity(code, SecCSFlags(rawValue: kSecCSCheckAllArchitectures | kSecCSStrictValidate), nil) == errSecSuccess
    }()

    /// Where the engine runs from. The installed app: only the engine inside its own bundle, and only while the
    /// bundle's signature still holds, so no folder another program can write decides what runs with the app's
    /// permissions. A development run (app/build, the checks): CONTEXT_DEV_ENGINE or CONTEXT_REPO names a folder
    /// holding `ctx/`; with neither, the bundled engine, else the working copy the build folder sits in.
    static func findRepo(_ override: String?) -> URL? {
        let fm = FileManager.default
        func ok(_ u: URL) -> Bool { fm.fileExists(atPath: u.appendingPathComponent("ctx/__main__.py").path) }
        if installed {
            if let u = bundledEngine, ok(u), sealIntact { return u }
            return nil
        }
        if let override, !override.isEmpty {
            let u = URL(fileURLWithPath: (override as NSString).expandingTildeInPath)
            return ok(u) ? u : nil
        }
        if let u = bundledEngine, ok(u) { return u }
        var u = Bundle.main.bundleURL.resolvingSymlinksInPath()
        for _ in 0..<8 {
            u = u.deletingLastPathComponent()
            if ok(u) { return u }
            if u.path == "/" { break }
        }
        return nil
    }

    /// The folder named for a development run, under either name.
    static var devEngine: String? {
        let env = ProcessInfo.processInfo.environment
        return env["CONTEXT_DEV_ENGINE"] ?? env["CONTEXT_REPO"]
    }

    func file(_ name: String) -> URL { home.appendingPathComponent(name) }

    func state(_ id: String) -> SourceState { states[id] ?? .idle }

    var totalRows: Int { states.values.reduce(0) { $0 + $1.rows } }
    var readCount: Int { states.values.filter { $0.rows > 0 }.count }
    var blocked: [String] {
        order.filter { if case .skipped = state($0) { return true } else { return false } }
    }

    // MARK: status on disk

    func loadStatus() {
        let url = file("status.json")
        guard let data = try? Data(contentsOf: url),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: [String: Any]] else { return }
        for (name, v) in obj where !running.contains(name) && states[name] != .reading {     // a read in progress knows better than the file
            if !order.contains(name) && !Catalog.hidden.contains(name) { order.append(name) }
            if let rows = v["rows"] as? Int, v["stale"] as? Bool == true {
                states[name] = .kept(rows: rows, why: v["why"] as? String ?? "")
            } else if let rows = v["rows"] as? Int {
                states[name] = .done(rows: rows, secs: (v["secs"] as? Double) ?? 0)
            } else if let why = v["skipped"] as? String {
                states[name] = .skipped(why)
            }
        }
        lastSync = (try? FileManager.default.attributesOfItem(atPath: url.path)[.modificationDate]) as? Date
    }

    func refreshSpans() {
        let home = self.home
        DispatchQueue.global(qos: .utility).async {
            let found = Jsonl.spans(home: home)
            DispatchQueue.main.async { if !self.syncing { self.spans = self.spans.merging(found) { _, new in new } } }
        }
    }

    // MARK: collect

    /// Setup reads everything with one `collect`. After that the app only ever runs `tick`, which does what is due:
    /// sources on this mac every 15 minutes, signed-in ones daily, exports weekly, plus any export zip that arrived.
    /// `tier` forces one: fast, daily or weekly.
    func sync(tick: Bool = false, tier: String? = nil) {
        guard !syncing else { return }
        guard let repo else {
            failure = "the reading half of context is missing or was changed after it was signed. install context again."
            return
        }
        failure = nil
        syncing = true
        ticking = tick
        pending = Data()
        log = [:]
        landed = []
        scanned = [:]
        phaseSince = [:]
        refreshSteps()
        previous = states.mapValues { $0.rows }.filter { $0.value > 0 }
        if !tick {                 // a full read: every source is about to be read again
            live = [:]
            spans = [:]
            for id in order { states[id] = .waiting }
        }
        current = nil
        sawSource = false
        launch(tick ? ["tick"] + (tier.map { [$0] } ?? []) : ["collect"], repo: repo)
    }

    /// What `python3 -m ctx schedule` says: when each tier last ran and runs next, and how the daily sources went.
    func loadSchedule() {
        json(["schedule"], timeout: 30) { [weak self] obj in
            if let obj, let s = Schedule(obj) { self?.schedule = s }
        }
    }

    static let noPython = "context needs python 3. install it once: xcode-select --install"

    /// The python the engine runs on. The installed app: the system's only, so nothing a program can drop into a
    /// writable folder is ever started with the app's permissions. A development run also tries the one saved in
    /// app.json and homebrew's. Each is asked for its version once (3.9 or later). Nil when none works.
    static let python: String? = {
        var tries: [String] = []
        if !installed {
            let home = ProcessInfo.processInfo.environment["CTX_HOME"].map { ($0 as NSString).expandingTildeInPath } ?? (NSHomeDirectory() + "/.context/v2")
            if let data = FileManager.default.contents(atPath: home + "/app.json"),
               let saved = ((try? JSONSerialization.jsonObject(with: data)) as? [String: Any])?["python"] as? String, !saved.isEmpty { tries.append(saved) }
            tries += ["/opt/homebrew/bin/python3", "/usr/local/bin/python3"]
        }
        // /usr/bin/python3 is a stub that opens an install dialog when the command line tools are missing: only try it when they are there
        if FileManager.default.fileExists(atPath: "/Library/Developer/CommandLineTools/usr/bin/python3")
            || FileManager.default.fileExists(atPath: "/Applications/Xcode.app") { tries.append("/usr/bin/python3") }
        for path in tries where FileManager.default.isExecutableFile(atPath: path) {
            let p = Process()
            p.executableURL = URL(fileURLWithPath: path)
            p.arguments = ["-I", "-c", "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)"]
            p.standardOutput = FileHandle.nullDevice
            p.standardError = FileHandle.nullDevice
            if (try? p.run()) != nil { p.waitUntilExit(); if p.terminationStatus == 0 { return path } }
        }
        return nil
    }()

    /// Started isolated (-I): python reads no PYTHON* variable, no user site folder and not the current folder, so
    /// the only code it can import is its own and the engine folder handed to it here. -B: it writes nothing back
    /// into that folder, which would break the app's seal.
    static let boot = "import sys, runpy; sys.path.insert(0, sys.argv.pop(1)); runpy.run_module('ctx', run_name='__main__', alter_sys=True)"

    /// What the engine is told about the world. The installed app passes a short fixed list; a development run
    /// also passes the CTX_ and FAKE_ settings the checks use.
    static func engineEnvironment(repo: URL) -> [String: String] {
        let all = ProcessInfo.processInfo.environment
        var env: [String: String] = [:]
        for k in ["HOME", "USER", "LOGNAME", "TMPDIR", "LANG", "LC_ALL", "LC_CTYPE", "CTX_HOME", "__CF_USER_TEXT_ENCODING"] { if let v = all[k] { env[k] = v } }
        if !installed { for (k, v) in all where k.hasPrefix("CTX_") || k.hasPrefix("FAKE_") || k.hasPrefix("DEMO_") || k.hasPrefix("CONTEXT_") { env[k] = v } }
        env["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin"
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONPATH"] = repo.path      // ignored: the engine and the children it starts (the api, a read) all run isolated (-I), handed the engine's folder by path
        return env
    }

    static func python(_ args: [String], repo: URL) -> Process {
        let p = Process()
        // a path, not PATH: an app opened from the Finder has a bare PATH. with no python at all the launch fails
        // and the caller says so in one line
        p.executableURL = URL(fileURLWithPath: Engine.python ?? "/usr/bin/python3")
        p.arguments = ["-I", "-B", "-u", "-c", boot, repo.path] + args
        p.currentDirectoryURL = repo
        p.environment = engineEnvironment(repo: repo)
        return p
    }

    /// Runs one engine command and hands back the last line of its output that is a JSON object, or nil.
    /// A missing command, a traceback or plain text all come back as nil.
    @discardableResult
    func json(_ args: [String], timeout: TimeInterval = 180, done: @escaping ([String: Any]?) -> Void) -> Process? {
        // what the warm engine knows goes to it: no python start per call. collect, tick, connect and installs stay one-shot
        if client.tryWarm(args, timeout: timeout, done: done) { return nil }
        guard let repo else { done(nil); return nil }
        let p = Engine.python(args, repo: repo)
        let out = Pipe()
        p.standardOutput = out
        p.standardError = FileHandle.nullDevice
        DispatchQueue.global(qos: .userInitiated).async {
            var found: [String: Any]?
            do {
                try p.run()
                DispatchQueue.global().asyncAfter(deadline: .now() + timeout) { if p.isRunning { p.terminate() } }
                let data = out.fileHandleForReading.readDataToEndOfFile()
                p.waitUntilExit()
                let text = String(decoding: data, as: UTF8.self)
                if let obj = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] {
                    found = obj
                } else if let list = (try? JSONSerialization.jsonObject(with: data)) as? [Any] {
                    found = ["list": list]        // a command that prints a list
                } else {
                    for line in text.split(separator: "\n").reversed() where line.hasPrefix("{") {
                        if let obj = (try? JSONSerialization.jsonObject(with: Data(line.utf8))) as? [String: Any] { found = obj; break }
                    }
                }
            } catch {}
            DispatchQueue.main.async { done(found) }
        }
        return p
    }

    private func launch(_ command: [String], repo: URL) {
        let p = Engine.python(command, repo: repo)
        let out = Pipe(), err = Pipe()
        p.standardOutput = out
        p.standardError = err
        out.fileHandleForReading.readabilityHandler = { [weak self] h in
            let d = h.availableData
            guard !d.isEmpty else { return }
            DispatchQueue.main.async { self?.feed(d) }
        }
        var errText = Data()
        err.fileHandleForReading.readabilityHandler = { h in
            let d = h.availableData
            if !d.isEmpty && errText.count < 4000 { errText.append(d) }
        }
        p.terminationHandler = { [weak self] proc in
            out.fileHandleForReading.readabilityHandler = nil
            err.fileHandleForReading.readabilityHandler = nil
            let rest = out.fileHandleForReading.availableData
            let code = proc.terminationStatus
            DispatchQueue.main.async {
                guard let self else { return }
                if !rest.isEmpty { self.feed(rest) }
                self.finish(code: code, stderr: String(decoding: errText, as: UTF8.self))
            }
        }
        do {
            try p.run()
            process = p
        } catch {
            syncing = false
            failure = Engine.python == nil ? Engine.noPython : "could not start python: \(error.localizedDescription.lowercased())"
            loadStatus()
        }
    }

    private func feed(_ data: Data) {
        pending.append(data)
        while let nl = pending.firstIndex(of: 0x0A) {
            let line = String(decoding: pending[pending.startIndex..<nl], as: UTF8.self)
            pending.removeSubrange(pending.startIndex...nl)
            handle(line)
        }
    }

    /// `whatsapp     {'rows': 150000, 'secs': 6.4}` or `imessage     {'skipped': 'reason'}`
    /// A source's final line says how many rows are new: {'rows': N, 'new': M}. The count shows beside it for a few seconds.
    func noteNew(_ line: String, _ name: String) {
        guard let r = line.range(of: #"'new': (\d+)"#, options: .regularExpression), let n = Int(line[r].dropFirst(7)), n > 0 else { return }
        fresh[name] = n
        DispatchQueue.main.asyncAfter(deadline: .now() + 4) { [weak self] in if self?.fresh[name] == n { self?.fresh[name] = nil } }
    }

    static func parse(_ line: String) -> (String, SourceState)? {
        guard let brace = line.firstIndex(of: "{"), line.hasSuffix("}") else { return nil }
        let name = line[..<brace].trimmingCharacters(in: .whitespaces)
        guard !name.isEmpty, !name.contains(" ") else { return nil }
        let body = String(line[brace...])
        if let r = body.range(of: #"'rows': (\d+)"#, options: .regularExpression) {
            let rows = Int(body[r].dropFirst(8)) ?? 0
            if body.contains("'stale': True") {
                var why = ""
                if let w = body.range(of: "'why': ") {
                    why = String(body[w.upperBound...].dropLast())
                    if why.count >= 2 { why = String(why.dropFirst().dropLast()) }
                }
                return (name, .kept(rows: rows, why: why))
            }
            var secs = 0.0
            if let s = body.range(of: #"'secs': ([0-9.]+)"#, options: .regularExpression) {
                secs = Double(body[s].dropFirst(8)) ?? 0
            }
            return (name, .done(rows: rows, secs: secs))
        }
        if let r = body.range(of: "'skipped': ") {
            var why = String(body[r.upperBound...].dropLast())
            if why.count >= 2 { why = String(why.dropFirst().dropLast()) }
            return (name, .skipped(why))
        }
        return nil
    }

    /// `@{"src":"whatsapp","rows":1700,"at":"2025-02","label":"..."}`
    static func progress(_ line: String) -> (String, Sample)? {
        guard line.hasPrefix("@"), let d = (try? JSONSerialization.jsonObject(with: Data(line.dropFirst().utf8))) as? [String: Any],
              let src = d["src"] as? String else { return nil }
        return (src, Sample(rows: d["rows"] as? Int ?? 0, at: d["at"] as? String ?? "", label: d["label"] as? String ?? "",
                            phase: d["phase"] as? String ?? ""))
    }

    private func handle(_ line: String) {
        if let (src, sample) = Engine.progress(line) {       // the full collect reads three lanes at once
            heard = src
            heardAt = Date()
            if src == "understand", let d = (try? JSONSerialization.jsonObject(with: Data(line.dropFirst().utf8))) as? [String: Any],
               let of = d["of"] as? Int, of > 0 { readThrough = (sample.rows, of) }
            if states[src]?.finished != true {
                if states[src] != .reading { states[src] = .reading; log[src] = [] }
                take(sample, for: src)
            }
            return
        }
        guard let (name, state) = Engine.parse(line) else { return }
        noteNew(line, name)
        sawSource = true
        landed.insert(name)
        if !order.contains(name) && !Catalog.hidden.contains(name) { order.append(name) }
        states[name] = state
        live[name] = state.rows
        let ats = (log[name] ?? []).map(\.at).filter { !$0.isEmpty }
        if let a = ats.min(), let b = ats.max() { spans[name] = DateSpan(first: a + "-01", last: b + "-01") }
        current = order.first { states[$0] == .reading }
    }

    private func finish(code: Int32, stderr: String) {
        tail?.stop()
        tail = nil
        process = nil
        syncing = false
        current = nil
        heard = nil
        readThrough = nil
        for id in order where states[id] == .waiting || states[id] == .reading { states[id] = .idle }
        ticking = false
        loadSchedule()
        if code != 0 {
            let last = stderr.split(separator: "\n").last.map(String.init) ?? "exit \(code)"
            failure = "the collector stopped: \(last.lowercased())"
        }
        loadStatus()
        refreshSteps()
        lastSync = Date()
        refreshSpans()
        onFinish?()
    }

    func stop() { process?.terminate() }

    // MARK: one source at a time (setup)

    /// A new setup run: every source is read again, when its step comes up.
    func resetRun() {
        readRun = []
        queued = []
        log = [:]
    }

    /// Reads one source now, unless this run already asked for it. At most two run at once; a third waits its turn,
    /// and the one asked for last goes first.
    func read(_ id: String, first: Bool = false) {
        guard repo != nil, !syncing else { return }
        if readRun.contains(id) {
            if first, let i = queued.firstIndex(of: id) { queued.remove(at: i); queued.insert(id, at: 0) }
            return
        }
        readRun.insert(id)
        if first { queued.insert(id, at: 0) } else { queued.append(id) }
        pump()
    }

    var readsLeft: Int { running.count + queued.count }

    private func pump() {
        while running.count < Engine.maxReads, !queued.isEmpty { start(queued.removeFirst()) }
    }

    private func start(_ id: String) {
        guard let repo else { return }
        let p = Engine.python(["collect-one", id], repo: repo)
        let out = Pipe()
        p.standardOutput = out
        p.standardError = FileHandle.nullDevice
        running.insert(id)
        previous[id] = state(id).rows
        states[id] = .reading
        live[id] = 0
        log[id] = [Sample(rows: 0, at: "", label: "", phase: "starting")]
        var buffer = Data()
        var final: SourceState?
        let began = Date()
        out.fileHandleForReading.readabilityHandler = { [weak self] h in
            let d = h.availableData
            guard !d.isEmpty else { return }
            var lines: [String] = []
            buffer.append(d)
            while let nl = buffer.firstIndex(of: 0x0A) {
                lines.append(String(decoding: buffer[buffer.startIndex..<nl], as: UTF8.self))
                buffer.removeSubrange(buffer.startIndex...nl)
            }
            DispatchQueue.main.async {
                guard let self else { return }
                for line in lines {
                    if let (src, sample) = Engine.progress(line) {
                        if src == id { self.take(sample, for: id) }
                    } else if let (name, state) = Engine.parse(line), name == id {
                        final = state
                        self.noteNew(line, name)
                    }
                }
            }
        }
        p.terminationHandler = { [weak self] _ in
            out.fileHandleForReading.readabilityHandler = nil
            let rest = String(decoding: buffer + out.fileHandleForReading.availableData, as: UTF8.self)
            DispatchQueue.main.async {
                guard let self else { return }
                for line in rest.split(separator: "\n").map(String.init) {
                    if let (src, sample) = Engine.progress(line) { if src == id { self.take(sample, for: id) } }
                    else if let (name, state) = Engine.parse(line), name == id { final = state }
                }
                var state = final ?? .skipped("error: the read stopped before it finished")
                if case .done(let rows, let secs) = state, secs == 0 { state = .done(rows: rows, secs: Date().timeIntervalSince(began)) }
                self.states[id] = state
                self.live[id] = state.rows
                let ats = (self.log[id] ?? []).map(\.at).filter { !$0.isEmpty }
                if let a = ats.min(), let b = ats.max() { self.spans[id] = DateSpan(first: a + "-01", last: b + "-01") }
                self.running.remove(id)
                self.readers[id] = nil
                self.refreshSteps()
                if self.readsLeft == 0 { self.lastSync = Date() }
                self.pump()
                self.onRead?(id)
            }
        }
        do {
            try p.run()
            readers[id] = p
        } catch {
            running.remove(id)
            states[id] = .skipped("error: " + (Engine.python == nil ? Engine.noPython : "could not start python"))
            onRead?(id)
        }
    }

    /// The figure in "found 12,345 emails. working out which address is yours", or nil.
    static func found(in phase: String) -> Int? {
        guard let r = phase.range(of: #"found ([0-9][0-9,]*)"#, options: .regularExpression) else { return nil }
        return Int(phase[r].dropFirst(6).replacingOccurrences(of: ",", with: ""))
    }

    private func take(_ s: Sample, for id: String) {
        if !s.phase.isEmpty, s.phase != log[id]?.last?.phase {
            phaseSince[id] = Date()
            if let n = Engine.found(in: s.phase) { scanned[id] = n }
        }
        var list = log[id] ?? []
        if s.label.isEmpty, s.phase.isEmpty, let last = list.last, last.at == s.at, list.count > 1 {
            list[list.count - 1].rows = s.rows        // only the count moved: no new line for the feed
        } else {
            list.append(s)
        }
        if list.count > 160 {       // keep the shape of the read, drop every other line of the older half
            let half = list.count / 2
            list = list[..<half].enumerated().filter { $0.offset % 2 == 0 }.map(\.element) + list[half...]
        }
        log[id] = list
        live[id] = s.rows
    }

    // MARK: follow the files while they grow

    private func startTail() {
        let t = Tail(files: ["messages.jsonl", "sessions.jsonl", "docs.jsonl"].map(file)) { [weak self] lines, first, last in
            guard let self, self.syncing, let c = self.current else { return }
            self.live[c, default: 0] += lines
            for d in [first, last].compactMap({ $0 }) {
                if self.spans[c] == nil { self.spans[c] = DateSpan(first: d, last: d) } else { self.spans[c]?.take(d) }
            }
        }
        tail = t
        t.start()
    }
}

/// Reads what the collector appended since the last look: how many rows, and the dates at both ends.
final class Tail {
    private let files: [URL]
    private var offsets: [Int]
    private let queue = DispatchQueue(label: "so.context.tail", qos: .userInitiated)
    private var timer: DispatchSourceTimer?
    private let report: (Int, String?, String?) -> Void

    init(files: [URL], report: @escaping (Int, String?, String?) -> Void) {
        self.files = files
        self.report = report
        // The collector truncates each file when it opens it, so start from the end of what is there now.
        offsets = files.map { Tail.size($0) }
    }

    static func size(_ u: URL) -> Int {
        var st = stat()
        return stat(u.path, &st) == 0 ? Int(st.st_size) : 0
    }

    func start() {
        let t = DispatchSource.makeTimerSource(queue: queue)
        t.schedule(deadline: .now() + 0.1, repeating: 0.12)
        t.setEventHandler { [weak self] in self?.tick() }
        t.resume()
        timer = t
    }

    /// A source just finished: whatever is read next belongs to the following one.
    func mark() {}

    func stop() { timer?.cancel(); timer = nil }

    private func tick() {
        for (i, url) in files.enumerated() {
            let size = Tail.size(url)
            if size < offsets[i] { offsets[i] = 0 }
            guard size > offsets[i] else { continue }
            let fd = open(url.path, O_RDONLY)
            guard fd >= 0 else { continue }
            defer { close(fd) }
            let want = min(size - offsets[i], 8 << 20)
            var buf = [UInt8](repeating: 0, count: want)
            let got = pread(fd, &buf, want, off_t(offsets[i]))
            guard got > 0 else { continue }
            var lines = 0, lastNL = -1, firstNL = -1, prevNL = -1
            for j in 0..<got where buf[j] == 0x0A {
                lines += 1
                if firstNL < 0 { firstNL = j }
                prevNL = lastNL
                lastNL = j
            }
            guard lastNL >= 0 else { continue }
            offsets[i] += lastNL + 1
            let first = Jsonl.date(in: buf[0..<firstNL])
            let last = Jsonl.date(in: buf[(prevNL + 1)..<lastNL])
            DispatchQueue.main.async { self.report(lines, first, last) }
        }
    }
}

enum Access {
    /// Full Disk Access has no API. The honest test is to try the file it guards.
    static var fullDisk: Bool {
        let home = NSHomeDirectory()
        let fd = open(home + "/Library/Messages/chat.db", O_RDONLY)
        if fd >= 0 { close(fd); return true }
        if errno == ENOENT {
            return (try? FileManager.default.contentsOfDirectory(atPath: home + "/Library/Mail")) != nil
        }
        return false
    }

    static func openSettings() {
        if let u = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles") {
            NSWorkspace.shared.open(u)
        }
    }

    static func relaunch() {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/bin/sh")
        p.arguments = ["-c", "sleep 0.6; /usr/bin/open \"$0\"", Bundle.main.bundlePath]
        try? p.run()
        NSApp.terminate(nil)
    }
}
