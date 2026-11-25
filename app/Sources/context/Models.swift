import SwiftUI

/// Which model does which job, as `python3 -m ctx models --json` reports it. No model is named in the app: every
/// name, tier, speed and reason here is the engine's.
struct ModelsReport: Equatable {
    struct Model: Identifiable, Equatable {
        let ask: String, name: String, plan: String, tier: String, usage: String, whyNot: String
        let ok: Bool
        let secs: Double?
        let recommendedFor: [String]
        var id: String { plan + ":" + ask }
        /// "strongest · 4.2 s to first words · uses more of your plan"
        var line: String {
            ([tier] + (secs.map { [String(format: "%.1f s to first words", $0)] } ?? []) + (usage.isEmpty ? [] : [usage])).filter { !$0.isEmpty }.joined(separator: "  ·  ")
        }
    }
    struct Role: Identifiable, Equatable {
        let id: String, name: String, plan: String, why: String
        var ask = "", source = ""
        /// the owner picked this job's model themselves, so it no longer follows the preset
        var chosen: Bool { !source.isEmpty && !source.hasPrefix("preset") && source != "plan limit" }
    }
    struct Limit: Equatable { let plan: String, until: Date, why: String }
    struct Preset: Identifiable, Equatable {
        let id: String, about: String
        var recommended: Bool { about.lowercased().hasPrefix("recommended") }
        /// the engine's sentence without its leading "recommended:"
        var says: String { recommended ? about.dropFirst("recommended".count).trimmingCharacters(in: CharacterSet(charactersIn: ": ")) : about }
    }

    static let jobs = ["routine", "analysis", "first_parse", "tools"]
    static let jobWords = ["routine": "everyday answers", "analysis": "long analysis", "first_parse": "the first read", "tools": "steering the search"]
    static let presetOrder = ["balanced", "best", "lean"]

    var models: [Model] = []
    var roles: [Role] = []
    var presets: [Preset] = []
    var preset = ""
    var notes: [String] = []
    var fallbackOn = true
    var measuredAt: Date?
    var limits: [Limit] = []         // plans at their limit now, and when each lifts

    init?(_ d: [String: Any]?) {
        guard let d, let ms = d["models"] as? [[String: Any]] else { return nil }
        models = ms.compactMap { m in
            guard let name = m["name"] as? String, let plan = m["plan"] as? String else { return nil }
            return Model(ask: m["ask"] as? String ?? m["id"] as? String ?? name, name: name.lowercased(), plan: plan, tier: m["tier"] as? String ?? "",
                         usage: m["usage"] as? String ?? "", whyNot: m["why_not"] as? String ?? "", ok: m["ok"] as? Bool ?? false,
                         secs: (m["first_secs"] as? NSNumber)?.doubleValue, recommendedFor: m["recommended_for"] as? [String] ?? [])
        }
        let who = d["roles"] as? [String: [String: Any]] ?? [:]
        roles = ModelsReport.jobs.compactMap { j in
            who[j].map { Role(id: j, name: ($0["name"] as? String ?? "").lowercased(), plan: $0["plan"] as? String ?? "", why: ($0["why"] as? String ?? "").lowercased(),
                              ask: $0["ask"] as? String ?? "", source: ($0["source"] as? String ?? "").lowercased()) }
        }
        limits = (d["limited"] as? [String: [String: Any]] ?? [:]).map { Limit(plan: $0.key, until: Date(timeIntervalSince1970: ($0.value["until"] as? NSNumber)?.doubleValue ?? 0), why: ($0.value["why"] as? String ?? "").lowercased()) }
            .sorted { $0.plan < $1.plan }
        let pre = d["presets"] as? [String: [String: Any]] ?? [:]
        presets = (ModelsReport.presetOrder.filter { pre[$0] != nil } + pre.keys.filter { !ModelsReport.presetOrder.contains($0) }.sorted())
            .map { Preset(id: $0, about: (pre[$0]?["about"] as? String ?? "").lowercased()) }
        preset = d["preset"] as? String ?? ""
        notes = (d["notes"] as? [String] ?? []).map { $0.lowercased() }
        fallbackOn = d["fallback_when_limited"] as? Bool ?? true
        measuredAt = (d["measured_at"] as? NSNumber).map { Date(timeIntervalSince1970: $0.doubleValue) }
    }

    /// The plans that can run something, in the order the engine lists them.
    var plans: [String] { models.filter(\.ok).reduce(into: [String]()) { if !$0.contains($1.plan) { $0.append($1.plan) } } }
    func name(of ask: String) -> String { models.first { $0.ask == ask }?.name ?? ask }

    /// "runs on claude · balanced (recommended)". With two plans, which does what.
    var runsOn: String {
        guard !plans.isEmpty else { return "" }
        let tag = presets.first { $0.id == preset }.map { $0.id + ($0.recommended ? " (recommended)" : "") } ?? preset
        if plans.count < 2 { return "runs on \(plans[0])  ·  \(tag)" }
        let by = plans.map { p in p + " for " + roles.filter { $0.plan == p }.compactMap { ModelsReport.jobWords[$0.id] }.joined(separator: ", ") }
        return "runs on " + by.filter { !$0.hasSuffix(" for ") }.joined(separator: "; ") + "  ·  \(tag)"
    }
}

extension AppModel {
    /// The models report. The one-shot `models --json` also starts the daily model check (one tiny call to each model),
    /// so it runs only once setup is done and the switch for that check is on; before that, or with the switch off, the
    /// report comes from the warm engine, which answers `models` without checking anything, or not at all.
    /// `refresh` is the owner's own test, which checks every model now.
    func loadModels(refresh: Bool = false) {
        guard !Engine.debug else { return }
        let args = ["models", "--json"] + (refresh ? ["--refresh"] : [])
        let take: ([String: Any]?) -> Void = { [weak self] obj in if let r = ModelsReport(obj) { self?.models = r } }
        if refresh || (saved.onboarded && saved.modelCheck) { engine.json(args, timeout: refresh ? 300 : 60, done: take) }
        else { _ = engine.client.tryWarm(args, timeout: 60, done: take) }
    }

    /// `settings --set preset=…`: all four jobs at once.
    func setPreset(_ id: String) {
        models?.preset = id
        engine.json(["settings", "--set", "preset=\(id)"], timeout: 30) { [weak self] _ in self?.loadModels() }
    }

    /// The model picked for one chat becomes the one that answers everywhere.
    func makeDefault(_ ask: String) {
        engine.json(["settings", "--set", "model.routine=\(ask)"], timeout: 30) { [weak self] _ in
            self?.engine.json(["settings", "--set", "model.analysis=\(ask)"], timeout: 30) { _ in self?.loadModels() }
        }
    }

    /// `settings --set model.<job>=<id>`: one job's model. "preset" hands the job back to the preset.
    func setJob(_ job: String, _ ask: String) {
        engine.json(["settings", "--set", "model.\(job)=\(ask)"], timeout: 30) { [weak self] _ in self?.loadModels() }
    }

    /// Trouble with the plan the answers run on, in a few words, or nil. Only this is ever shown outside settings.
    var planTrouble: String? {
        if let p = plan, !p.ready { return "no ai plan signed in" }
        if let l = models?.limits.first { return "plan limit reached" + (l.until > Date() ? ", until " + Words.hourMinute(l.until) : "") }
        return nil
    }

    func setFallback(_ on: Bool) {
        models?.fallbackOn = on
        engine.json(["settings", "--set", "fallback_when_limited=\(on ? "on" : "off")"], timeout: 30) { [weak self] _ in self?.loadModels() }
    }

    /// `models --bench`: asks every model a set of questions, on their plan. Only ever after the owner has said yes.
    func measureModels() {
        guard !measuring else { return }
        measuring = true
        engine.json(["models", "--bench"], timeout: 7200) { [weak self] _ in self?.measuring = false; self?.loadModels() }
    }
}

/// In the input, left of send: what answers this chat. The presets first, then any one model of their plans.
struct ModelMenu: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let ask = model.ask
        if let r = model.models, !r.presets.isEmpty {
            let word = ask.model.isEmpty ? r.preset : r.name(of: ask.model)
            Menu {
                ForEach(r.presets) { p in
                    Toggle(isOn: Binding(get: { ask.model.isEmpty && r.preset == p.id }, set: { _ in ask.model = ""; model.setPreset(p.id) })) {
                        Text(p.id + (p.recommended ? "  ·  recommended" : ""))
                        Text(p.says)
                    }
                }
                Divider()
                Menu("choose a model…") {
                    ForEach(r.plans, id: \.self) { plan in
                        Section(plan) {
                            ForEach(r.models.filter { $0.plan == plan && $0.ok }) { m in
                                Toggle(isOn: Binding(get: { ask.model == m.ask }, set: { on in ask.model = on ? m.ask : "" })) {
                                    Text(m.name)
                                    Text(m.line)
                                }
                            }
                        }
                    }
                }
                if !ask.model.isEmpty {
                    Divider()
                    Button("make \(r.name(of: ask.model)) the default") { model.makeDefault(ask.model) }
                    Button("back to \(r.preset) in this chat") { ask.model = "" }
                }
            } label: {
                HStack(spacing: 5) {
                    Text(word).font(.system(size: 12, weight: .medium)).foregroundStyle(Ink.soft).lineLimit(1)
                    Image(systemName: "chevron.down").font(.system(size: 7.5, weight: .bold)).foregroundStyle(Ink.soft)
                }
                .padding(.horizontal, 9).frame(height: 26).contentShape(Rectangle())
            }
            .menuStyle(.borderlessButton).menuIndicator(.hidden).fixedSize()
            .help("which model answers. \(r.presets.first { $0.id == r.preset }?.says ?? "")")
            .accessibilityLabel("model: \(word)")
            .probe("chat.model", .button, group: "chat.controls")
        }
    }
}

extension LayoutTest {
    /// A made-up report in the engine's shape: two plans, three models each named for nothing real.
    static let modelsReport: [String: Any] = [
        "models": [
            ["id": "large", "ask": "large", "name": "Plan A large", "plan": "plan a", "ok": true, "tier": "strongest", "measured": true, "first_secs": 4.2, "usage": "uses more of your plan", "recommended_for": ["analysis", "first_parse"]],
            ["id": "medium", "ask": "medium", "name": "Plan A medium", "plan": "plan a", "ok": true, "tier": "balanced", "measured": true, "first_secs": 2.1, "usage": "", "recommended_for": ["routine"]],
            ["id": "small", "ask": "small", "name": "Plan A small", "plan": "plan a", "ok": true, "tier": "fast", "measured": true, "first_secs": 0.9, "usage": "uses the least of your plan", "recommended_for": ["tools"]],
            ["id": "other", "ask": "other", "name": "Plan B default", "plan": "plan b", "ok": true, "tier": "balanced", "measured": false, "usage": "", "recommended_for": [String]()],
            ["id": "gone", "ask": "gone", "name": "Plan B old", "plan": "plan b", "ok": false, "why_not": "not on this plan", "tier": "fast"]],
        "roles": ["routine": ["name": "Plan A medium", "ask": "medium", "plan": "plan a", "why": "Quick and good enough for a lookup.", "source": "you chose it"],
                  "analysis": ["name": "Plan A large", "plan": "plan a", "why": "Long thinking over many threads: the strongest your plan runs."],
                  "first_parse": ["name": "Plan A large", "plan": "plan a", "why": "First read: strongest. It runs once and everything later leans on it."],
                  "tools": ["name": "Plan A small", "plan": "plan a", "why": "Steering the search is many small calls: the quickest."]],
        "preset": "balanced",
        "presets": ["balanced": ["about": "Recommended: the strongest model reads your archive and does long thinking; quick ones answer everyday questions. About 3 s to first words."],
                    "best": ["about": "The strongest model does everything. Slower, about 5 s to first words, and uses more of your plan."],
                    "lean": ["about": "The quickest model does everything. About 1 s to first words; answers to hard questions get worse."]],
        "notes": ["Plan B was at its limit until 14:00, so the last answer was written by Plan A small."],
        "fallback_when_limited": true, "measured_at": Date().timeIntervalSince1970 - 7200]
}
