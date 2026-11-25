---
name: tester report
about: you tried context on your own mac. tell us what worked and what broke
title: "tester report: "
labels: tester
---

thank you for trying it. this issue is public: read the report file before you attach it.

**your mac**

- mac model and year:
- macos version:
- browser you use most:

**sources**

- which sources did you expect to see (whatsapp, imessage, mail, notes, browser history, claude code, ...)?
- which of them showed up?
- which did not?

**what felt broken, slow or confusing**

1.
2.
3.

**three questions you asked, in general terms** (no private detail: "a question about a trip", not the trip)

- did the answers use the right messages?

**checklist**

- [ ] i ran `python3 -m ctx doctor`
- [ ] i ran `python3 -m ctx collect`, or installed the app with `app/install.sh`
- [ ] i asked three questions
- [ ] i tried to add one source
- [ ] i ran `python3 -m ctx report` (add `--try` if you had five more minutes)
- [ ] i read the report file before attaching it
- [ ] the report file is attached (drag `context-report-<date>.txt` into this box)

how to do each step, and how to remove everything afterwards: [docs/TESTING.md](https://github.com/heettike/context/blob/main/docs/TESTING.md)
