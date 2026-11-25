import AppKit
import SwiftUI

// MARK: the chat's screens for the layout check. every name and line here is made up.

extension LayoutTest {
    static let followUp = "and the deposit"
    static let veryLong = "i am trying to work out, before i write back to sam, whether i ever told him or ines or anyone in the flat group "
        + "that we would renew the lease for another year, what i said about the deposit carrying over, whether the boiler repair "
        + "was meant to come out of it, and which of those messages came first, because i remember it differently every time i think about it"

    static func source(_ i: Int, _ src: String, _ thread: String, _ who: String, _ text: String, url: String = "") -> [String: Any] {
        ["id": "R\(i)", "src": src, "ts": "2026-\(i % 2 == 0 ? "11" : "10")-\(String(format: "%02d", 3 + i * 2))T10:00:00Z", "thread": thread, "who": who, "text": text, "url": url]
    }

    static let lease: [String: Any] = [
        "answer": "not yet. sam asked about the renewal twice and you have not written back.[1][2] he first raised it on the fourth, "
            + "then again six days later, when he also asked about the deposit.[2] you did write a note with two questions for him: "
            + "the renewal date, and whether the deposit carries over.[3] nothing in your mail mentions the lease at all.",
        "cites": [source(1, "whatsapp", "sam (landlord)", "them", "the lease renewal is due on the first. can you let me know by then whether you are staying?"),
                  source(2, "whatsapp", longName, "them", "did you see my message about the renewal? i also need to know about the deposit, and whether you want the boiler looked at before winter."),
                  source(3, "apple_notes", "lease questions", "me", "ask sam about the renewal date and whether the deposit carries over.")],
        "searched": ["sam lease", "renewal", "deposit", "staying another year"], "found": 38, "secs": 17.2, "error": ""]

    static let eight: [String: Any] = [
        "answer": "you have gone back and forth on it since september.[1] the short version is that you want to stay, ines does not mind, and the price is the open question.[2][3]\n"
            + "- sam offered the same rent for a twelve month term.[4]\n"
            + "- you told ines you would decide by the end of the month.[5]\n"
            + "- you saved two listings nearby that cost less.[6][7]\n"
            + "- your own note says to ask about the deposit before signing.[8]\n"
            + "the next step is yours: he is waiting on a yes or a no.[1][4]",
        "cites": [source(1, "whatsapp", "sam (landlord)", "them", "the lease renewal is due on the first. can you let me know by then whether you are staying?"),
                  source(2, "imessage", "ines", "me", "honestly i would rather stay. moving in january sounds awful."),
                  source(3, "whatsapp", longName, "them", "fine by me either way, as long as the rent does not jump again like it did last spring when nobody warned us."),
                  source(4, "email", "re: renewal terms", "them", "happy to keep the rent where it is for a twelve month term. let me know and i will send the paperwork over."),
                  source(5, "imessage", "ines", "me", "i'll decide by the end of the month, promise."),
                  source(6, "x_bookmarks", "@flatfinder", "saved", "two bed, top floor, ten minutes from the park. available from february.", url: "https://example.com/listing/1"),
                  source(7, "instagram", "@rooms.to.let", "saved", "bright corner flat with a small balcony. bills included.", url: "https://example.com/listing/2"),
                  source(8, "apple_notes", "lease questions", "me", "ask sam about the renewal date and whether the deposit carries over.\n\nalso: who pays for the boiler? check the old contract before replying, the clause is on page four.")],
        "searched": ["sam lease renewal", "ines staying", "rent twelve month term", "deposit", "listing flat", "boiler contract clause"],
        "found": Invented.found, "secs": 31.6, "error": ""]

    static let found: [String: Any] = [
        "answer": "it is the talk you gave at the allotment open day.[1] the recording is at https://video.example.com/watch?v=Qw3rTy9ZxA&list=PLmadeUpListIdThatIsQuiteLong0123456789. "
            + "you also sent maya a shorter cut (https://example.com/clips/talk-short).[2]",
        "cites": [source(1, "x_bookmarks", "@lowerfield_plots", "saved", "recording of last night's talks is up", url: "https://video.example.com/watch?v=Qw3rTy9ZxA"),
                  source(2, "whatsapp", "maya okafor", "me", "here is the short cut https://example.com/clips/talk-short")],
        "links": [["url": "https://video.example.com/watch?v=Qw3rTy9ZxA&list=PLmadeUpListIdThatIsQuiteLong0123456789", "what": "the open day talk, full recording", "ts": "2026-10-05T10:00:00Z", "src": "x_bookmarks"],
                  ["url": "https://example.com/clips/talk-short", "what": "", "ts": "2026-10-07T10:00:00Z", "src": "whatsapp"],
                  ["url": "javascript:alert(1)", "what": "not an address", "ts": "", "src": ""]],
        "searched": ["allotment talk", "open day talk"], "found": 9, "secs": 12.0, "error": ""]

    static var lensAnswer: (Answer, [LensItem]) {
        var items: [[String: Any]] = []
        for i in 0..<5 {
            items.append(["what": i == 2 ? "introduce priya to the founder of the print shop, with a note on why they should talk about the yearly plan and the new proofs"
                            : "introduce maya to jonas about the pricing page",
                          "who": i == 1 ? "the allotment committee" : "maya okafor", "when": "2026-11-" + String(format: "%02d", 4 + i),
                          "status": ["open", "done", "unclear"][i % 3], "cite": source(i, "whatsapp", "maya okafor", "me", "i'll intro you two this week")])
        }
        return Answer.from(lens: .object(["title": "intros i promised", "summary": "you offered five introductions in the last two months. two went out, three did not.",
                                          "items": items, "searched": ["intro", "introduce"], "error": ""]), title: "intros i promised", tag: "t0")
    }

    /// A long answer written as analysis: every kind of block, with citations in prose, in a list and in a table.
    static let report: [String: Any] = [
        "answer": """
        ## Where the lease stands

        **Not settled.** Sam has asked twice and you have not answered [1][2]. You *want* to stay, Ines does not mind, and the open question is the deposit, not the rent [3].

        ### What each of you said

        1. **Sam** offered the same rent for a twelve month term [4].
        2. **Ines** is fine either way, as long as the rent does not jump again [3].
           - she asked for a decision by the end of the month
           - she would rather not move in January
        3. **You** wrote yourself a note: ask about the deposit *before* signing [5].

        > the lease renewal is due on the first. can you let me know by then whether you are staying?

        | who | what they want | by when |
        |---|---|---|
        | Sam | a yes or a no on the renewal | the first [1] |
        | Ines | no rent jump, a decision | end of the month [3] |
        | You | the deposit carried over, the boiler checked before winter | before signing [5] |

        The clause on the deposit is on page four of the old contract (see [the listing you saved](https://example.com/Listing/1) for comparison). The dates, as you wrote them in `lease_notes.py`:

        ```python
        deposit_due = Date(2026, 12, 1)   # Sam's deadline
        notice_days = 60 if staying else 30
        print(f"reply by {deposit_due - timedelta(days=notice_days)}, or the old terms roll over for another twelve months")
        ```

        ---

        Next step: reply to Sam with a yes, and ask in the same message whether the deposit carries over [1][4].
        """,
        "cites": [source(1, "whatsapp", "sam (landlord)", "them", "the lease renewal is due on the first. can you let me know by then whether you are staying?"),
                  source(2, "whatsapp", longName, "them", "did you see my message about the renewal? i also need to know about the deposit."),
                  source(3, "imessage", "ines", "them", "fine by me either way, as long as the rent does not jump again."),
                  source(4, "email", "re: renewal terms", "them", "happy to keep the rent where it is for a twelve month term."),
                  source(5, "apple_notes", "lease questions", "me", "ask sam about the renewal date and whether the deposit carries over.")],
        "searched": ["sam lease renewal", "ines staying", "deposit"], "found": 312, "secs": 41.0, "strength": "strong", "error": ""]

    /// The report, and then as much again in plain paragraphs, cut in the middle of a sentence: more than any window holds.
    static let longWriting: String = (report["answer"] as! String) + "\n\n" + (1...7).map { i in
        "Paragraph \(i) of what came after. Sam wrote again on the \(i + 10)th to say the paperwork was ready, and that the rent stays where it is for the term [1]. "
            + "Ines read it the same evening and asked only that the boiler is looked at before winter [3]. You said you would answer both of them by the weekend."
    }.joined(separator: "\n\n") + "\n\nThe one thing still open is the deposit, and whether it carries"

    /// The model's steps, as the engine sends them once each has returned.
    static let steps: [[String: Any]] = [
        ["n": 0, "tool": "first_look", "args": [String: Any](), "found": 38],
        ["n": 1, "tool": "search", "args": ["q": "lease renewal deposit", "sources": ["whatsapp", "imessage"]], "found": 12],
        ["n": 2, "tool": "read_thread", "args": ["id": "T1"], "thread": longName, "src": "whatsapp", "found": 240],
        ["n": 3, "tool": "person", "args": ["name": "Ines"], "found": 1],
        ["n": 4, "tool": "timeline", "args": ["from": "2026-09-01", "to": "2026-11-14"], "found": 31]]

    static let bare: [String: Any] = [
        "answer": "nothing in your archive matches that yet.", "cites": [[String: Any]](),
        "searched": ["allotment waiting list", "plot number"], "found": 0, "secs": 9.4, "error": ""]

    static func turns(_ n: Int) -> [Turn] {
        let qs = [question, followUp, "what did ines say about it?", "so where have i got to on the lease?"]
        let short: [String: Any] = ["answer": "she said she is fine either way.[1] she only asked that the rent does not jump again.",
                                    "cites": [source(3, "whatsapp", "the flat", "them", "fine by me either way, as long as the rent does not jump again.")],
                                    "searched": ["ines lease", "rent"], "found": 12, "secs": 14.0]
        return (0..<n).map { i in Turn(id: i, q: qs[i % qs.count], answer: Answer(i == 0 ? lease : (i == n - 1 && n > 2 ? eight : short), tag: "t\(i)")) }
    }

    /// The key of the first citation in a turn, as the chip that draws it names itself.
    static func firstChip(_ t: Turn) -> String? {
        for b in t.answer?.md ?? [] {
            if let i = MD.words(b.bits).firstIndex(where: { !$0.cites.isEmpty }) { return "\(t.id)/\(b.id)/\(i)/0" }
        }
        return nil
    }

    /// Four turns means four turns: all laid out, in order, the newest at the top of the window and the rest above it,
    /// out of sight but there. Looked back at, an earlier turn is in the window and the newest is below it.
    static func chatCheck(_ screen: String, _ at: String, _ size: CGSize, _ found: [ProbeInfo]) -> [String] {
        var more: [String] = []
        let m = AppModel.shared
        if screen == "home-typing-long", found.contains(where: { $0.name == "ask.row" }) || !m.ask.groups.isEmpty || m.ask.searching {
            more.append("\(at): typing a question shows a list of word matches")
        }
        if screen == "home-exact", !found.contains(where: { $0.name == "ask.row" }) { more.append("\(at): exact search shows no rows") }
        if screen == "chat-links" {
            if found.filter({ $0.name == "chat.link" }).count != 2 { more.append("\(at): the answer's links are not two cards (an address that is not http is never shown)") }
            if !found.contains(where: { $0.name == "refs.open" }) { more.append("\(at): a source with an address has no open action") }
        }
        func has(_ name: String) -> Bool { found.contains { $0.name == name } }
        if screen == "chat-digging", !has("chat.dig") { more.append("\(at): a deeper search is running and nothing says so") }
        if screen == "chat-deeper", !has("chat.first") { more.append("\(at): the first answer cannot be reached") }
        if screen == "chat-one", has("chat.dig") || has("chat.first") { more.append("\(at): a strong answer shows the deeper search") }
        // the title-bar row: every symbol's centre and the middle of the title's x-height on the traffic lights' centre line
        let line = m.lights.y
        for item in found.filter({ $0.name == "bar.item" }) where abs(item.frame.midY - line) > 1 {
            more.append("\(at): a title-bar symbol's centre is at \(item.frame.midY), the traffic lights' at \(line)")
        }
        for name in ["bar.title", "refs.title"] {
            if let t = found.first(where: { $0.name == name }), t.frame.height > 0 {
                let x = TopBar.xCentre(of: t.frame, font: TopBar.tabFont)
                if abs(x - line) > 1 { more.append("\(at): \(name)'s x-height centre is at \(x), the traffic lights' at \(line)") }
            }
        }
        for name in ["plan.day", "sources.heading"] {
            if let p = found.first(where: { $0.name == name }), let ground = found.first(where: { $0.name == "bar.ground" }), abs(p.frame.minX - ground.frame.minX - Grid.edge) > 1 {
                more.append("\(at): \(name) starts at \(p.frame.minX), not on the page's left edge")
            }
        }
        // the conversation is one centred column, no wider than it should be
        if screen.hasPrefix("chat-"), let ground = found.first(where: { $0.name == "bar.ground" }), let input = found.first(where: { $0.name == "chat.input" }) {
            let right = found.first(where: { $0.name == "refs.panel" })?.frame.minX ?? size.width
            let mid = (ground.frame.minX + right) / 2
            if abs(input.frame.midX - mid) > 1.5 { more.append("\(at): the input's centre is at \(input.frame.midX), the main area's at \(mid)") }
            if input.frame.width > Grid.column + 30 { more.append("\(at): the input is \(input.frame.width) wide") }
            for a in found.filter({ $0.name == "chat.answer" }) where a.frame.width > Grid.column + 1 { more.append("\(at): an answer is \(a.frame.width) wide"); break }
            for q in found.filter({ $0.name == "chat.bubble" }) {
                if let a = found.first(where: { $0.name == "chat.answer.edge" }), q.frame.maxX < a.frame.minX + 200 { more.append("\(at): a question is not on the right of the column") }
            }
        }
        if screen.hasPrefix("home-"), !["home-exact"].contains(screen), m.adding == nil, let ground = found.first(where: { $0.name == "bar.ground" }), let input = found.first(where: { $0.name == "chat.input" }) {
            let mid = (ground.frame.minX + size.width) / 2
            if abs(input.frame.midX - mid) > 1.5 { more.append("\(at): the input's centre is at \(input.frame.midX), the main area's at \(mid)") }
            if abs(input.frame.midY - (size.height + ground.frame.maxY) / 2) > size.height * 0.2 { more.append("\(at): the input sits at \(Int(input.frame.midY)) of \(Int(size.height)), not in the middle") }
            if !has("home.greeting") || !has("home.sources") { more.append("\(at): home has no greeting or no line for the archive") }
        }
        if !m.saved.onboarded, has("job.pill") { more.append("\(at): a job pill shows during first run") }
        if screen == "frame-running" {
            if found.filter({ $0.name == "job.pill" }).count != 1 { more.append("\(at): the source being added is not the one pill in the corner") }
            if sizeNameWide(size), found.filter({ $0.name == "side.busy" }).count != 1 || found.filter({ $0.name == "side.unread" }).count != 1 {
                more.append("\(at): the list does not show one chat being answered and one unread")
            }
        }
        if screen == "plan-running", sizeNameWide(size), found.filter({ $0.name == "side.busy" }).count != 1 { more.append("\(at): the chat being answered does not turn in the list while the owner is on another page") }
        if screen.hasPrefix("chat-") || screen == "plan-running", has("job.pill") { more.append("\(at): a pill shows for a chat") }
        if screen == "frame-3", sizeNameWide(size), found.filter({ $0.name == "side.row" }).count != 3 { more.append("\(at): three chats are not three rows") }
        if screen == "frame-60", sizeNameWide(size) {
            if found.filter({ $0.name == "side.row" }).count != 60 { more.append("\(at): sixty chats are not sixty rows") }
            if Set(found.filter({ $0.name == "side.head" }).map { Int($0.frame.minY) }).count != 5 { more.append("\(at): the list is not grouped pinned, today, yesterday, last 7 days, older") }
            if !has("side.tools") { more.append("\(at): a row has no pin, rename and delete") }
        }
        if screen == "frame-collapsed" || screen == "chat-collapsed", has("side.ground") { more.append("\(at): the sidebar shows though it is folded") }
        if screen == "frame-search", sizeNameWide(size), !has("side.search") || found.filter({ $0.name == "side.row" }).count != 2 { more.append("\(at): the search does not narrow the list to two") }
        if ["chat-sources", "chat-eight-cites", "chat-maybe", "chat-thread", "chat-no-cites", "chat-links", "chat-lens"].contains(screen), !has("refs.panel") { more.append("\(at): the sources panel is not open") }
        if screen == "chat-one", has("refs.panel") { more.append("\(at): the sources panel is open though nobody asked") }
        if screen == "chat-maybe", found.filter({ $0.name == "refs.maybe" }).count != 3 || !has("refs.said") || !has("refs.yes") { more.append("\(at): might be related is not three rows, one of them judged") }
        if screen == "chat-thread", !has("peek.card") || has("refs.row") { more.append("\(at): the message in its conversation is not what the panel shows") }
        if screen == "chat-scope" {
            if found.filter({ $0.name == "chat.chip" }).count != 5 { more.append("\(at): the scope is not shown as chips") }
            if m.ask.scope.json["sources"] as? [String] != ["whatsapp", "email"] || !m.ask.deep { more.append("\(at): the scope or the mode is not kept with the chat") }
        }
        if screen == "chat-markdown-end", !has("chat.code.copy") { more.append("\(at): the code has no way to copy it") }
        if screen == "chat-markdown" || screen == "chat-markdown-panel" {
            if !has("chat.table") || !has("chat.code") || found.filter({ $0.name == "chat.cell" }).count != 9 { more.append("\(at): the answer's table and code are not drawn") }
            if let table = found.first(where: { $0.name == "chat.table" }), let input = found.first(where: { $0.name == "chat.input" }), table.frame.width > input.frame.width { more.append("\(at): the table is wider than the column") }
        }
        if screen == "chat-writing-long" || screen == "chat-writing-long-back", let input = found.first(where: { $0.name == "chat.input" }) {
            let caret = found.first { $0.name == "chat.caret" }
            let top = found.first { $0.name == "bar.ground" }?.frame.maxY ?? 52
            if screen == "chat-writing-long" {
                if let c = caret { if c.frame.maxY > input.frame.minY - 8 || c.frame.minY < top { more.append("\(at): the line being written is at \(Int(c.frame.minY)) to \(Int(c.frame.maxY)); the input starts at \(Int(input.frame.minY)): the page does not follow the answer") } }
                else { more.append("\(at): a long answer being written has no caret") }
            } else if let c = caret, c.frame.minY < input.frame.minY, let q = found.first(where: { $0.name == "chat.bubble" }), q.frame.minY < top {
                more.append("\(at): the owner scrolled up, and the page still went to the last line")
            }
        }
        // nothing of a conversation touches the edge of its area: the bubble, the steps line, the answer
        if screen.hasPrefix("chat-") || screen.hasPrefix("person-"), let ground = found.first(where: { $0.name == "bar.ground" }) {
            let right = found.first(where: { $0.name == "refs.panel" })?.frame.minX ?? size.width
            for p in found where ["chat.status", "chat.bubble", "chat.answer", "chat.step", "chat.steps", "chat.usage"].contains(p.name) && p.frame.width > 0 {
                if p.frame.minX < ground.frame.minX + 14 || p.frame.maxX > right - 14 {
                    more.append("\(at): \(p.name) reaches \(Int(p.frame.minX)) to \(Int(p.frame.maxX)) in an area from \(Int(ground.frame.minX)) to \(Int(right)): it touches the edge"); break
                }
            }
        }
        if screen == "chat-markdown-writing", !has("chat.caret") { more.append("\(at): an answer being written has no caret") }
        if screen == "chat-one", has("chat.caret") { more.append("\(at): a finished answer still shows the caret") }
        if screen == "chat-steps-running", !has("chat.status") { more.append("\(at): nothing says what the model is doing") }
        if screen == "chat-steps-done", found.filter({ $0.name == "chat.step" }).count != 5 || !has("chat.usage") || !has("chat.aside") { more.append("\(at): the steps, what they cost and the fallback note are not all shown") }
        if screen == "chat-scope", !has("chat.model") { more.append("\(at): the input has no model control") }
        if screen.hasPrefix("ping-"), !has("ping.panel") || !has("ping.act") || !has("ping.later") { more.append("\(at): the ping is not one sentence, one action and a way out") }
        if screen.hasPrefix("home-") || screen.hasPrefix("frame-") {
            // a chip's words are on home once, whichever list they came from
            let words = m.ask.homeChips.map { $0.text.lowercased() }
            if Set(words).count != words.count { more.append("\(at): a starter is on home twice: \(words)") }
            let chips = found.filter { $0.name == "home.starter" }.count
            if chips > 0, chips != words.count { more.append("\(at): home draws \(chips) starters for \(words.count) different ones") }
        }
        if screen == "home-starters-engine" {
            let n = found.filter { $0.name == "home.starter" }.count
            if n != 7 || found.filter({ $0.name == "home.made" }).count != 2 { more.append("\(at): four lenses, two of their own and plan are not seven chips: \(n)") }
        }
        if screen == "home-starters", found.filter({ $0.name == "home.made" }).count != 2 { more.append("\(at): home does not show two starters made from the profile") }
        if screen == "person-full-names", let a = m.ask.turns.first?.answer {
            let drawn = Set(found.filter { $0.name == "chat.person" }.map { "\(Int($0.frame.minX)),\(Int($0.frame.minY))" }).count, named = mentions(a, m.people)
            if drawn != named || named == 0 { more.append("\(at): \(named) mentions of a person are drawn as \(drawn) things to press: a name is one button, however many words it has") }
        }
        if screen == "chat-draft", found.filter({ $0.name == "chat.act" }).count != 1 { more.append("\(at): a draft offers more than copy") }
        if screen == "chat-months", found.filter({ $0.name == "chat.chip" }).count != 1 { more.append("\(at): a stretch of months is not one chip") }
        if screen == "frame-collapsed-sync", !has("bar.pill") { more.append("\(at): nothing in the bar says what is being read while the sidebar is folded") }
        if screen.hasPrefix("chat-"), screen != "chat-draft", found.contains(where: { $0.name == "chat.act" }), found.filter({ $0.name == "chat.act" }).count < 4, !["chat-error", "chat-stopped"].contains(screen), m.ask.turns.count == 1, m.ask.turns[0].answer?.error.isEmpty == true {
            more.append("\(at): an answer is missing copy, copy as markdown, ask again or save to journal")
        }
        if screen == "chat-editing", !has("chat.editing") { more.append("\(at): nothing says the last message is being changed") }
        if screen == "chat-lens" {
            if found.filter({ $0.name == "lens.row" }).count != 5 || !has("chat.answer") || !has("refs.row") { more.append("\(at): a lens is not drawn as an answer with its list and sources") }
        }
        if screen == "chat-follow-up", found.filter({ $0.name == "chat.queued" }).count != 2 || has("chat.notice") {
            more.append("\(at): the two waiting questions are not in the conversation, or a hint is left under the input")
        }
        if screen == "home-stale" {
            let items = m.shelf.flatMap(\.items)
            for id in ["imessage", "email", "safari_history"] {
                let n = items.filter { $0.source == id }.count
                if n != 1 { more.append("\(at): \(id) is on home \(n) times") }
                if items.first(where: { $0.source == id })?.stale != true { more.append("\(at): \(id) is not marked stale") }
            }
            let disk = items.filter { $0.id == "wait:disk" }
            if disk.count != 1 || !["imessage", "mail", "safari"].allSatisfy({ disk[0].line.contains($0) }) {
                more.append("\(at): there is not one full disk access item naming all three: \(disk.map(\.line))")
            }
        }
        if screen == "home-stale-unlocked" {
            let items = m.shelf.flatMap(\.items)
            if items.contains(where: { $0.id == "wait:disk" || $0.action.contains("switch") }) { more.append("\(at): it asks them to switch on full disk access, which is on") }
            if items.contains(where: { $0.stale }) { more.append("\(at): a source is marked stale for a lock that is not there") }
            if !Set(["imessage", "email", "safari_history"]).isSubset(of: m.staleUnlocked) { more.append("\(at): the sources to read again are \(m.staleUnlocked), not the three stale ones") }
        }
        if screen == "home-stale", !m.staleUnlocked.isEmpty { more.append("\(at): it would read locked sources again while access is off") }
        if screen.hasPrefix("home-"), screen != "home-focus", m.shelfFocus != nil { more.append("\(at): a tile has the focus though nobody pointed at it") }
        if screen.hasPrefix("home-") {
            for g in m.shelf where g.name != "waiting on you" {
                let rows = g.items.map(\.rows)
                if rows != rows.sorted(by: >) { more.append("\(at): \(g.name) is not sorted by count, largest first") }
            }
        }
        if has("shelf.tile") {
            let tiles = found.filter { $0.name == "shelf.tile" || $0.name == "shelf.add" }
            let widths = Set(tiles.map { ($0.frame.width * 2).rounded() / 2 })
            if widths.count > 1 { more.append("\(at): shelf tiles are \(widths.sorted()) wide, not one width") }
            if let w = widths.first, let x0 = tiles.map(\.frame.minX).min(), tiles.contains(where: { abs(($0.frame.minX - x0).truncatingRemainder(dividingBy: w)) > 1 && abs(($0.frame.minX - x0).truncatingRemainder(dividingBy: w) - w) > 1 }) {
                more.append("\(at): shelf tiles are not on one grid of columns")
            }
            if let shelf = found.first(where: { $0.name == "home.shelf" }), !shelf.scrolls, let low = tiles.map(\.frame.maxY).max(), low > size.height - 18 {
                more.append("\(at): the last shelf row ends at \(Int(low)) of \(Int(size.height)): it touches the bottom of the window")
            }
            if m.shelfTotal.contains("  ") || m.shelfTotal.hasSuffix("now") || !m.shelfTotal.hasSuffix(".") { more.append("\(at): the home line is not one clean sentence: \(m.shelfTotal)") }
        }
        if screen == "sources-refreshing" {
            if has("bar.doing") { more.append("\(at): the indicator is on while nothing is being read") }
            if SourcesView.total(m.engine) != m.engine.totalRows || m.engine.totalRows == 0 { more.append("\(at): the count is not the archive total") }
        }
        if screen == "sources", found.filter({ $0.name == "sources.icon" }).count < 8 { more.append("\(at): the rows do not use the shelf's icon") }
        if screen == "plan-empty", !has("plan.what") { more.append("\(at): the empty page does not say what it does") }
        if screen == "plan-empty", has("plan.looking") { more.append("\(at): it says it is looking when it is not") }
        if screen == "plan-looking", !has("plan.looking") { more.append("\(at): nothing says it is looking") }
        if screen == "add-site-ask", Set(found.filter({ $0.name == "add.choice" }).map { Int($0.frame.minX) }).count != 2 || m.adding.map({ a in { if case .result(let r) = a.stage { return r.sentence.contains("40 pages since 2018") } else { return false } }() }) != true {
            more.append("\(at): a site's trial does not say what it found and offer the engine's two choices")
        }
        if screen == "add-note", !found.contains(where: { $0.name == "add.note" }) { more.append("\(at): their own notes have no page to write on") }
        if screen == "add-nothing", let h = found.first(where: { $0.name == "add.hint" }), h.frame.height < 30 { more.append("\(at): with nothing found the panel does not say what can be typed") }
        if screen == "add-kinds", Set(found.filter({ $0.name == "add.result" }).map { Int($0.frame.minY) }).count != 6 { more.append("\(at): the six kinds of thing to add are not six rows") }
        if screen.hasPrefix("add-"), m.tab != .sources { more.append("\(at): the add panel is shown over a page that is not sources") }
        if screen == "add-looking", !m.adding.map({ AddSheet.hint(query: $0.query, searching: $0.searching).hasPrefix("looking") })! { more.append("\(at): the add panel says nothing was found before the engine answered") }
        guard screen == "chat-four" || screen == "chat-four-earlier" else { return more }
        let qs = found.filter { $0.name == "chat.question" }.sorted { $0.group.localizedStandardCompare($1.group) == .orderedAscending }
        guard qs.count == 4 else { return ["\(at): \(qs.count) turns are laid out, not 4"] }
        var out: [String] = []
        let ys = qs.map { $0.frame.minY }
        if zip(ys, ys.dropFirst()).contains(where: { $0 >= $1 }) { out.append("\(at): the turns are not in order, oldest first: \(ys.map { Int($0) })") }
        let inputTop = found.first { $0.name == "chat.input" }?.frame.minY ?? size.height
        if screen == "chat-four" {
            if ys[3] < 52 || ys[3] > 120 { out.append("\(at): the newest question sits at \(Int(ys[3])), not at the top of the window") }
            if qs[2].frame.maxY > 60 { out.append("\(at): an earlier turn is still in view under the top bar (\(Int(qs[2].frame.maxY)))") }
            if qs[0].frame.maxY > 52 || ys[3] - ys[0] < 300 { out.append("\(at): the first turn is not above the window (\(Int(ys[0])) to \(Int(qs[0].frame.maxY))): there is nothing to scroll back to") }
        } else {
            if ys[0] < 52 || ys[0] > inputTop { out.append("\(at): the first question is not in the window (\(Int(ys[0])))") }
            if ys[3] < 120 { out.append("\(at): still scrolled to the newest turn (\(Int(ys[3])))") }
        }
        return out
    }

    static func chatScreens(_ m: AppModel, main: @escaping (Tab) -> Void) -> [(String, () -> Void)] {
        func chat(_ turns: [Turn], asking: Bool = false, _ more: () -> Void = {}) {
            main(.home)
            m.ask.openSources = []
            m.ask.openHow = []
            m.ask.openMaybe = []
            m.ask.openCite = nil
            m.ask.flash = nil
            m.ask.peek = nil
            m.ask.goTo = nil
            m.ask.turns = turns
            m.ask.asking = asking
            m.ask.askedAt = Date()
            more()
        }
        return [
            ("chat-one", { chat(turns(1)) }),
            ("chat-asking", { chat([Turn(id: 0, q: question)], asking: true) }),
            ("chat-reading", {                                           // the engine has said what it is reading
                var t = Turn(id: 0, q: question)
                t.live = Live(phase: "read", rows: Invented.found, sources: ["whatsapp", "email", "apple_notes", "slack", "imessage", "claude_code"], threads: ["Sam (landlord)", longName])
                chat([t], asking: true)
            }),
            ("chat-writing", {                                           // the words as they are written, with the first citation in
                var t = Turn(id: 0, q: question)
                t.live = Live(phase: "read", rows: 250, sources: ["whatsapp"], text: "Not yet. Sam asked about the renewal twice [1] and you have not written back. He first raised it on the fourth",
                              cites: [Answer.cite(cite(1, "sam (landlord)", "the lease renewal is due on the first"), 0, prefix: "t0")!])
                chat([t], asking: true)
            }),
            ("chat-maybe", {                                             // a weak answer, with what might be related unfolded and one row judged
                var d: [String: Any] = ["answer": "You have not said. Sam asked twice [1].", "cites": [cite(1, "sam (landlord)", "the lease renewal is due on the first")],
                                        "searched": ["lease"], "error": "", "strength": "weak"]
                d["maybe"] = [cite(2, "lease questions", "ask sam about the renewal date and whether the deposit carries over to the new term, and what notice he needs if we go."),
                              cite(3, longName, "the committee renews the field lease every third year."), cite(4, "flat hunting", "saw two places near the canal.")]
                chat([Turn(id: 0, q: question, answer: Answer(d, tag: "t0"))]) { m.ask.sourcesFor = 0; m.ask.judged = ["t0m:1:W3": false] }
            }),
            ("chat-digging", {                                           // a partial answer, with a deeper search running under it
                var t = Turn(id: 0, q: question, answer: Answer(["answer": "Partly. Sam asked twice [1].", "cites": [cite(1, "sam (landlord)", "the lease renewal is due on the first")], "strength": "partial"], tag: "t0"))
                t.dig = "reading your whole thread with sam, and the note you wrote about the deposit"
                chat([t])
            }),
            ("chat-deeper", {                                            // the deeper answer in its place, the first one a click away
                var t = Turn(id: 0, q: question, answer: Answer(["answer": "Yes. You told Sam on the ninth that you are staying [1].", "cites": [cite(2, "sam (landlord)", "we are staying, will sign next week")],
                    "strength": "strong", "deep": true, "dug": [["how": "thread", "threads": 2], ["how": "names"], ["how": "dates"]]], tag: "t0d"))
                t.first = Answer(["answer": "Partly. Sam asked twice.", "strength": "partial"], tag: "t0")
                t.streamed = true
                chat([t])
            }),
            ("chat-stopped", {
                var a = Answer(["answer": "Not yet. Sam asked about the renewal twice"], tag: "t0")!
                a.stopped = true
                var t = Turn(id: 0, q: question, answer: a)
                t.streamed = true
                chat([t])
            }),
            ("chat-follow-up", {                                         // the state the bug was in: one answered, the next being read
                chat(turns(1) + [Turn(id: 1, q: followUp)], asking: true) { m.ask.queue = ["and the boiler", veryLong] }
            }),
            ("chat-four", { chat(turns(4)) }),
            ("chat-four-earlier", {                                      // the same chat, looked back at: a row under the first answer
                chat(turns(4)) { m.ask.goTo = 0 }
            }),
            ("chat-eight-cites", {
                chat([Turn(id: 0, q: "where have i got to on the lease?", answer: Answer(eight, tag: "t0"))]) {
                    m.ask.sourcesFor = 0
                }
            }),
            ("chat-sources", { chat(turns(1)) { m.ask.sourcesFor = 0; m.ask.flash = "t0:1:R2" } }),
            ("chat-thread", { let t = turns(1); chat(t) { m.ask.sourcesFor = 0; m.ask.thread = threadProof(t[0]) } }),
            ("chat-peek", { let t = turns(1); chat(t) { m.ask.peek = firstChip(t[0]) } }),
            ("chat-no-cites", {
                chat([Turn(id: 0, q: "which plot number did the allotment give me?", answer: Answer(bare, tag: "t0"))]) { m.ask.sourcesFor = 0 }
            }),
            ("chat-error", {
                chat(turns(1) + [Turn(id: 1, q: followUp, answer: .failure("no plan is signed in, so context cannot read for an answer. sign in to claude code or codex once."))])
            }),
            ("plan-running", { chat([Turn(id: 0, q: question)], asking: true) { m.tab = .plan } }),      // the owner left for another page; the answer is still being read
            ("chat-collapsed", { chat(turns(2)) { m.saved.sidebar = false } }),
            ("chat-steps-running", {                                     // the model at work: the step it is on, in words, with its source
                var t = Turn(id: 0, q: question)
                var live = Live(phase: "agent")
                for s in steps.prefix(3) { live.take(["step": s], tag: "t0") }
                t.live = live
                chat([t], asking: true)
            }),
            ("chat-steps-done", {                                        // "worked for 41 s · 5 steps", unfolded, and a note that a fallback model wrote it
                var d = report
                d["steps"] = steps
                d["usage"] = ["calls": 4, "tools": 5, "in": 24_000, "out": 1_500]
                d["fallback"] = "Written by a quicker model: your plan's limit was reached."
                chat([Turn(id: 0, q: question, answer: Answer(d, tag: "t0"))]) { m.ask.openHow = [0] }
            }),
            ("chat-markdown", { chat([Turn(id: 0, q: "where do i stand on the lease? give me the whole picture", answer: Answer(report, tag: "t0"))]) }),
            ("chat-markdown-end", {                                      // the lower half of the same answer: the table, a link, the code, the rule
                var d = report
                let text = report["answer"] as! String
                d["answer"] = String(text[text.range(of: "| who")!.lowerBound...])
                chat([Turn(id: 0, q: "where do i stand on the lease?", answer: Answer(d, tag: "t0"))])
            }),
            ("chat-markdown-panel", { chat([Turn(id: 0, q: "where do i stand on the lease?", answer: Answer(report, tag: "t0"))]) { m.ask.sourcesFor = 0 } }),
            ("chat-markdown-writing", {                                  // markdown as it is written: a heading, bold, a list half way, the caret
                var t = Turn(id: 0, q: question)
                let text = report["answer"] as! String
                t.live = Live(phase: "read", rows: 350, sources: ["whatsapp", "imessage"], text: String(text.prefix(430)),
                              cites: (report["cites"] as! [[String: Any]]).prefix(3).enumerated().map { Answer.cite($1, $0, prefix: "t0")! })
                chat([t], asking: true)
            }),
            ("chat-writing-long", {                                      // an answer longer than the window, being written: its last line stays above the input
                var t = Turn(id: 0, q: question)
                t.live = Live(phase: "read", rows: 350, sources: ["whatsapp", "imessage"], text: longWriting,
                              cites: (report["cites"] as! [[String: Any]]).enumerated().map { Answer.cite($1, $0, prefix: "t0")! })
                chat([t], asking: true)
            }),
            ("chat-writing-long-back", {                                 // the same, after the owner scrolled up to read: the page stays where the owner put it
                var t = Turn(id: 0, q: question)
                t.live = Live(phase: "read", rows: 350, sources: ["whatsapp", "imessage"], text: longWriting,
                              cites: (report["cites"] as! [[String: Any]]).enumerated().map { Answer.cite($1, $0, prefix: "t0")! })
                chat([t], asking: true) { m.ask.follow = false }
            }),
            ("chat-editing", { chat(turns(2)) { m.ask.editLast() } }),               // up-arrow: the last question is back in the input
            ("chat-scope", {                                             // the question narrowed: two sources, a stretch of time, two people; deep
                chat(turns(1)) {
                    var s = Scope()
                    s.sources = ["whatsapp", "email"]
                    s.after = Composer.ranges()[1].after
                    s.people = ["sam", "ines okafor-lindqvist"]
                    m.ask.scope = s
                    m.ask.deep = true
                    m.models = ModelsReport(modelsReport)
                    m.ask.model = "large"
                    m.ask.draft = "and what did they say about the deposit"
                }
            }),
            ("chat-lens", {                                              // a ready-made question: the same turn as any answer, with its list
                chat([Turn(id: 0, q: "intros i promised", answer: lensAnswer.0, lensID: "intros", items: lensAnswer.1)]) { m.ask.sourcesFor = 0 }
            }),
            ("home-stale", {                                             // three sources hold rows from last time but cannot be read now
                main(.home)
                for id in ["imessage", "email", "safari_history"] {
                    m.engine.states[id] = .kept(rows: Invented.kept, why: "blocked by macOS: grant Full Disk Access to the app running this")
                }
            }),
            ("home-stale-unlocked", {                                    // the same three, but macos lets the app in: nothing to switch on
                main(.home)
                m.access = true
                for id in ["imessage", "email", "safari_history"] {
                    m.engine.states[id] = .kept(rows: Invented.kept, why: "blocked by macOS: grant Full Disk Access to the app running this")
                }
            }),
            ("sources-refreshing", {                                     // a refresh is alive but nothing is being read
                main(.sources)
                m.engine.syncing = true
                m.engine.ticking = true
            }),
            ("plan-looking", {
                main(.plan)
                m.journal.text = "today is the pricing page. the yearly toggle goes on by default and each plan gets one line under the price.\n"
                m.journal.relating = true
            }),
            ("add-looking", { main(.sources); let a = AddModel(engine: m.engine); a.query = "discord"; a.cancel(); m.adding = a }),      // asked, not yet answered
            ("chat-links", {                                             // "find me the link": addresses in the answer, link cards, rows that open
                chat([Turn(id: 0, q: "link to my allotment talk", answer: Answer(found, tag: "t0"))]) { m.ask.sourcesFor = 0 }
            }),
            ("chat-long-question", { chat([Turn(id: 0, q: veryLong, answer: Answer(lease, tag: "t0"))]) { m.ask.draft = veryLong } }),
        ]
    }
}

extension LayoutTest {
    /// The sidebar is drawn at the two wider sizes; the smallest window folds it by itself.
    static func sizeNameWide(_ size: CGSize) -> Bool { size.width >= Grid.narrow }

    /// The frame itself: the list of chats empty, short and long, folded, searched, and with things running.
    static func frameScreens(_ m: AppModel, main: @escaping (Tab) -> Void, lenses: [LensInfo]) -> [(String, () -> Void)] {
        let titles = ["the lease and the deposit", "what ines said about moving", "open day talk recording", "intros i promised", "boiler repair, who pays",
                      "a title that is far too long to fit in the list and has to be cut at the edge", "pricing page: yearly toggle", "checkout bug"]
        func chats(_ n: Int) {
            m.ask.seed((0..<n).map { i in [Turn(id: 1000 + i, q: titles[i % titles.count], answer: Answer(i % 3 == 0 ? lease : bare, tag: "t\(1000 + i)"))] }, ago: n > 10 ? 3600 * 7 : 3600)
            for i in m.ask.chats.indices { m.ask.chats[i].title = titles[i % titles.count] }
            if n > 10 {
                // spread over the days whatever the hour: two just now, some yesterday, some this week, the rest older
                let day0 = Calendar.current.startOfDay(for: Date())
                for i in m.ask.chats.indices {
                    let k = n - 1 - i                   // 0 is the newest
                    let at = k < 3 ? Date().addingTimeInterval(-Double(k + 1)) : (k < 8 ? day0.addingTimeInterval(-3600 * Double(k)) : day0.addingTimeInterval(-86400 * Double(k - 6)))
                    m.ask.chats[i].updated = at
                    m.ask.chats[i].created = at
                }
                m.ask.chats[n - 2].pinned = true
                m.ask.chats[n - 5].pinned = true
            }
        }
        return [
            ("frame-0", { main(.home); m.ask.lenses = lenses }),
            ("frame-3", { main(.home); m.ask.lenses = lenses; chats(3) }),
            ("frame-60", { main(.home); m.ask.lenses = lenses; chats(60) }),
            ("frame-60-open", { main(.home); chats(60); m.ask.open(m.ask.ordered[3].id) }),
            ("frame-collapsed", { main(.home); m.ask.lenses = lenses; chats(3); m.saved.sidebar = false }),
            ("frame-search", { main(.home); chats(12); m.chatSearch = "lease" }),
            ("frame-running", {                                          // one chat being answered, one that landed unread, a source being worked out
                main(.home)
                chats(4)
                m.ask.busy = [m.ask.chats[1].id]
                m.ask.chats[2].unread = true
                let a = AddModel(engine: m.engine)
                a.picked = Found(id: "granola", name: "granola", kind: "app", installed: true, iconPath: "", known: false)
                a.phases = ["looking at where granola keeps its data"]
                a.stage = .working
                m.adding = a
                m.addHidden = true
            }),
            ("frame-card", {
                main(.home); m.ask.lenses = lenses; chats(3)
                m.card = Card(["id": "2026-11-17-promised-1", "kind": "promised", "state": "unread",
                               "line": "You told Sam you would come back to him about the lease after checking with the others. That was sixteen days ago, and the renewal is due on the first.",
                               "cite": cite(2, "sam (landlord)", "I will check with the others and come back to you."), "action": ["label": "reply", "thread": "W2"]])
            }),
            ("frame-sources-collapsed", { main(.sources); m.saved.sidebar = false }),
            ("frame-settings-collapsed", { main(.settings); m.saved.sidebar = false; m.settings.loaded = true; m.settings.answered = false; m.settings.raw = [:]; m.settings.apps = [] }),
            ("frame-plan-collapsed", { main(.plan); m.saved.sidebar = false }),
        ]
    }
}

// MARK: `context --asktest`

/// Asks a stand-in engine question after question, the way the chat does, and checks that each one ends:
/// an answer or a plain sentence, never a turn left waiting. The stand-in is a small python file written to a
/// temporary folder; no real data is read, no model is called and nothing is drawn.
enum AskTest {
    static let stub = #"""
import json, sys, time
args = sys.argv[1:]
cmd = args[0] if args else ""
if cmd == "connect":
    a = args[1] if len(args) > 1 else ""
    if a == "--search":
        time.sleep(0.6)
        print(json.dumps([{"id": "discord", "name": "Discord", "kind": "app", "installed": True, "app_path": "/Applications/Discord.app", "known": False}] if "disc" in args[2] else
                         [{"id": "nope", "name": "Nope", "kind": "app", "installed": True, "known": False}] if "nope" in args[2] else []))
    elif a == "--enable":
        print(json.dumps({"id": args[2], "enabled": True}))
    else:
        print("@" + json.dumps({"src": a, "phase": "looking at where it keeps its data"}), flush=True)
        time.sleep(0.2)
        print("@" + json.dumps({"src": a, "phase": "trying a reader on a sample"}), flush=True)
        print(json.dumps({"id": a, "name": a, "state": "ready", "how": "found its messages in its app folder", "sample": {"rows": 12, "since": "2025-03"}} if a == "discord"
                         else {"id": a, "name": a, "state": "cannot", "detail": "its data is kept encrypted"}))
    sys.exit(0)
if cmd == "title":
    print(json.dumps({"title": "Maya and Friday."}))
    sys.exit(0)
if cmd == "lens":
    time.sleep(0.2)
    print(json.dumps({"title": "intros i promised", "summary": "You promised two.", "searched": ["intro"], "error": "", "items": [
        {"what": "introduce maya to jonas", "who": "maya", "when": "2026-11-03", "status": "open", "cite": {"id": "L1", "src": "whatsapp", "ts": "2026-11-03T10:00:00Z", "thread": "maya", "who": "me", "text": "i'll intro you"}},
        {"what": "introduce priya to sam", "who": "priya", "when": "2026-11-04", "status": "open", "cite": {"id": "L2", "src": "whatsapp", "ts": "2026-11-04T10:00:00Z", "thread": "priya", "who": "me", "text": "will connect you two"}}]}))
    sys.exit(0)
if cmd != "answer":
    print("{}"); sys.exit(0)
q = args[1] if len(args) > 1 else ""
hist = json.loads(args[args.index("--history") + 1]) if "--history" in args else []
ok = {"answer": "yes. you told her on friday.[1] she wrote back the same day.[2]",
      "cites": [{"id": "A1", "src": "whatsapp", "ts": "2026-11-03T10:00:00Z", "thread": "maya", "who": "me", "text": "friday works", "url": ""},
                {"id": "A2", "src": "x_bookmarks", "ts": "2026-11-03T12:00:00Z", "thread": "@someone", "who": "saved", "text": "a saved post", "url": "https://example.com/p"}],
      "searched": ["maya friday"], "found": len(hist), "confidence": 4, "secs": 1.0, "error": "",
      "echo": {"n": len(hist), "marks": any("[" in h.get("a", "") for h in hist), "longest": max([len(h.get("a", "")) for h in hist] or [0])}}
stream = "--stream" in args
def say(ok):
    if not stream:
        print(json.dumps(ok)); return
    print(json.dumps({"phase": "plan"}), flush=True)
    print(json.dumps({"phase": "read", "rows": 3, "sources": ["whatsapp"]}), flush=True)
    for w in ok["answer"].split(" ")[:6]:
        print(json.dumps({"delta": w + " "}), flush=True)
    print(json.dumps({"done": ok}), flush=True)
if "mode:noise" in q:
    print("warning: something on stdout first"); sys.stderr.write("x" * 200000); say(ok); print("done.")
elif "mode:pretty" in q:
    print("note"); print(json.dumps(ok, indent=2)) if not stream else say(ok)
elif "mode:big" in q:
    ok["answer"] = "long. " + "word " * 80000; say(ok)
elif "mode:garbage" in q:
    print("this is not json at all")
elif "mode:empty" in q:
    pass
elif "mode:crash" in q:
    raise RuntimeError("boom")
elif "mode:error" in q:
    print(json.dumps({"error": "no plan is signed in"} if stream else {"answer": "", "cites": [], "searched": [], "found": 0, "error": "no plan is signed in"}))
elif "mode:exception" in q:
    print(json.dumps({"error": "Expecting value: line 1 column 1 (char 0)"} if stream else {"answer": "", "cites": [], "error": "Expecting value: line 1 column 1 (char 0)"}))
elif "mode:blank" in q:
    say({"answer": "", "cites": [], "error": ""})
elif "mode:slow" in q:
    time.sleep(30); say(ok)
elif "mode:hold" in q:        # a child that keeps the pipe open after this process is gone
    import subprocess
    subprocess.Popen(["sleep", "30"]); time.sleep(30)
else:
    time.sleep(0.3); say(ok)
"""#

    static func run() -> Never {
        let fm = FileManager.default
        let tmp = NSTemporaryDirectory() + "context-asktest-\(ProcessInfo.processInfo.processIdentifier)"
        try? fm.createDirectory(atPath: tmp + "/repo/ctx", withIntermediateDirectories: true)
        try? fm.createDirectory(atPath: tmp + "/home", withIntermediateDirectories: true)
        try? stub.write(toFile: tmp + "/repo/ctx/__main__.py", atomically: true, encoding: .utf8)
        setenv("CONTEXT_DEBUG", "still", 1)
        setenv("CTX_HOME", tmp + "/home", 1)
        setenv("CONTEXT_REPO", tmp + "/repo", 1)
        ChatStore.force = true          // the chats are written, to this throwaway folder
        DispatchQueue.global().asyncAfter(deadline: .now() + 120) { print("asktest: timed out"); exit(3) }
        var failed = 0
        func check(_ name: String, _ ok: Bool) { print(ok ? "ok   " : "FAIL ", name); if !ok { failed += 1 } }
        func wait(_ seconds: Double, until done: () -> Bool) {
            let end = Date().addingTimeInterval(seconds)
            while !done(), Date() < end { RunLoop.current.run(until: Date().addingTimeInterval(0.02)) }
        }

        // the text of an answer, taken apart
        let a = Answer(["answer": "Not yet.[1][2] He asked on the 4th, v1.2 of the lease. [3]\n- one thing[2]\n- another [9]",
                        "cites": [["id": "a"], ["id": "b"], ["id": "c"]]], tag: "t0")!
        check("markers leave the text for history", Answer.strip(a.text) == "Not yet. He asked on the 4th, v1.2 of the lease.\n- one thing\n- another")
        check("first sentence stands alone with its markers", a.blocks.first.map { $0.lead && $0.pieces == [.text("Not yet."), .cite(1), .cite(2)] } ?? false)
        check("a full stop inside a number is not an end", a.blocks.count == 4 && a.blocks[1].plain.contains("v1.2 of the lease."))
        check("list lines stay lines", a.blocks[2].bullet && a.blocks[3].bullet)
        check("a marker past the list is dropped", !a.blocks[3].hasCites && a.blocks[3].plain.trimmingCharacters(in: .whitespaces) == "another")
        check("a marker rides on the word before it", a.blocks[0].words.map(\.word) == ["Not", "yet."] && a.blocks[0].words[1].cites == [1, 2])
        let p = Answer(["answer": "it interests him [1]. she agreed [2][3], more or less [1]! (as he said [2]) done.", "cites": [["id": "a"], ["id": "b"], ["id": "c"]]], tag: "t")!
        let pw = p.blocks.flatMap(\.words)
        check("punctuation follows the word, then the chip", pw.contains { $0.word == "him." && $0.cites == [1] } && pw.contains { $0.word == "agreed," && $0.cites == [2, 3] }
              && pw.contains { $0.word == "less!" && $0.cites == [1] } && pw.contains { $0.word == "said)" && $0.cites == [2] }
              && !pw.contains { [".", ",", "!", ")"].contains($0.word) })
        // markdown, taken apart
        let m = Answer(LayoutTest.report, tag: "t")!
        let kinds = m.md.map(\.kind)
        check("markdown: headings, paragraphs, lists, a quote, a table, code and a rule are blocks", kinds.contains(.heading) && kinds.contains(.item) && kinds.contains(.quote)
              && kinds.contains(.table) && kinds.contains(.code) && kinds.contains(.rule) && m.md.first?.kind == .heading && m.md.first?.level == 2)
        check("markdown: the answer keeps its case, and code keeps every character", m.text.contains("Sam") && m.md.first { $0.kind == .code }?.code.contains("deposit_due = Date(2026, 12, 1)") == true)
        let table = m.md.first { $0.kind == .table }
        check("markdown: a table has its head, its rows, and citations in its cells", table?.header.count == 3 && table?.rows.count == 3 && table?.rows[0][2].contains(.cite(1)) == true)
        let bits = MD.inline("**Sam** asked *twice* [1], see `lease.pdf` and [the listing](https://example.com/L/1)[2]. ~~old~~ 2 * 3 * 4 and snake_case_name stay.", cites: 2)
        let spans = bits.compactMap { b -> Styled? in if case .span(let s) = b { return s } else { return nil } }
        check("markdown: bold, italic, code, strike and links are styles, not signs", spans.contains { $0.text == "Sam" && $0.bold } && spans.contains { $0.text == "twice" && $0.italic }
              && spans.contains { $0.text == "lease.pdf" && $0.code } && spans.contains { $0.text == "the listing (example.com)" && $0.link == "https://example.com/L/1" }      // the real host is written after a link's words
              && spans.contains { $0.text == "old" && $0.strike } && MD.plain(bits).contains("2 * 3 * 4 and snake_case_name stay.") && !MD.plain(bits).contains("**"))
        let mw = MD.words(bits)
        check("markdown: a citation rides on the word before it, and punctuation after bold sits tight", mw.contains { $0.text == "twice," && $0.cites == [1] }
              && mw.first { $0.text == "asked" }?.glue == false && mw.contains { $0.text == "(example.com)." && $0.cites == [2] })
        check("markdown: a marker past the list is dropped, an open sign is kept as typed", MD.plain(MD.inline("more [9] and **half", cites: 2)) == "more and **half")
        check("markdown: a javascript link is never a link", !MD.inline("[x](javascript:alert(1))", cites: 0).contains { if case .span(let s) = $0 { return s.link != nil } else { return false } })
        check("markdown: plain sentences are still set as short paragraphs, the first alone", !MD.isMarkdown(a.text) && a.md.first?.lead == true && a.md.count == a.blocks.count && MD.isMarkdown(m.text))
        check("markdown: an unfinished table or code block while writing is still blocks", MD.parse("## so far\n\n| a | b |\n|---|---|\n| 1 |", cites: 0).last?.kind == .table
              && MD.parse("text\n\n```swift\nlet x", cites: 0).last?.code == "let x")
        // steps and models, in the engine's shapes
        var lv = Live()
        lv.take(["step": ["n": 1, "tool": "search", "args": ["q": "lease", "sources": ["whatsapp", "telegram"]]]], tag: "t")
        lv.take(["step": ["n": 1, "tool": "search", "args": ["q": "lease", "sources": ["whatsapp", "telegram"]], "found": 12]], tag: "t")
        lv.take(["step": ["n": 2, "tool": "read_thread", "args": ["id": "x"], "thread": "Sam", "src": "whatsapp"]], tag: "t")
        check("steps: a step said twice is one step, with what it found", lv.steps.count == 2 && lv.steps[0].found == 12 && lv.steps[0].line == "searching whatsapp and telegram for \u{201C}lease\u{201D}"
              && lv.steps[1].line == "reading your thread with Sam")
        lv.take(["delta": "half an answer"], tag: "t"); lv.take(["retract": true], tag: "t")
        check("steps: a retraction puts the text away and keeps the steps", lv.text.isEmpty && lv.steps.count == 2)
        check("steps: worked for, in words", StepsLine.summary(secs: 9.2, steps: 5) == "worked for 9 s  ·  5 steps" && StepsLine.cost(Usage(["in": 24_000, "out": 800]), steps: lv.steps) == "1 search  ·  1 thread read  ·  24k tokens read  ·  800 written")
        let rep = ModelsReport(LayoutTest.modelsReport)
        check("models: presets in order, the recommended one tagged, jobs with reasons", rep?.presets.map(\.id) == ["balanced", "best", "lean"] && rep?.presets[0].recommended == true
              && rep?.roles.map(\.id) == ModelsReport.jobs && rep?.plans == ["plan a", "plan b"] && rep?.runsOn.contains("balanced (recommended)") == true)
        check("the status line is gone before the answer starts to arrive", ChatTurn.statusOut > 0 && ChatTurn.statusOut < ChatTurn.answerIn)
        // a question box, not a word matcher
        let box = AskModel(home: URL(fileURLWithPath: tmp + "/home"))
        box.query = "link to my allotment talk"
        check("typing a question looks nothing up", !box.searching && box.groups.isEmpty)
        check("exact search leaves small words out", AskModel.terms("link to my allotment talk") == ["allotment", "talk"] && AskModel.terms("to my") == ["to", "my"])
        try? ["{\"id\": \"M1\", \"src\": \"whatsapp\", \"ts\": \"2026-11-03T10:00:00Z\", \"thread\": \"maya\", \"who\": \"me\", \"text\": \"the allotment talk is up\"}",
              "{\"id\": \"M2\", \"src\": \"whatsapp\", \"ts\": \"2026-11-04T10:00:00Z\", \"thread\": \"jonas\", \"who\": \"them\", \"text\": \"the allotments forum is talking about it on linkedin\"}"]
            .joined(separator: "\n").appending("\n").write(toFile: tmp + "/home/messages.jsonl", atomically: true, encoding: .utf8)
        let exactHits = Jsonl.search(home: URL(fileURLWithPath: tmp + "/home"), query: "link to my allotment talk", stop: Flag()).flatMap(\.hits)
        check("exact search matches whole words only", exactHits.map(\.id) == ["message:M1"])
        let cased = Answer(["answer": "It Is Here: https://video.example.com/Watch?v=AbC123. And (https://example.com/A/b)."], tag: "t")!
        check("an answer keeps the engine's own capitals, in words and in addresses", cased.text.contains("https://video.example.com/Watch?v=AbC123") && cased.text.hasPrefix("It Is Here"))
        let lw = cased.blocks.flatMap(\.words).compactMap { Answer.link(in: $0.word) }
        check("addresses are links, without the full stop or bracket stuck to them", lw.map(\.url.absoluteString) == ["https://video.example.com/Watch?v=AbC123", "https://example.com/A/b"] && lw.map(\.tail) == [".", ")."])
        check("a long address is cut in the middle", Answer.short("https://www.video.example.com/watch?v=Qw3rTy9ZxA&list=PLmadeUpListIdThatIsQuiteLong0123456789").count == 44
              && Answer.short("https://example.com/a/") == "example.com/a")
        // an address that came only from someone else's message arrives as plain words, and stays words
        let theirs = Answer(["answer": "The form is at forms.example.com (an address from someone else's message: not opened from here). Ask Sam first."], tag: "t")!
        check("an address from someone else's message is plain text, never a link", theirs.blocks.flatMap(\.words).compactMap { Answer.link(in: $0.word) }.isEmpty && theirs.links.isEmpty
              && theirs.text.contains("forms.example.com (an address from someone else's message: not opened from here)") && !Saved().linksFromOthers
              && Answer.quickHelp(lookDeeper: false).contains("does not look deeper") && Answer.quickHelp(lookDeeper: true).contains("looks deeper by itself"))
        check("only http addresses are ever links", Answer.web("javascript:alert(1)") == nil && Answer.web("file:///etc/passwd") == nil && Answer(LayoutTest.found, tag: "t")!.links.count == 2)
        // the wiki follows the same rule: an address is a link only when one of the owner's own rows holds it
        let wikiText = "The form is [here](https://forms.example.com/f?id=9) and at https://forms.example.com/f?id=9. Notes at https://www.notes.example.org/plot/, see `https://code.example.com/x`."
        let ownRow: [String: Any] = ["src": "apple_notes", "open": "https://notes.example.org/plot", "rows": [["who": "me", "me": true, "here": true, "text": "plot notes"]]]
        let theirRow: [String: Any] = ["src": "whatsapp", "rows": [["who": "them", "me": false, "here": true, "text": "fill in https://forms.example.com/f?id=9"]]]
        let vouched = WikiLinks(mine: WikiLinks.mine(inThread: ownRow).union(WikiLinks.mine(inThread: theirRow)))
        let gated = WikiText.gate(wikiText, vouched), shut = WikiText.gate(wikiText, WikiLinks()), wide = WikiText.gate(wikiText, WikiLinks(widen: true))
        check("wiki: an address only someone else's message holds is its site's name, never a link",
              gated.contains("The form is here (forms.example.com) and at forms.example.com.") && !gated.contains("](https://forms") && WikiLinks.mine(inThread: theirRow).isEmpty)
        check("wiki: an address the owner's own row holds is a link, bare or not; code is left as written",
              gated.contains("[https://www.notes.example.org/plot/](https://www.notes.example.org/plot/),") && gated.contains("`https://code.example.com/x`")
              && shut.contains("Notes at www.notes.example.org,") && !shut.contains("]("))
        check("wiki: with links from others on, every web address is a link", wide.contains("[here](https://forms.example.com/f?id=9)") && wide.contains("[https://forms.example.com/f?id=9](https://forms.example.com/f?id=9)."))
        check("wiki: the rows beside an address are the ones looked up", WikiText.rows(in: "a [[r:W1]] b [[c:k]] [[r:W2]] [[r:W1]]") == ["W1", "W2"]
              && WikiText.addresses(in: "x https://a.example.com/b. y <https://c.example.com/d>") == ["a.example.com/b", "c.example.com/d"])
        // what the reader would open from a line or a cell: a link's address, or a word that is an address (MDWordView)
        func gateOpens(_ bits: [Bit]) -> [String] {
            MD.words(bits).compactMap { w -> String? in
                if let l = w.span.link { return Answer.web(l)?.host }
                return w.span.code ? nil : Answer.link(in: w.text)?.url.host
            }
        }
        func gateLines(_ b: MDBlock) -> [[Bit]] { [b.bits] + b.header + b.rows.flatMap { $0 } }
        func gateOpensAll(_ blocks: [MDBlock]) -> [String] { blocks.flatMap(gateLines).flatMap(gateOpens) }
        func gateSaid(_ b: MDBlock) -> String { gateLines(b).map(MD.plain).joined(separator: " | ") }
        // a refused address never opens from the wiki: not as a link's words, not in a cell, not bare, not in angle brackets,
        // not tight in italics, not as a picture's words, not where an escaped backtick makes the gate take it for code
        let cellText = "| where | what |\n|---|---|\n| [https://forms.example.com/f?id=9](https://forms.example.com/f?id=9) | its own words |\n"
            + "| https://forms.example.com/f?id=9 | bare |\n| <https://forms.example.com/f> | in angle brackets |\n|_https://forms.example.com/i_|tight, in italics|\n"
            + "| ![https://forms.example.com/p](https://img.example.com/p.png) | a picture |\n| [https://forms.example.com/m](mailto:sam@example.com) | no web address |\n"
            + "| \\` https://forms.example.com/e ` | an escaped backtick |\n| https://www.notes.example.org/plot/ | the owner's own |\n\n"
            + "See [https://forms.example.com/f?id=9](https://forms.example.com/f?id=9), <https://forms.example.com/g> and \\` https://forms.example.com/e `."
        let cellPage = WikiText.parse(cellText, names: PeopleModel(), pages: [:], links: vouched)
        let cellRuns: [String] = cellPage.flatMap { p in p.text.runs.compactMap { r in r.link.flatMap { Answer.web($0.absoluteString)?.host } } }
        let cellOpens = gateOpensAll(cellPage.map(\.md)) + cellRuns
        let cellSaid = cellPage.map { gateSaid($0.md) + " " + $0.plain }.joined(separator: " ")
        let firstCell = cellPage.first?.md.rows.first.map { MD.plain($0[0]) }
        let cellsShut = !cellOpens.contains { $0.contains("forms.example.com") } && !cellSaid.contains("https://forms.") && firstCell == "forms.example.com"
        let ownStill = cellOpens.contains("www.notes.example.org") && cellPage.first?.md.rows.count == 8
        let wordsShut = WikiText.gate("[https://forms.example.com/f](https://forms.example.com/f)", WikiLinks()) == "forms.example.com"
            && WikiText.gate("go <https://www.notes.example.org/plot>", vouched) == "go [https://www.notes.example.org/plot](https://www.notes.example.org/plot)"
        check("wiki: a refused address opens from no cell, link words, picture, angle brackets or bare text, and reads as its site", cellsShut && ownStill && wordsShut)
        // the pages about you follow the same rule through the same filter: they cite no rows, so every address is its
        // site's name until links from others is on; "this is wrong" still names the line as the page has it
        let aboutText = "# you\n\nwrites at https://forms.example.com/f?id=9 and [the form](https://forms.example.com/f?id=9).\n\n"
            + "| site | why |\n|---|---|\n| https://forms.example.com/f | sent by sam |\n| [https://forms.example.com/g](https://forms.example.com/g) | sam again |\n| <https://forms.example.com/h> | and again |\n"
        let about = ProfilePage(id: "core", text: aboutText, rebuilt: nil)
        let aboutShut = about.blocks.map { WikiText.gate($0, WikiLinks()) }, aboutWide = about.blocks.map { WikiText.gate($0, WikiLinks(widen: true)) }
        let shutText = aboutShut.map(gateSaid).joined(separator: " ")
        let aboutOff = gateOpensAll(aboutShut).isEmpty && !shutText.contains("https://") && shutText.contains("the form (forms.example.com)") && shutText.contains("| forms.example.com |")
        let aboutOn = about.blocks.count == 3 && Set(gateOpensAll(aboutWide)) == ["forms.example.com"] && !gateOpens(aboutWide[1].bits).isEmpty
            && aboutWide[2].rows.count == 3 && aboutWide[2].rows.allSatisfy { !gateOpens($0[0]).isEmpty }
        check("about you: an address is its site's name, in a line and a table's cell, unless links from others is on",
              aboutOff && aboutOn && about.blocks[1].plain.contains("https://forms.example.com/f?id=9"))
        // a copy of the archive holds the rows, the pages, the journal, the chats and the rules, and nothing else: no sign-in,
        // key or token, no backup (other apps' configs with their servers' tokens), no forgotten row, no raw export
        let arch = URL(fileURLWithPath: tmp + "/copy-from"), copied = URL(fileURLWithPath: tmp + "/copy-to")
        let keep = ["messages.jsonl", "docs.jsonl", "never.json", "rules.json", "forgotten.json", "parts/whatsapp.jsonl", "parts/groups.json", "memory/core.md",
                    "memory/cards/chat_1.json", "memory/wiki/projects/the-token.md", "memory/corrections.jsonl", "journal/2026-11-20.md", "chats/c1.json", "made/m1.json"]
        let leave = ["telegram.session", "telegram.session-journal", "telegram/x", "api.json", "remote.json", ".env", "bridge/key", "bridge/jobs/j1", "agent.runs/x", "cache/words/a",
                     "settings.json", "app.log", "imports/x/data/tweets.js", "github_token", "GITHUB_TOKEN.json",
                     "backups/claude_desktop_config.json.20261120-101010", "backups/forgotten-20261120-r1/rows.jsonl", "backups/core.md.20261120-101010",
                     "memory/forgotten-20261120-r2/rows.jsonl", "memory/github_token.json", "memory/client_secret.json", "memory/api-key.json", "memory/token",
                     "memory/wiki/.env", "memory/x.session", "parts/x.pem", "parts/id_ed25519", "journal/key", "chats/notes.txt"]
        for f in keep + leave {
            let u = arch.appendingPathComponent(f)
            try? fm.createDirectory(at: u.deletingLastPathComponent(), withIntermediateDirectories: true)
            try? (f.contains("backups/claude") ? "{\"mcpServers\": {\"gh\": {\"env\": {\"GITHUB_TOKEN\": \"x\"}}}}" : "x").write(to: u, atomically: true, encoding: .utf8)
        }
        let copyOK = ArchiveCopy(arch).copy(to: copied)
        let kept = keep.allSatisfy { fm.fileExists(atPath: copied.appendingPathComponent($0).path) }
        let left = leave.allSatisfy { !fm.fileExists(atPath: copied.appendingPathComponent($0).path) }
            && ["backups", "imports", "bridge", "cache", "telegram", "agent.runs", "memory/forgotten-20261120-r2"].allSatisfy { !fm.fileExists(atPath: copied.appendingPathComponent($0).path) }
        check("a copy of the archive keeps the rows and pages, and leaves sign-ins, keys, tokens, backups, forgotten rows and raw exports", copyOK && kept && left)
        // telegram's sign-in never tells an installed app to run the engine from a working copy
        let tg = Blocked.telegramSaid("Telegram wants your two-step password. run once in a terminal: python3 -m ctx telegram-login")
        check("telegram's two-step password points at the open terminal button", tg.terminal && !tg.text.contains("python3") && tg.text.hasPrefix("telegram wants your two-step password. press open terminal")
              && !Blocked.telegramSaid("signed in to telegram").terminal)
        let tgNow = Blocked.telegramSaid("telegram wants your two-step password. it is typed in a terminal, never here: press open terminal on the sign-in card in the app's sources page")
        check("the engine's own two-step sentence, which names no command, still brings the open terminal button", tgNow.terminal && !tgNow.text.contains("python3")
              && tgNow.text == "telegram wants your two-step password. press open terminal: the sign-in starts there, where you type it")
        check("no markers, no chips", Answer(["answer": "plain. two sentences."], tag: "t")!.blocks.allSatisfy { !$0.hasCites })
        check("output with noise around it parses", EngineCall.parse(Data("warn\n{\"answer\": \"x\"}\nbye\n".utf8))?["answer"] as? String == "x")
        check("indented output parses", EngineCall.parse(Data("note\n{\n  \"answer\": \"x\"\n}\n".utf8))?["answer"] as? String == "x")
        check("plain text does not parse", EngineCall.parse(Data("nothing here".utf8)) == nil)
        let long = (0..<6).map { Turn(id: $0, q: "q\($0)", answer: Answer(["answer": "said so.[1] " + String(repeating: "more words ", count: 200)], tag: "t")) }
            + [Turn(id: 6, q: "failed", answer: .failure("no."))]
        let hist = (try? JSONSerialization.jsonObject(with: Data(AskModel.history(long).utf8))) as? [[String: String]] ?? []
        check("history: last four answered turns, no markers, 600 characters each",
              hist.count == 4 && hist.first?["q"] == "q2" && hist.allSatisfy { ($0["a"] ?? "").count <= 600 && !($0["a"] ?? "").contains("[") })

        // the chat, against the stand-in engine
        let engine = Engine()
        let ask = AskModel(home: engine.home)
        check("stand-in engine found", engine.repo != nil)
        func turn(_ q: String, within: Double = 8) -> Answer? {
            ask.draft = q
            ask.send(engine)
            wait(within) { !ask.asking }
            return ask.turns.last?.answer
        }
        ask.onScreen = true
        ask.draft = "did i tell maya about friday?"
        ask.send(engine)
        check("first question: on screen at once, in a chat of its own, input emptied", ask.turns.count == 1 && ask.turns[0].answer == nil && ask.asking && ask.homeDraft.isEmpty && ask.chats.count == 1)
        wait(8) { !ask.asking }
        check("first question: answered with two sources", ask.turns[0].answer.map { !$0.text.isEmpty && $0.cites.count == 2 && $0.cites[1].url == "https://example.com/p" } ?? false)

        // the follow-up that used to go missing: not phrased as a question, typed while the first answer is on screen
        ask.draft = "and the deposit"
        let ret = NSEvent.keyEvent(with: .keyDown, location: .zero, modifierFlags: [], timestamp: 0, windowNumber: 0, context: nil,
                                   characters: "\r", charactersIgnoringModifiers: "\r", isARepeat: false, keyCode: 36)!
        let esc = NSEvent.keyEvent(with: .keyDown, location: .zero, modifierFlags: [], timestamp: 0, windowNumber: 0, context: nil,
                                   characters: "\u{1b}", charactersIgnoringModifiers: "\u{1b}", isARepeat: false, keyCode: 53)!
        check("follow-up: return is used", ask.chatKey(ret, engine))
        check("follow-up: on screen at once, input emptied", ask.turns.count == 2 && ask.turns[1].q == "and the deposit" && ask.asking && ask.draft.isEmpty)
        ask.draft = "a third thing"
        check("a send while one is running waits in the conversation as next", ask.chatKey(ret, engine) && ask.turns.count == 2 && ask.queue == ["a third thing"] && ask.draft.isEmpty && ask.notice.isEmpty)
        wait(8) { ask.turns.count == 3 }
        check("follow-up: answered", ask.turns[1].answer?.text.isEmpty == false)
        check("follow-up: the first turn went along as history, without markers", ask.turns[1].answer?.found == 1)
        check("the waiting question goes by itself when the answer lands", ask.turns.count == 3 && ask.turns[2].q == "a third thing" && ask.queue.isEmpty && ask.asking)
        wait(8) { !ask.asking }
        check("and is answered, with no hint left behind", ask.turns[2].answer?.text.isEmpty == false && ask.notice.isEmpty)
        ask.draft = "mode:slow first"
        ask.send(engine)
        ask.draft = "kept after esc"
        ask.send(engine)
        let stopped = ask.turns.count - 1
        check("esc stops the running answer and keeps the waiting one", ask.chatKey(esc, engine) && ask.turns[stopped].answer?.error.isEmpty == false
              && ask.turns.count == stopped + 2 && ask.turns.last?.q == "kept after esc" && ask.asking && ask.queue.isEmpty)
        wait(8) { !ask.asking }
        check("the kept question is answered", ask.turns.last?.answer?.text.isEmpty == false)
        let firstChat = ask.currentID ?? ""
        wait(6) { ask.current?.named == true }
        check("the engine names the chat, in lower case", ask.current?.title == "maya and friday")
        ask.draft = "half a thought"
        ask.newChat()
        check("new chat goes home and keeps the conversation, with its draft", !ask.chatting && ask.currentID == nil && ask.chats.count == 1 && ask.draft.isEmpty && ask.chats[0].draft == "half a thought")
        // two chats answered at once: a slow one left running, and a new one asked beside it
        ask.open(firstChat)
        ask.draft = "mode:slow left running"
        ask.send(engine)
        ask.newChat()
        ask.draft = "asked beside it"
        ask.send(engine)
        let second = ask.currentID ?? ""
        check("a running answer does not block another chat", ask.busy == [firstChat, second] && ask.turns.count == 1 && ask.queue.isEmpty)
        wait(8) { !ask.busy.contains(second) }
        check("the second chat is answered while the first is still read", ask.turns[0].answer?.text.isEmpty == false && ask.busy == [firstChat])
        ask.cancel(firstChat)
        ask.open(firstChat)
        ask.draft = "asked and then left"
        ask.send(engine)
        ask.newChat()
        wait(8) { ask.busy.isEmpty }
        check("an answer that lands while the owner is elsewhere marks its chat unread", ask.chats.first { $0.id == firstChat }?.unread == true && ask.chats.first { $0.id == second }?.unread == false)
        ask.open(firstChat)
        check("opening it clears the mark", ask.current?.unread == false && ask.draft.isEmpty)
        let before2 = ask.turns.count, firstID = ask.turns[0].id
        ask.ask(engine, "a new question from home")
        check("a question from the panel starts its own conversation and keeps the ones before", ask.turns.count == 1 && ask.chats.count == 3 && ask.chats.first { $0.id == firstChat }?.turns.count == before2)
        wait(8) { !ask.asking }
        check("recent lists the last questions, newest first", ask.recent.first?.q == "a new question from home" && ask.recent.count == 5)
        ask.reopen(firstID)
        check("a recent question opens its conversation again", ask.turns.first?.id == firstID && ask.turns.count == before2 && ask.currentID == firstChat)
        check("the list is newest first, in days", ask.sections().first?.name == "today" && ask.sections().first?.chats.first?.turns.first?.q == "a new question from home"
              && ask.sections(matching: "beside").flatMap(\.chats).map(\.id) == [second])
        ask.pin(second)
        check("a pinned chat goes on top", ask.sections().first?.name == "pinned" && ask.sections().first?.chats.map(\.id) == [second])
        ask.pin(second)
        ask.rename(second, to: "  the one   beside  ")
        check("a renamed chat keeps the name the owner gave", ask.chats.first { $0.id == second }?.title == "the one beside")
        if let l = Optional(LensInfo(id: "intros", title: "intros i promised", about: "")) {
            ask.run(l, engine)
            check("a lens is a turn in a chat of its own", ask.turns.count == 1 && ask.turns[0].lensID == "intros" && ask.asking && ask.chats.count == 4)
            wait(8) { !ask.asking }
            check("a lens answers as a summary, a list and its sources", ask.turns[0].answer?.text == "You promised two." && ask.turns[0].items.count == 2 && ask.turns[0].answer?.cites.count == 2)
            let item = ask.turns[0].items[0]
            ask.score(item, ok: true, in: ask.turns[0].id)
            ask.score(ask.turns[0].items[1], ok: false, in: ask.turns[0].id)
            check("done and not real act on the turn's list", ask.turns[0].items.count == 1 && ask.turns[0].items[0].status == "done")
        }
        ask.reopen(firstID)
        ask.draft = "and back in"
        ask.send(engine)
        check("asking again goes into that chat", ask.currentID == firstChat && ask.asking)
        wait(8) { !ask.asking }

        for (mode, want) in [("noise", true), ("pretty", true), ("big", true), ("garbage", false), ("empty", false), ("crash", false),
                             ("error", false), ("exception", false), ("blank", false)] {
            let got = turn("mode:\(mode) please")
            let fine = want ? got?.text.isEmpty == false : (got != nil && got!.text.isEmpty && got!.error.count > 8 && !got!.error.contains("line 1 column"))
            check("engine \(mode): \(want ? "answer" : "a sentence"), nothing left waiting", fine && !ask.asking)
        }
        check("the engine's own words are shown", ask.turns.contains { $0.answer?.error == "no plan is signed in." })

        AskModel.patience = 1.5
        var t0 = Date()
        var got = turn("mode:slow one")
        check("too slow: stopped with a sentence in about the time allowed", got?.error.contains("try again") == true && Date().timeIntervalSince(t0) < 4)
        t0 = Date()
        got = turn("mode:hold the pipe")
        check("a pipe held open by a child still ends", got?.error.contains("try again") == true && Date().timeIntervalSince(t0) < 4)
        AskModel.patience = 150

        ask.draft = "mode:slow two"
        ask.send(engine)
        let slow = ask.turns.count - 1
        check("esc stops a running answer", ask.chatKey(esc, engine) && !ask.asking && ask.turns[slow].answer?.error.isEmpty == false)
        got = turn("and after stopping")
        check("after a stop the next question is answered", got?.text.isEmpty == false && ask.turns[slow].answer?.text.isEmpty == true)
        ask.again(ask.turns[slow], engine)
        check("try again: the same turn reads again", ask.asking && ask.turns[slow].answer == nil)
        ask.cancelAsk()
        if let i = ask.turns.firstIndex(where: { $0.answer?.error == "no plan is signed in." }) {
            ask.turns[i] = Turn(id: ask.turns[i].id, q: "did it work this time?", answer: ask.turns[i].answer)
            ask.again(ask.turns[i], engine)
            wait(8) { !ask.asking }
            check("try again: the failed turn gets its answer in place", ask.turns[i].answer?.text.isEmpty == false)
        }
        let before = ask.turns.count
        ask.draft = "   "
        check("an empty input sends nothing", ask.chatKey(ret, engine) && ask.turns.count == before && !ask.asking)
        // up-arrow: the last question comes back, is changed, and is asked again in its place
        let up = NSEvent.keyEvent(with: .keyDown, location: .zero, modifierFlags: [], timestamp: 0, windowNumber: 0, context: nil,
                                  characters: "", charactersIgnoringModifiers: "", isARepeat: false, keyCode: 126)!
        ask.draft = ""
        let n = ask.turns.count
        check("up-arrow in an empty input brings the last question back", ask.chatKey(up, engine) && ask.editing == ask.turns.last?.id && ask.draft == ask.turns.last?.q)
        ask.draft = "did it work, asked differently?"
        check("sending it asks again in the same place", ask.chatKey(ret, engine) && ask.turns.count == n && ask.turns.last?.q == "did it work, asked differently?" && ask.asking && ask.editing == nil)
        wait(8) { !ask.asking }
        // what is on disk opens again exactly: questions, answers, rows, ratings, titles, scope
        if let t = ask.turns.first(where: { $0.answer?.cites.count == 2 }) { ask.rate(t, ok: true, engine) }
        var sc = Scope(); sc.sources = ["whatsapp"]; sc.after = "2026-01-01"; sc.people = ["maya"]
        ask.scope = sc
        ask.deep = true
        ask.draft = "left half typed"
        ask.save(firstChat)
        let again = AskModel(home: engine.home)
        let was = ask.chats.first { $0.id == firstChat }, now = again.chats.first { $0.id == firstChat }
        check("every chat is a file, and comes back", again.chats.count == ask.chats.count && FileManager.default.fileExists(atPath: ChatStore.file(firstChat, engine.home).path))
        check("a chat opens again exactly: questions, answers, sources", now?.turns.map(\.q) == was?.turns.map(\.q) && now?.turns.map { $0.answer?.text ?? "" } == was?.turns.map { $0.answer?.text ?? "" }
              && now?.turns.map { $0.answer?.cites.map(AskModel.rowID) ?? [] } == was?.turns.map { $0.answer?.cites.map(AskModel.rowID) ?? [] }
              && now?.turns.map { $0.answer?.error ?? "" } == was?.turns.map { $0.answer?.error ?? "" })
        check("and its title, rating, scope, mode and draft", now?.title == "maya and friday" && now?.named == true && now?.turns.contains { $0.rated == true } == true
              && now?.scope == sc && now?.deep == true && now?.draft == "left half typed")
        check("history for the engine comes from the reopened chat", AskModel.history(now?.turns ?? []) == AskModel.history(was?.turns ?? []))
        ask.delete(second)
        check("a deleted chat leaves the list and its file leaves the folder", !ask.chats.contains { $0.id == second } && !FileManager.default.fileExists(atPath: ChatStore.file(second, engine.home).path))
        ask.newChat()
        check("new chat clears the window", ask.turns.isEmpty && !ask.chatting && ask.draft.isEmpty)

        // what the running refresh is doing, and what the sources heading counts
        engine.states = ["whatsapp": .done(rows: 700, secs: 1), "email": .done(rows: 300, secs: 1)]
        engine.syncing = true
        engine.ticking = true
        engine.live = [:]
        check("a refresh that is alive but idle shows no indicator", engine.doing() == nil)
        check("the sources number is the archive total during a refresh", SourcesView.total(engine) == 1000)
        check("the sources heading does not say reading when nothing is read", SourcesView.heading(engine, next: "", at: Date()).hasPrefix("synced"))
        engine.heard = "whatsapp"
        engine.heardAt = Date()
        check("it says what is being read while it is", engine.doing() == "reading whatsapp" && SourcesView.heading(engine, next: "", at: Date()) == "reading whatsapp now")
        engine.heard = "understand"
        engine.readThrough = (12, 40)
        check("the read-through says how far", engine.doing() == "read-through 12 of 40" && engine.doingDetail().contains("12 of 40"))
        engine.heardAt = Date().addingTimeInterval(-90)
        check("and goes quiet when nothing has been heard for a while", engine.doing() == nil)
        engine.syncing = false
        engine.ticking = false

        // the add panel, start to finish
        let add = AddModel(engine: engine)
        add.query = "disc"
        check("add: it says it is looking until the engine has answered", add.searching && AddSheet.hint(query: add.query, searching: add.searching).hasPrefix("looking"))
        wait(6) { !add.searching }
        check("add: the list the engine prints becomes rows", add.results.map(\.id) == ["discord"] && add.results[0].name == "discord" && add.results[0].iconPath == "/Applications/Discord.app")
        add.pick()
        check("add: picking starts the engine working it out", add.stage == .working)
        wait(6) { add.stage != .working }
        var ready = false
        if case .result(let r) = add.stage { ready = r.state == "ready" && r.rows == 12 && r.sentence.hasSuffix("add it?") }
        check("add: progress lines were heard and it is ready", ready && add.phases.count == 2)
        add.add()
        check("add: added", add.stage == .added)
        wait(6) { engine.order.contains("discord") }
        check("add: the new source is on the list to be read", engine.order.contains("discord"))
        let add2 = AddModel(engine: engine)
        add2.query = "zzzz"
        wait(6) { !add2.searching }
        check("add: nothing by that name, said only once the engine has answered", add2.results.isEmpty && AddSheet.hint(query: add2.query, searching: add2.searching).hasPrefix("no app on this mac and no service context knows goes by that name"))
        add2.query = "nope"
        wait(6) { !add2.searching }
        add2.pick()
        wait(6) { add2.stage != .working }
        var cannot = false
        if case .result(let r) = add2.stage { cannot = r.state == "cannot" && r.sentence.contains("cannot read") }
        check("add: one it cannot read says so", cannot)

        // icons of services without an app: off unless switched on; then found on the service's own page, kept in the archive folder, nothing of their sent
        let page = "<html><head><link rel=\"icon\" href=\"/favicon-32.png\" sizes=\"32x32\"><link rel='apple-touch-icon' sizes='180x180' href='https://cdn.example.com/touch.png?a=1&amp;b=2'>"
            + "<link rel=\"mask-icon\" href=\"/mark.svg\"><link rel=\"stylesheet\" href=\"/a.css\"></head></html>"
        let links = WebIcons.links(html: page, base: URL(string: "https://example.com/home")!).map(\.absoluteString)
        check("icons: the biggest icon a page names comes first, vectors and stylesheets are left out",
              links == ["https://cdn.example.com/touch.png?a=1&b=2", "https://example.com/favicon-32.png"])
        check("icons: every source of a service wears that service's mark", WebIcons.key("instagram_saved") == "instagram" && WebIcons.key("x_bookmarks") == "x"
              && WebIcons.key("linkedin_connections") == "linkedin" && WebIcons.key("journal") == nil)
        let req = WebIcons.request(URL(string: "https://example.com/i.png")!)
        check("icons: fetching is off until it is switched on, and so is a nudge worded by the plan", !Saved().webIcons && !Saved().nudgeModel)
        check("icons: the request carries no cookies and says what it is", !req.httpShouldHandleCookies && req.value(forHTTPHeaderField: "Cookie") == nil
              && req.value(forHTTPHeaderField: "User-Agent")?.hasPrefix("context/") == true && req.value(forHTTPHeaderField: "User-Agent")?.contains("Mozilla") == false && WebIcons.session.configuration.httpCookieStorage == nil
              && WebIcons.sites.values.allSatisfy { ($0.icons + [$0.page]).allSatisfy { $0.hasPrefix("https://") } })
        check("icons: junk is not an icon", WebIcons.png(Data("<html>not found</html>".utf8)) == nil)
        let drawn = NSImage(size: NSSize(width: 64, height: 64), flipped: false) { r in NSColor.systemTeal.setFill(); r.fill(); return true }
        if let tiff = drawn.tiffRepresentation, let png = WebIcons.png(tiff) {
            let to = WebIcons.file("x", home: engine.home)
            try? fm.createDirectory(at: to.deletingLastPathComponent(), withIntermediateDirectories: true)
            try? png.write(to: to)
            check("icons: one kept in the archive folder is used from then on", WebIcons.cached("x_bookmarks", home: engine.home) != nil && WebIcons.cached("instagram", home: engine.home) == nil)
        } else { check("icons: a picture becomes a png", false) }
        if ProcessInfo.processInfo.environment["CONTEXT_ICONS_LIVE"] != nil {      // by hand only: fetch every mark for real, into the temporary folder
            var left = WebIcons.sites.count, got: [String] = []
            for (key, site) in WebIcons.sites { WebIcons.fetch(key, site: site, home: engine.home) { ok in left -= 1; if ok { got.append(key) } } }
            wait(60) { left == 0 }
            print("     icons fetched: \(got.sorted().joined(separator: " "))  ·  missing: \(WebIcons.sites.keys.filter { !got.contains($0) }.sorted().joined(separator: " "))")
            if let keep = ProcessInfo.processInfo.environment["CONTEXT_ICONS_KEEP"] { try? fm.copyItem(atPath: engine.home.appendingPathComponent("cache/icons").path, toPath: keep) }
        }
        let rest = AppModelPointer()
        check("a pointer at rest gives no tile the focus; a moved one does", !rest.moved(CGPoint(x: 10, y: 10)) && rest.moved(CGPoint(x: 30, y: 10)))

        let none = Engine.findRepo("/nonexistent")
        var said = ""
        EngineCall.start(repo: none, args: ["answer", "x"], timeout: 5) { if case .failed(let s) = $0 { said = s } }
        wait(2) { !said.isEmpty }
        check("no engine: a sentence", said.contains("try again"))

        try? fm.removeItem(atPath: tmp)
        print(failed == 0 ? "asktest: all checks passed" : "asktest: \(failed) failed")
        exit(failed == 0 ? 0 : 1)
    }
}
