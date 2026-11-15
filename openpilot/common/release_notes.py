"""Latest what's-new notes from a build's RELEASES.md.

The offroad update splash and the software Install row read these from the
incoming build, not the running one. Missing or empty notes become an empty
string so the UI can show a fallback.
"""
from __future__ import annotations

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


def latest_release_notes_html(basedir: str) -> bytes:
  """HTML for the first RELEASES.md section, or b'' if none can be shown."""
  md = latest_release_notes_markdown(basedir)
  if not md:
    return b""
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
