# motion: every animation in the app

Each line is: what moves, how long, on what curve, and where to see it.
Tokens are in `Sources/context/Theme.swift` (`enum Motion`). Curves are cubic-bezier unless a spring is named.

**Reduce Motion** (System Settings > Accessibility > Display). With it on: nothing travels or scales; a change is
either instant or a fade of 100 to 120 ms; spinners, the sweep and the caret stand still; a pressed thing does not
give. To check: switch it on and walk the list again. Where a line says "fade" below, that is what is left.

The gate draws frames of the starred ones (*) offscreen, as strips: `build/check/strip-<name>.png`.

## pages

| what | how | where to see it | reduce motion |
|---|---|---|---|
| a page arriving* (`page`) | opacity 0 to 1 and 6 pt up, 220 ms, (.19, 1, .22, 1). the page before is cut at once: no cross-fade | click sources, settings, about you, journal, teach, made | 100 ms fade, no rise |
| a settings pane arriving | same as a page | click a pane in settings | same |
| another chat (`Arrive`) | the conversation is cut and arrives: opacity and 6 pt, 220 ms, same curve | click a different chat in the list | 100 ms fade |
| the bar's title | the new name fades in over 320 ms spring (response .32, damping .88); the old is cut | change page | 100 ms |
| sidebar and sources panel | slide in from their edge, spring response .38, damping .86 (`tray`) | shift-cmd-S; "sources" under an answer | 120 ms fade |
| first run to the main window | opacity and scale .985 to 1, spring response .5, damping .86 | finish first run | fade |

## home and asking

| what | how | where | reduce motion |
|---|---|---|---|
| a line of the desk settling* (`settle`) | opacity and 8 pt up, 420 ms, (.19, 1, .22, 1), each 35 ms after the one before | open home when the month's data arrives | instant |
| a line's number of days | counts from 0 to its value on the same timing | same | stands at its value |
| the archive strip* (`grow`) | each bar grows from the baseline, 400 ms, (.22, 1, .36, 1), left to right over 300 ms, once | same | instant |
| the desk falling back* (`deskOut`) | opacity to 0 and scale to .97, 120 ms ease-out. then it is cut | send a question from home | cut |
| the question lifting* (`lift`) | rises 260 pt from the input to the top, scale .98 to 1, spring response .46, damping .84 | send a question, from home or in a chat | appears in place |
| the input growing* | the box follows its text on a spring, response .38, damping .86 (`tray`) | type until the line wraps, or shift-return | instant |
| starters under the input (plain home) | each 14 pt up with a 5 pt blur clearing, spring response .5, damping .86, 50 ms apart (`reveal`) | home with an engine that has no `now` | fade |
| a starter, a row, a tile under the press | scale to .97, spring response .22, damping .8 | press and hold | no scale |
| hover on anything | colour or ground over 100 to 150 ms ease-out | move the pointer | same (it is not movement) |

## an answer

| what | how | where | reduce motion |
|---|---|---|---|
| the ribbon's line (`draw`) | draws from the left, 600 ms, (.22, 1, .36, 1) | ask something; watch above the working line | there at once |
| a dot landing* (`dot`) | scale .2 to 1 with opacity, spring response .30, damping .62 (a small overshoot) | while the answer is worked on | appears |
| the chosen dot | grows 6 to 9 pt and turns ember, same spring; its date rises 4 pt, 140 ms | hover a dot, a number, a sentence or a note | changes at once |
| the working line's words | the old line fades out in 80 ms, then the new fades in over 180 ms from 3 pt above (`Flap`) | while it works | swaps |
| seconds and counts on the working line | digits change in place (`numericText`) | same | change at once |
| the sweep under the working line | an ember stretch runs along a hairline every 1.6 s | same; also a source being read | stands still |
| the working line leaving | 140 ms fade; the answer waits those 140 ms | when the answer lands | same |
| an answer that was not streamed arriving | opacity and 8 pt up, 400 ms ease-out after 140 ms | open sources of a slow answer; ask with CONTEXT_STREAM=0 | 100 ms fade |
| the newest words* (`words`) | opacity 0 to 1, 180 ms ease-out. nothing before them moves | while it is written | appear |
| the caret at the end of a line being written | blinks every 530 ms | same | stays lit |
| a margin note arriving* (`note`) | 8 pt in from the right with opacity, 300 ms, (.25, 1, .5, 1), each 40 ms after the one above | answer in a window with room for the margin | appears |
| a note, its sentence, lit* (`lit`) | the note moves 2 pt left and takes the ember rule and a wash; the sentence takes a soft ground. 140 ms, (.25, 1, .5, 1) | hover or click a note, a number or a dot | changes at once |
| a citation's number (narrow window) | swells to 1.12, spring response .28, damping .72 (`pop`) | hover a numbered chip | no swell |
| the hover card of a chip (narrow window) | opens from .97 at the chip with opacity, 120 ms, (.24, 1, .29, 1) (`enter`); closes by fading | hover a chip | 50 ms fade |
| a message unfolding in the margin* (`unfold`) | scale .96 to 1 from its top with opacity, spring response .38, damping .86; the notes below move down on the same spring | click a margin note | appears |
| the steps unfolding | opacity, with the page making room on the `tray` spring | click "worked for 9 s" | fade |
| the actions under an answer | opacity and 8 pt up when the answer is done | end of an answer | fade |
| scrolling to a new turn | 500 ms, (.24, 1, .29, 1) (`snap`) | ask a follow-up | jumps |

## about you, the journal, teach, made

| what | how | where | reduce motion |
|---|---|---|---|
| the four words under a paragraph | opacity, 150 ms ease-out | hover a paragraph of about you (when the engine names its paragraphs) or of the journal in review | same |
| a paragraph removed, and put back | the line that takes its place and the paragraph swap on the `unfold` spring | remove, then undo within six seconds | swap |
| jumping to a heading | scroll, 180 ms ease-out | click a heading in "on this page" | jumps |
| your sentence in teach | `lift`, as a question | say something in teach | appears |
| the reading's card | scale .97 to 1 from its top left with opacity, `unfold` spring | when the engine has read the sentence | appears |
| a saved rule | 8 pt up with opacity (`settle`, 420 ms), on a wash that fades over 600 ms | "do this" | appears |
| a rule switched off | dims to 55% and its words are struck, 140 ms (`lit`); the switch's knob moves on a spring, response .32, damping .88 | flip a rule's switch | at once |
| a row of the made list | 8 pt up with opacity, `settle`, 35 ms apart | open made | appears |

## first run and adding a source

| what | how | where | reduce motion |
|---|---|---|---|
| the lines of the first screen | `reveal`: 14 pt up, blur clearing, 50 ms apart | first launch | fade |
| a switch's word (off, waiting, on) | `Flap`: out in 80 ms, in over 180 ms | grant a permission | swaps |
| a switch that still needs you | wash and ember rule fade over 140 ms when it turns on | grant a permission | at once |
| one screen of first run to the next | the old one leaves 14 pt up in 130 ms ease-in; the new arrives with opacity | "start reading" | fade |
| the total and each source's count | run to each new value in 130 ms linear; one long breath of 850 ms ease-out when a read lands | while sources are read | stand at their value |
| a row's bar on the line of years | drawn where the source has read: nothing on the reading screen animates but its figures (a value changes where it stands) | reading | same |
| the ember dot on a row | stands at the month being read; moves when the engine names a later one, at once | reading | same |
| the sweep under a row being read | as under the working line | reading | still |
| a step of the trial read arriving | 6 pt up with opacity, `settle` | add a source and watch the trial | appears |
| the add panel | arrives 14 pt up with opacity on a spring, response .5, damping .86 | "add a source" | fade |

## the hotkey panel, pings, the menu bar

| what | how | where | reduce motion |
|---|---|---|---|
| the panel appearing | opacity with scale .98 to 1 from its top, 120 ms (`enter`); leaving, 90 ms fade (`exit`) | control-option-space | fade |
| the panel growing with its answer | `tray` spring | ask in the panel | 120 ms |
| a ping | drops under the menu bar mark, then fades after 8 s | an answer finishing while the window is behind | fade |
| the menu bar mark while work runs out of sight | the dot between the brackets swells and settles through eight sizes, a step every 180 ms | close the window during a read | stands still |
| the mark when something waits | one pulse of opacity, to 35% and back | a ping arriving | none |
| the mark when an answer lands out of sight | one pulse, to 35% and back in 900 ms | ask, then switch to another app | none |

## not animated on purpose

A value that changes where it stands (a word on the reading screen, the line under the total, the bar's title) is
swapped, never cross-faded: two values would be read through each other. A page leaving is cut. Nothing loops but
the spinner, the sweep and the caret.
