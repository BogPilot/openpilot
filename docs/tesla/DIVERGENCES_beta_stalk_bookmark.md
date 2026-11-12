# Divergence: beta stalk bookmark (BETA-ONLY, remove before production)

Entry in the `docs/tesla/DIVERGENCES.md` style, kept in its own file so it can be folded into `DIVERGENCES.md`.

### Legacy Tesla beta stalk bookmark
**New BogPilot beta behavior; no parity source.** BogPilot 0.9.7 (sidebar `userFlag` only), Tinkla/BogGyver and NAP have no
stalk bookmark; FWD on `STW_ACTN_RQ` 0x45 is cancel only in all three. The gesture lets a beta tester mark a moment in the
logs with three quick FWD taps after disengaging. Timing is derived from real tap attempts on AP1 Model S drives, with
0.9.7 log taps as supporting data.

BogPilot 0.11.2 adds a UI-side, observe-only detector (`openpilot/selfdrive/ui/beta_stalk_bookmark.py`):
- after disengaging, 3 FWD taps of 50-300 ms, gaps <= 1.00 s, span <= 1.20 s -> one `userBookmark`, written at the 3rd
  tap's release, through the UI's existing publisher;
- extra taps never cancel it and never fire a second bookmark: lockout until the stalk is IDLE for more than 1.00 s, or an abort;
- each counted tap's onset must be disengaged (`selfdriveState.enabled` False AND `carState.cruiseState.enabled` False);
- disengage guard, 0.30 s: no counted tap starts less than 0.30 s after the most recent falling edge of either flag
  (bounce / re-press guard); the disengaging cancel itself never counts;
- aborts: engage edge, RWD (single or double pull), UP/DN tips, invalid value, `canValid` False, carState gap > 0.25 s,
  a press < 50 ms or > 300 ms (> 300 ms also disarms until IDLE);
- own-TX drop, 0.30 s (a separate constant from the 0.30 s disengage guard, with its own edge): a FWD onset within 0.30 s
  after one of our own 0x45 frames on `sendcan` is never counted, and our own 0x45 TX while a tap train is counting
  (a press being timed, or counted taps) resets it to IDLE, so a dropped onset can never merge two presses into one tap.
  The post-fire lockout is kept through our own TX, so there is still at most one bookmark per train. Unconditional, on every platform. This is defense in depth; the bus-0 parser already reads src 0
  only, and our own frames come back as src 128/130. The window follows NAP, which ignores a stalk cancel within
  `SPOOF_ECHO_WINDOW_MS = 300` after its own spoof TX (pre-AP `engagement.py:10,187-190` @ opendbc `cc39c7fa`). Supporting
  measurement on a real pre-AP drive log: 15 of our 0x45 frames, echoed 2.91 / 5.20 / 6.13 ms (min / median / max) after the
  send, far inside 0.30 s. Cost: a real press less than 0.30 s after our TX is not counted (false negative, never a false
  bookmark).

Scope: **off by default** (file flag `/data/params_bogpilot/BetaStalkBookmark` = `1`), explicit fingerprint allow-list,
currently `TESLA_AP1_MODELS` only. Pre-AP S, AP1 X and AP2 S/X are added one entry at a time once each has an on-car 0x45
capture with a real tap train, (AP2) proof of the 0x45 originator with no AP-ECU forward or echo, and a real-drive replay.
Raven/HW3 and Model 3/Y are out of scope.

Not changed: car process (card, carstate, carcontroller), buttonEvents, cruise and engagement state (including pre-AP
`PreAPEngagement`, `StockCCSpoofer` and the panda-drop latch), CAN TX, panda safety, schema, Params, and the Experimental FWD
hold (`phase3_stalk_controls.ExperimentalHold`). FWD stays cancel exactly as in all three references.

Accepted trade-off: accidental bookmarks are acceptable. The output has no actuation path, the beta is default-off, and
bookmarks without a tester note are ignored in review. The false-trigger rate for non-attempt multi-taps is untested;
re-check after beta drives.

References: BogPilot (stalk parsing, Experimental hold), Tinkla/BogGyver and NAP (FWD = cancel; NAP's spoof-echo ignore).
