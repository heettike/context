import SwiftUI

/// First run. Two screens: what this is with its four switches, then every source reading at once.
/// A source's own live view opens from its row and closes back to the list.
struct OnboardingView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduce
    private let poll = Timer.publish(every: 1.5, on: .main, in: .common).autoconnect()
    @State private var ticks = 0

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .topLeading) {
                if let id = model.detail, model.step == .reading { bigMark(id, in: geo.size) }
                VStack(spacing: 0) {
                    SetupBar(title: barTitle)
                    screen
                        .id(screenKey)
                        .transition(reduce ? .opacity : .asymmetric(
                            insertion: .opacity,
                            removal: .opacity.combined(with: .offset(y: -14)).animation(.easeIn(duration: 0.13))))
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                }
            }
            .animation(Motion.spring(reduce), value: screenKey)
        }
        .onReceive(poll) { _ in
            ticks += 1
            model.pollSwitches(deep: model.step == .welcome ? ticks % 3 == 0 : (ticks % 6 == 0 && !model.engine.syncing))
        }
    }

    private var screenKey: String { model.step == .welcome ? "switches" : (model.detail ?? "reading") }

    /// The word in the middle of the bar, as a page's name is in the app.
    private var barTitle: String {
        if model.step == .welcome { return "set up" }
        if let id = model.detail { return Catalog.info(id).name }
        return model.engine.syncing ? "reading" : "read"
    }

    /// Each screen is one centred column with its button row under it. A screen taller than a short window scrolls
    /// inside its own space; the button row never moves.
    @ViewBuilder private var screen: some View {
        if model.step == .welcome {
            ViewThatFits(in: .vertical) {
                VStack(spacing: 0) {
                    Spacer(minLength: 14)
                    SwitchScreen()
                    footer.padding(.top, 22)
                    Spacer(minLength: 14)
                }
                VStack(spacing: 0) {
                    ScrollView(showsIndicators: false) { SwitchScreen().padding(.top, 14) }
                    footer.padding(.top, 10).padding(.bottom, 18)
                }
            }
            .frame(maxWidth: Setup.column).padding(.horizontal, Setup.gutter)
        } else if let id = model.detail {
            VStack(alignment: .leading, spacing: 0) {
                ViewThatFits(in: .vertical) {
                    SourceStep(id: id)
                    ScrollView(showsIndicators: false) { SourceStep(id: id) }
                }
                .frame(maxWidth: 480, maxHeight: .infinity, alignment: .topLeading)
                footer.padding(.bottom, 22)
            }
            .padding(.top, 26)
            .frame(maxWidth: Setup.wall, alignment: .leading).padding(.horizontal, Setup.gutter)
        } else {
            VStack(alignment: .leading, spacing: 0) {
                ReadingScreen().frame(maxHeight: .infinity, alignment: .top)
                footer.padding(.top, 12).padding(.bottom, 22)
            }
            .padding(.top, 22)
            .frame(maxWidth: Setup.wall).padding(.horizontal, Setup.gutter)
        }
    }

    /// The source's own icon, large, beside its live view. It breathes while that source is being read.
    private func bigMark(_ id: String, in size: CGSize) -> some View {
        let reading = model.engine.state(id) == .reading
        let finished = model.engine.state(id).finished
        let side = min(size.height * 0.34, 220)
        return SourceIcon(id: id, size: side)
            .opacity(reading || (finished && model.engine.state(id).rows > 0) ? 1 : 0.45)
            .scaleEffect(reading && !reduce ? 1.03 : 1)
            .animation(reduce ? nil : .easeInOut(duration: 1.4).repeatForever(autoreverses: true), value: reading)
            .position(x: min(size.width - side * 0.95, size.width / 2 + Setup.wall / 2 - side * 0.5), y: size.height * 0.45)
            .allowsHitTesting(false)
            .accessibilityHidden(true)
            .transition(.opacity)
    }

    // MARK: footer

    @ViewBuilder private var footer: some View {
        HStack(spacing: 16) {
            if model.step == .welcome {
                // nothing is mandatory: whatever is off only means those sources wait
                Button("start reading") { model.startReading() }.buttonStyle(PrimaryButton()).ring(22)
                    .disabled((model.engine.repo == nil || Engine.python == nil) && !Probe.on)
                Text(startHint).font(.system(size: 12, weight: .medium)).foregroundStyle(Ink.soft).lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
                    .probe("first.hint", .text)
            } else if let id = model.detail {
                Button("back to the wall") { model.detail = nil }.buttonStyle(PrimaryButton(hint: "esc")).ring(22)
                if model.engine.state(id).finished, !model.engine.syncing, !model.engine.running.contains(id) {
                    Button("read again") { model.engine.readRun.remove(id); model.settled = nil; model.engine.read(id, first: true) }
                        .buttonStyle(QuietButton(size: 13))
                }
            } else {
                Button("open context") { model.finishOnboarding() }.buttonStyle(PrimaryButton()).ring(22)
                Text(model.readHint)
                    .font(.system(size: 12, weight: .medium)).foregroundStyle(Ink.soft).lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
                    .probe("read.hint", .text)
            }
            Spacer(minLength: 0)
        }
        .frame(minHeight: 40)
        .probe("setup.footer", .block)
    }

    /// "12 sources can start now; 9 wait on full disk access"
    private var startHint: String {
        if Engine.python == nil, !Probe.on { return Engine.noPython }
        if model.engine.repo == nil, !Probe.on { return "the reading half of context is missing. keep the app inside the folder it came in." }
        let c = model.startCounts
        var s = "\(c.now) source\(c.now == 1 ? "" : "s") can start now"
        if c.disk > 0 { s += "; \(c.disk) wait on full disk access" }
        if c.browser > 0 { s += "; \(c.browser) wait on your browser" }
        return s
    }
}

/// The measures of first run: one centred column, as home and a conversation are, and a wider one for the wall.
enum Setup {
    static let column: CGFloat = Grid.column - 60
    static let wall: CGFloat = 980
    static let gutter: CGFloat = 32
}

/// First run's own top row, on the traffic lights' centre line like the app's: the mark after the lights, the name
/// of the screen in the middle, and at the right the key that asks from anywhere, as macos registered it.
struct SetupBar: View {
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduce
    let title: String

    var body: some View {
        let keys = HotKey.keys(model.liveKey)
        HStack(alignment: .center, spacing: 6) {
            LogoMark(size: TopBar.mark).probe("bar.item", .block)
            Spacer(minLength: 12)
            if !keys.isEmpty {
                HStack(spacing: 4) {
                    Text("ask from anywhere").font(.system(size: 12, weight: .medium)).foregroundStyle(Ink.soft).lineLimit(1).fixedSize()
                        .padding(.trailing, 3)
                    ForEach(keys, id: \.self) { KeyHint(key: $0) }
                }
                .probe("first.key", .line)
                .accessibilityElement(children: .ignore)
                .accessibilityLabel("ask from anywhere with " + keys.joined(separator: " "))
            }
        }
        .padding(.leading, model.lights.x + 12).padding(.trailing, 16)
        .frame(height: model.lights.y * 2, alignment: .center)
        .overlay(alignment: .center) {
            Text(title).font(.system(size: 13, weight: .semibold)).foregroundStyle(Ink.soft).lineLimit(1).truncationMode(.tail)
                .probe("bar.title", .block)
                .offset(y: -TopBar.rise(TopBar.tabFont))
                .padding(.horizontal, 230)
                .accessibilityAddTraits(.isHeader)
        }
        .frame(maxWidth: .infinity)
        .background(Ink.paper.probe("bar.ground", .block))
        // the name changes where it stands: a fade from one word to the next draws both at once
        .transaction { $0.animation = nil }
    }
}
