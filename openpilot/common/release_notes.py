"""Latest what's-new notes from a build's RELEASES.md.

The offroad update splash and the software Install row read these from the
incoming build, not the running one. Missing or empty notes become an empty
string so the UI can show a fallback.

The stored notes are cut at a whole line, ending with an ellipsis item, when
they would not fit the comma 3X update splash without scrolling. The splash
scroll range is measured from the unwrapped text, so longer notes were cut off
mid-line and their end could not be reached.
"""
from __future__ import annotations

import math
import os
import re
from html import unescape

from openpilot.common.markdown import parse_markdown


def latest_release_notes_markdown(basedir: str) -> str:
  """Return the first RELEASES.md section in basedir, or '' if missing or empty."""
  path = os.path.join(basedir, "RELEASES.md")
  try:
    with open(path, encoding="utf-8") as f:
      text = f.read().lstrip("\n")
  except (FileNotFoundError, OSError, UnicodeDecodeError):
    return ""
  if not text.strip():
    return ""
  return text.split("\n\n", 1)[0]


# comma 3X update splash geometry, from a headless render at 2160x1080 (notes area 1920 x 580 px):
# the heading takes 136 px, each list item 12 px plus 50 px per wrapped line, and a line of
# ordinary text holds about 85 characters. The values below are rounded to the safe side.
SPLASH_BODY_PX = 443          # 580 px of notes below the 136 px heading
SPLASH_ITEM_PX = 12
SPLASH_LINE_PX = 51
SPLASH_CHARS_PER_LINE = 80
ELLIPSIS_ITEM = "* \u2026"


def _item_px(text: str, chars_per_line: int) -> int:
  return SPLASH_ITEM_PX + SPLASH_LINE_PX * max(1, math.ceil(len(text) / chars_per_line))


def fit_release_notes_markdown(md: str, body_px: int = SPLASH_BODY_PX,
                               chars_per_line: int = SPLASH_CHARS_PER_LINE) -> str:
  """Keep whole lines of md that fit in body_px of the splash; if any are dropped, end with an ellipsis item.

  The heading (a line followed by '===') is always kept. A list item that only introduces dropped
  sub-items (ends with ':') is dropped with them.
  """
  lines = md.split("\n")
  head = 2 if len(lines) > 1 and lines[1].startswith("===") else 0
  budget = body_px - _item_px("\u2026", chars_per_line)  # room is kept for the ellipsis item
  kept, used, cut = lines[:head], 0, False
  for line in lines[head:]:
    text = line.strip()
    if not text:
      continue
    cost = _item_px(text.lstrip("* "), chars_per_line)
    if used + cost > budget:
      cut = True
      break
    kept.append(line)
    used += cost
  if not cut:
    return md
  while len(kept) > head and kept[-1].rstrip().endswith(":"):
    kept.pop()
  return "\n".join(kept + [ELLIPSIS_ITEM])


def latest_release_notes_html(basedir: str) -> bytes:
  """HTML for the first RELEASES.md section, cut to fit the update splash, or b'' if none can be shown."""
  md = latest_release_notes_markdown(basedir)
  if not md:
    return b""
  md = fit_release_notes_markdown(md)
  try:
    return parse_markdown(md).encode("utf-8")
  except Exception:
    return (md if md.endswith("\n") else md + "\n").encode("utf-8")


def release_notes_plain(notes: bytes | str) -> str:
  """Strip HTML tags from stored release notes for compact text views."""
  if isinstance(notes, (bytes, bytearray)):
    text = notes.decode("utf-8", "replace")
  else:
    text = notes
  text = unescape(re.sub(r"<[^>]+>", "\n", text))
  return "\n".join(line.strip() for line in text.splitlines() if line.strip())
