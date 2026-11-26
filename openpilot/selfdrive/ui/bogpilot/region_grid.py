"""comma 4 region picker: a 2-column grid of full region names.

Countries and U.S. States open ONE grid of every region by name (A-Z), cut into card-sized pages of 2 columns x 3 rows that
swipe sideways like every other comma 4 list (the rendered c4_grid_2col_3row_names mockup). A tap on a cell flips that region
(green = selected, grey = not), through the same MapDataLayout._on_region the 3X switch uses. The 3X keeps its group lists.

This module is the toolkit-free part (cell geometry, paging, label fitting, hit testing) so it is tested without a window;
the drawing widget is `RegionGridPage` in selfdrive/ui/mici/layouts/settings/bogpilot/widgets.py.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence

COLS, ROWS = 2, 3
PER_PAGE = COLS * ROWS
PAGE_W, PAGE_H = 496, 180      # one stock card slot: full width minus the 20 px pads, the height of a stock BigButton
GAP = 8
PAD_X = 10                     # text padding inside a cell
MAX_FONT, MIN_FONT = 32, 24    # a name is drawn at 32 px, shrunk in 2 px steps to 24 px, then wrapped onto two lines

Cell = tuple[str, str]         # (region code, full name)


def cell_size() -> tuple[float, float]:
  return (PAGE_W - GAP * (COLS - 1)) / COLS, (PAGE_H - GAP * (ROWS - 1)) / ROWS


def cell_origin(index: int) -> tuple[float, float]:
  """Top-left corner of the index-th cell of a page (row-major), relative to the page."""
  cw, ch = cell_size()
  row, col = divmod(index, COLS)
  return col * (cw + GAP), row * (ch + GAP)


def paginate(cells: Sequence[Cell]) -> list[list[Cell]]:
  return [list(cells[i:i + PER_PAGE]) for i in range(0, len(cells), PER_PAGE)]


def sorted_cells(groups: Sequence[tuple[str, Sequence[Cell]]]) -> list[Cell]:
  """Every region of every group once, A-Z by name (case-insensitive), codes breaking ties."""
  once = {code: name for _label, regs in groups for code, name in regs}      # Kazakhstan sits in Asia and Europe: one cell
  return sorted(once.items(), key=lambda c: (c[1].casefold(), c[0]))


def cell_at(x: float, y: float, count: int) -> int | None:
  """Index of the cell under (x, y) (page-relative) among the `count` cells of the page; None for a gap, the pad or an empty slot."""
  cw, ch = cell_size()
  for i in range(min(count, PER_PAGE)):
    ox, oy = cell_origin(i)
    if ox <= x <= ox + cw and oy <= y <= oy + ch:
      return i
  return None


def fit_label(text: str, width: float, measure: Callable[[str, int], float]) -> tuple[list[str], int]:
  """Lines and font size for `text` in `width` px. One line at the largest size from MAX_FONT down to MIN_FONT that fits;
  else two lines at MIN_FONT split at a space (the longest first line that fits, the rest on line two); a line still too wide
  (one very long word) is cut with an ellipsis. `measure(text, size)` is the text width in px."""
  size = MAX_FONT
  while size >= MIN_FONT:
    if measure(text, size) <= width:
      return [text], size
    size -= 2
  size = MIN_FONT
  words = text.split(" ")
  best = None
  for k in range(len(words) - 1, 0, -1):
    first, second = " ".join(words[:k]), " ".join(words[k:])
    if measure(first, size) <= width and measure(second, size) <= width:
      best = (first, second)
      break
  if best is None:
    best = (" ".join(words[:max(1, len(words) // 2)]), " ".join(words[max(1, len(words) // 2):]))
  return [_clip(line, width, size, measure) for line in best if line], size


def _clip(line: str, width: float, size: int, measure: Callable[[str, int], float]) -> str:
  if measure(line, size) <= width:
    return line
  while line and measure(line + "...", size) > width:
    line = line[:-1]
  return line.rstrip() + "..."
