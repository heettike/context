# design

How the mac app looks and behaves, for anyone changing it. The numbers live in `Sources/context/Theme.swift`; a
screen takes its numbers from there, and a number that is not there is a fault. `MOTION.md` lists every animation.

## rules

1. One idea per screen, one filled control per view. Everything else is a plain word that darkens under the pointer.
2. Lowercase in the interface. Short, plain words. No emoji. No marketing words, no alarm words.
3. Three voices of type: serif for what is said to the person or about them, sans for the name of a thing, mono
   for what is measured (a date, a count, a kind, a key).
4. Colour is not decoration. One accent, ember, marks what is live or needs the person, and stays under two
   percent of a screen. Every other colour belongs to a source's mark.
5. Nothing is pure black or pure white. Every level of text reads at 4.5:1 or better on its ground, light and dark;
   the build measures it.
6. Progress is always real: a count, a bar or a sentence shows only what the engine reported.
7. Every control has a spoken label. A focus ring shows for the keyboard only.
8. No gradients, glass, glow, side-stripe accents or icon-above-heading grids. One shadow, under a raised card.
9. The app says what is true about where data goes. A thing that writes outside the archive folder, asks a site for
   something, or spends the person's plan in the background needs a press on a labelled control or a visible switch.

## colour (`Ink`)

| token | light | dark | for |
|---|---|---|---|
| paper | F5F4F0 | 131414 | the window's ground |
| raised | FBFAF7 | 1A1B1B | a card |
| wash | E8E7E0 | 1D1E1E | a chosen row, a quiet button |
| side | EFEEE9 | 181919 | the sidebar |
| ink | 17181A | EDECE8 | text |
| soft | 55565A | A8A8A4 | secondary text |
| faint | 6E6F6D | 858683 | measures and hints; never on the wash |
| mark | FBEFC2 | 3A3212 | the ground of a highlighted sentence |
| line | DAD9D1 | 272828 | hairlines |
| ember | E8502A | FF6A3D | the accent: live, or needs you |

## type (`Face`)

Sizes, in points, with no half sizes: 10 tiny (a key, a badge), 11 micro (a heading over a list), 12 small (beside
or under a name), 13 label (a row, a control), 15 body (the person's own words, the input), 16 read (serif: an
answer, a page), 19 head (serif: a heading in a page), 30 title (serif: a page's name), 44 figure (the one big
number). The mono measure is 10.5.

Weights: regular for what is read, medium for the name of a thing or the chosen one, semibold only for the small
heading over a list. Figures use tabular digits wherever a number can change.

## space and corners (`Space`, `Radius`)

Space: 2, 4, 8, 12, 16, 24, 32, and 48 for a page's margin. Gaps and paddings come from this run only.

Corners: 5 for a mark in the text (a citation, a key), 8 for a row or small button, 12 for a card, table or tile,
18 for the input and a floating panel. A capsule is only for a thing pressed like a key: send, a switch.

## motion (`Motion`)

One sentence: things arrive from below, fast out of the gate with a long soft landing, and almost nothing
overshoots.

- A page is cut and the next arrives: opacity and a 6 pt rise, 220 ms, cubic-bezier(.19, 1, .22, 1). Two pages
  never cross-fade.
- Hover and selection: 100 to 150 ms ease-out. A pressed thing gives to 0.97.
- Panels and the sidebar move on a spring (response 0.38, damping 0.86) with no overshoot.
- The one overshoot is small: a citation or a dot of evidence landing.
- Words of an answer fade in over 180 ms; nothing already on the page moves.
- A spinner, a sweep or a ticking count shows only while the engine is really working.
- Reduce Motion: nothing travels or scales. A change is instant or a fade of 100 to 120 ms. Every animation has
  this second form, and `MOTION.md` names it.

## structure

- **The window.** A sidebar (new chat, search, the list of chats; then journal and made; about you, sources and
  teach; settings) and one page. The window's least size is 760 by 540; the gate lays every screen out at 760 by
  540, 920 by 640 and 1400 by 900.
- **Home** is a desk: what waits on the person, what they said they would do, what is on their mind, a strip of
  the archive by month, and the input.
- **An answer** is a page: prose in serif, at most 480 pt wide. Evidence sits in the margin as notes beside the
  sentence each supports, and falls into a panel when the window is narrow. A ribbon shows when the evidence is
  from. Only a word that begins http or https, or a markdown link, is ever a link; a link shows its real host.
- **Time** is on screen: a spine of years at the left of the main page.
- **Sources** is one shelf of tiles: an app's own icon read from this mac, or a letter on the source's colour, with
  a short count; then what waits on the person, each with the one action it needs.
- **Settings** is a list of panes and one pane: general, models, connected ais, what can read, sources & sync,
  permissions, your data, notifications, about. A pane is cards (`SetCard`) of rows (`SetRow`): a name, one
  sentence, an optional mark (a dot and a word), and one control (`SetButton`, `SetSwitch`, `SetMenu`, `SetFold`).
  All text in a pane goes through `SetText`, which never truncates.
- **The panel** opens over any app from a hotkey: one field, the answer in place.
- **The menu bar mark** is a pair of brackets round a dot; the dot turns ember when something needs the person.
  A ping drops under it: one sentence, one action, "not now".

## the gate

`./build.sh` is not done until `--layouttest` has laid out every screen at the three sizes with awkward content
(long names, empty states, large counts) and found no clipped text, overlap, or thing outside the window, and until
the ask checks pass against a stand-in engine. A new screen or state adds a scenario and, where it has a rule worth
keeping, a check. Fixtures use invented data only; shared counts come from `Fixtures.swift`. The gate draws nothing
on screen and writes light and dark renders of each screen into `build/check`.
