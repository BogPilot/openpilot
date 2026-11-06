# bogpilot-tesla-c3x provenance audit (Cursor Agent authorship)

Date: 2026-11-06 (America/New_York). Scope: everything reachable from `bogpilot-tesla-c3x`
and the code it carries from older BogPilot lines.

## Reachable history
- Base `f7db927c7` "openpilot v0.11.2" (release-tizi) is one squashed upstream commit. It has no
  Cursor author, committer or trailer. The four upstream commits that carry
  `Co-authored-by: Cursor <cursoragent@cursor.com>` (19459d2b2, c6db0cd4b, 489afc384, 2dac616be) are
  standard upstream openpilot history. They are not ancestors of the base and were left alone.
- All 15+ BogPilot commits on top: author and committer are `BogPilot <bogpilot@users.noreply.github.com>`,
  and none has a co-author trailer.
- The stream donor commits (port/c3x-s1/s2/s4..s8) were also BogPilot-authored and had no trailers.

## Cursor Agent commits in the repository
- `b956ce126` / `e6b629a9c` (Cursor Agent, 2026-10-24) "ui: optional offroad screensaver for upload
  progress" (Qt, 0.9.7 line). It reaches the 367e1fe reference. `0865e3902` is a copy of it with only the
  author changed. `4a593770c` (0.11.2 offroad UI, ancestor of agnos199-integration) carries
  `selfdrive/ui/bogpilot/screensaver.py` derived from that feature.
- C3X carries none of that implementation. There is no screensaver module or consumer, and none of
  the 158 substantive added lines of b956ce126 appear verbatim in any of the 147 files C3X changes.
- The one trace left is the `OffroadScreensaver` file-toggle key. Its default ON is an owner policy pin
  (bogpilot_params.py / bogpilot_shipping_defaults.py), so the key is kept as a reserved name and its
  description was reworded. Nothing on C3X reads it. Bardo decides whether to drop it or ask for a
  fresh BogPilot raylib screensaver.
- Brand assets are not Cursor-derived. The road logo first appears in BogPilot commit a72c24b6d
  (2026-10-14, boot logo), before the Cursor commit. icon_bogpilot.png comes from dc017e3fb (BogPilot).

## Not in scope / open
- Many BogPilot commits carry `Co-Authored-By: Claude ...` trailers. That is not Cursor Bot, so
  it was not acted on.
- The C3 product line and the `agnos199-port-screensaver` worktree may carry the screensaver port.
  The C3 executor owns that.
