import os

from openpilot.common.swaglog import cloudlog

# Legacy xattr name kept so existing on-disk route metadata stays readable (inert, no upload).
UPLOAD_ATTR_NAME = 'user.upload'
UPLOAD_ATTR_VALUE = b'1'


def get_directory_sort(d: str) -> list[str]:
  return [s.rjust(10, '0') for s in d.rsplit('--', 1)]


def listdir_by_creation(d: str) -> list[str]:
  if not os.path.isdir(d):
    return []

  try:
    paths = [f for f in os.listdir(d) if os.path.isdir(os.path.join(d, f))]
    return sorted(paths, key=get_directory_sort)
  except OSError:
    cloudlog.exception("listdir_by_creation failed")
    return []
