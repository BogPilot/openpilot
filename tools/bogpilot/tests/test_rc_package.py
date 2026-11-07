"""Synthetic sandbox git trees and ELF headers only; never native build/runtime tests."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import tarfile

spec = importlib.util.spec_from_file_location("rc_package", Path(__file__).parents[1] / "rc_package.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class PackageTests(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.addCleanup(self.tmp.cleanup)
    self.base = Path(self.tmp.name)
    self.root = self.base / "source"
    self.root.mkdir()
    self.manifest = self.base / "artifacts.json"
    for name in m.SOURCE_REQUIRED:
      self.write(name, b"# synthetic fixture\n")
    self.write("launch_env.sh", b'export AGNOS_VERSION="19.9"\n')
    self.write("openpilot/system/manager/process_config.py", b'procs = []\n')
    self.write("common/version.h", b'"synthetic"\n')
    for name in m.MODELS:
      self.write("openpilot/selfdrive/modeld/models/" + name, b"synthetic" * 12501)
    self.artifacts = []
    elf = bytearray(64)
    elf[:6] = b"\x7fELF\x02\x01"
    elf[18:20] = (183).to_bytes(2, "little")
    for name in m.NATIVE_REQUIRED:
      self.write(name, bytes(elf), 0o755)
      self.add_artifact(name, "elf-aarch64")
    for name in ("panda/board/obj/panda_h7.bin.signed", "panda/board/obj/bootstub.panda_h7.bin"):
      self.write(name, b"synthetic firmware", 0o644)
      self.add_artifact(name, "data")
    self.git("init", "-q")
    self.git("config", "user.name", "Synthetic Test")
    self.git("config", "user.email", "synthetic@example.invalid")
    self.commit()

  def git(self, *args):
    return subprocess.check_output(["git", "-C", str(self.root), *args], stderr=subprocess.DEVNULL).decode().strip()

  def write(self, name, value, mode=0o644):
    path = self.root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)
    path.chmod(mode)

  def add_artifact(self, name, format):
    path = self.root / name
    self.artifacts.append(dict(path=name, sha256=m.digest(path), size=path.stat().st_size,
                               mode=f"{path.stat().st_mode & 0o777:04o}", format=format))

  def commit(self):
    (self.root / ".panda-source.json").unlink(missing_ok=True)
    self.git("add", ".")
    self.git("commit", "-qm", "synthetic fixture")
    self.sha = self.git("rev-parse", "HEAD")
    # Regenerate the unsigned panda source manifest with its exact inventory.
    files = {"SConstruct", "common/version.h"}
    for scope in ("panda", "opendbc_repo/opendbc/safety"):
      for path in (self.root / scope).rglob("*"):
        if path.is_file() and "obj" not in path.parts:
          files.add(path.relative_to(self.root).as_posix())
    hashes = {name: m.digest(self.root / name) for name in sorted(files)}
    self.write(".panda-source.json", m.canonical(dict(schema=1, source_commit=self.sha, dirty=False,
               version='"synthetic"', files=hashes,
               source_sha256=__import__("hashlib").sha256(m.canonical(hashes)).hexdigest())))
    self.data = dict(schema=1, candidate_sha=self.sha, agnos_version="19.9", architecture="aarch64", artifacts=self.artifacts)
    self.save_manifest()

  def save_manifest(self):
    self.manifest.write_text(json.dumps(self.data))

  def verify(self):
    return m.verify(self.root, self.sha, self.manifest)

  def privacy_fixture(self, report):
    # SYNTHETIC acceptance envelope only; no claim of running track9 on final bytes.
    shipping = dict(schema_version=1, source_commit=self.sha,
                    files={name: row["sha256"] for name, row in report["entries"].items()})
    self.shipping = self.base / "shipping.json"
    self.shipping.write_bytes(m.canonical(shipping))
    self.evidence = self.base / "privacy.json"
    evidence = dict(schema_version=1, status="pass", checks=[], source=dict(commit=self.sha, clean=True),
                    shipping=dict(manifest_sha256=__import__("hashlib").sha256(m.canonical(shipping)).hexdigest(),
                                  declared_files=len(shipping["files"]), scanned_files=len(shipping["files"])))
    self.evidence.write_text(json.dumps(evidence))
    return m.bind_provenance(report, self.evidence, self.shipping)

  def test_bundle_requires_privacy_gate(self):
    with self.assertRaisesRegex(ValueError, "provenance"):
      m.bundle(self.root, self.verify(), self.base / "not-approved.tar")

  def test_privacy_evidence_exact_inventory_and_candidate(self):
    report = self.verify()
    self.privacy_fixture(report)
    data = json.loads(self.shipping.read_text())
    data["files"].pop("SConstruct")
    self.shipping.write_text(json.dumps(data))
    with self.assertRaises(ValueError):
      m.bind_provenance(report, self.evidence, self.shipping)
    self.privacy_fixture(report)
    data = json.loads(self.evidence.read_text())
    data["source"]["commit"] = "0" * 40
    self.evidence.write_text(json.dumps(data))
    with self.assertRaises(ValueError):
      m.bind_provenance(report, self.evidence, self.shipping)

  def test_full_tree_static_metadata(self):
    report = self.verify()
    self.assertFalse(report["installable"])
    self.assertFalse(report["road_validated"])
    self.assertEqual(report["candidate_sha"], self.sha)
    self.assertEqual(report, self.verify())

  def test_deterministic_archive_and_no_untracked_private_data(self):
    self.write(".env", b"SYNTHETIC_ONLY=not-a-real-secret")
    report = self.privacy_fixture(self.verify())
    first, second = self.base / "a.tar", self.base / "b.tar"
    self.assertEqual(m.bundle(self.root, report, first), m.bundle(self.root, report, second))
    with tarfile.open(first) as tar:
      self.assertNotIn(".env", tar.getnames())
      self.assertNotIn(".git", tar.getnames())
      metadata = json.load(tar.extractfile("RC_PACKAGE.json"))
      self.assertFalse(metadata["installable"])

  def test_manifest_cannot_disguise_dirty_source(self):
    self.write("SConstruct", b"changed source")
    self.add_artifact("SConstruct", "data")
    self.save_manifest()
    with self.assertRaisesRegex(ValueError, "differs"):
      self.verify()

  def test_missing_python_runtime_is_detected(self):
    self.write("openpilot/system/manager/process_config.py", b'PythonProcess("missing", "openpilot.missing", True)\n')
    self.commit()
    with self.assertRaisesRegex(ValueError, "Python runtime"):
      self.verify()

  def test_arm_firmware_elf_is_not_arm64_runtime(self):
    value = bytearray(64)
    value[:6] = b"\x7fELF\x01\x01"
    value[18:20] = (40).to_bytes(2, "little")
    name = "panda/board/obj/panda_h7/main.elf"
    self.write(name, bytes(value))
    self.add_artifact(name, "elf-arm")
    self.save_manifest()
    self.assertIn(name, self.verify()["entries"])

  def test_internal_gitlink_initialized_and_exact(self):
    dependency = self.root / "dependency"
    dependency.mkdir()
    subprocess.run(["git", "-C", str(dependency), "init", "-q"], check=True)
    (dependency / "source.py").write_text("# synthetic dependency\n")
    subprocess.run(["git", "-C", str(dependency), "add", "."], check=True)
    subprocess.run(["git", "-C", str(dependency), "-c", "user.name=Synthetic", "-c", "user.email=synthetic@example.invalid", "commit", "-qm", "synthetic dependency"], check=True)
    subsha = subprocess.check_output(["git", "-C", str(dependency), "rev-parse", "HEAD"]).decode().strip()
    self.git("update-index", "--add", "--cacheinfo", "160000," + subsha + ",dependency")
    self.commit()
    self.assertIn("dependency/source.py", self.verify()["entries"])
    (dependency / "source.py").write_text("# changed synthetic dependency\n")
    with self.assertRaisesRegex(ValueError, "differs"):
      self.verify()

  def test_candidate_mismatch(self):
    with self.assertRaises(ValueError):
      m.verify(self.root, "0" * 40, self.manifest)

  def test_missing_manifest(self):
    self.manifest.unlink()
    with self.assertRaises(FileNotFoundError):
      self.verify()

  def test_wrong_agnos_or_architecture(self):
    for key, value in (("agnos_version", "12.8"), ("architecture", "x86_64")):
      with self.subTest(key=key):
        old = self.data[key]
        self.data[key] = value
        self.save_manifest()
        with self.assertRaises(ValueError):
          self.verify()
        self.data[key] = old

  def test_native_checksum_mismatch(self):
    self.write(m.NATIVE_REQUIRED[0], b"wrong", 0o755)
    with self.assertRaises(ValueError):
      self.verify()

  def test_wrong_architecture_header(self):
    path = self.root / m.NATIVE_REQUIRED[0]
    value = bytearray(path.read_bytes())
    value[18:20] = (62).to_bytes(2, "little")
    path.write_bytes(value)
    self.artifacts[0]["sha256"] = m.digest(path)
    self.save_manifest()
    with self.assertRaisesRegex(ValueError, "AArch64"):
      self.verify()

  def test_source_dirty(self):
    self.write("SConstruct", b"changed")
    with self.assertRaisesRegex(ValueError, "differs"):
      self.verify()

  def test_missing_runtime_or_model(self):
    (self.root / m.NATIVE_REQUIRED[0]).unlink()
    with self.assertRaises(FileNotFoundError):
      self.verify()

  def test_lfs_pointer(self):
    self.write("asset.bin", b"version https://git-lfs.github.com/spec/v1\n")
    self.commit()
    with self.assertRaisesRegex(ValueError, "LFS"):
      self.verify()

  def test_permission_loss(self):
    (self.root / m.NATIVE_REQUIRED[0]).chmod(0o644)
    with self.assertRaises(ValueError):
      self.verify()

  def test_unsafe_permissions(self):
    (self.root / "SConstruct").chmod(0o666)
    with self.assertRaisesRegex(ValueError, "permissions"):
      self.verify()

  def test_external_or_dangling_symlink(self):
    (self.root / "link").symlink_to("../outside")
    self.commit()
    with self.assertRaises((ValueError, FileNotFoundError)):
      self.verify()

  def test_unshipped_symlink_target_refused(self):
    self.write("untracked-target", b"synthetic")
    (self.root / "link").symlink_to("untracked-target")
    self.git("add", "link")
    self.git("commit", "-qm", "synthetic link")
    self.sha = self.git("rev-parse", "HEAD")
    self.data["candidate_sha"] = self.sha
    self.save_manifest()
    with self.assertRaisesRegex(ValueError, "not shipped"):
      self.verify()

  def test_safe_symlink(self):
    (self.root / "link").symlink_to("SConstruct")
    self.commit()
    self.assertEqual(self.verify()["entries"]["link"]["target"], "SConstruct")

  def test_paths_private_and_traversal(self):
    for name in ("../escape", "/absolute", ".git/config", "secrets/values", "rlog.bz2", ".env", "params/CarVin", "RC_PACKAGE.json"):
      with self.subTest(name=name), self.assertRaises(ValueError):
        m.safe_name(name)
    m.safe_name("opendbc_repo/opendbc/car/rlog.capnp")
    m.safe_name("tools/scripts/qlog_size.py")

  def test_private_tracked_path(self):
    self.write(".env", b"synthetic")
    self.commit()
    with self.assertRaisesRegex(ValueError, "private"):
      self.verify()

  def test_panda_provenance_stale(self):
    path = self.root / ".panda-source.json"
    data = json.loads(path.read_text())
    data["source_commit"] = "0" * 40
    path.write_text(json.dumps(data))
    with self.assertRaisesRegex(ValueError, "provenance"):
      self.verify()

  def test_missing_native_coverage(self):
    self.data["artifacts"] = self.artifacts[1:]
    self.save_manifest()
    with self.assertRaisesRegex(ValueError, "coverage"):
      self.verify()

  def test_uninitialized_submodule(self):
    self.git("update-index", "--add", "--cacheinfo", "160000," + self.sha + ",dependency")
    self.git("commit", "-qm", "synthetic gitlink")
    self.sha = self.git("rev-parse", "HEAD")
    self.data["candidate_sha"] = self.sha
    self.save_manifest()
    with self.assertRaises((ValueError, subprocess.CalledProcessError)):
      self.verify()

  def test_archive_recheck_and_no_overwrite(self):
    report = self.privacy_fixture(self.verify())
    self.write("SConstruct", b"changed")
    with self.assertRaises(ValueError):
      m.bundle(self.root, report, self.base / "bad.tar")
    self.assertFalse((self.base / "bad.tar").exists())
    output = self.base / "exists.tar"
    output.touch()
    with self.assertRaises(ValueError):
      m.bundle(self.root, report, output)

  def test_output_restrictions(self):
    for path in (self.root / "bundle.tar", Path("/data/candidate.tar"), Path("/cache/candidate.tar")):
      with self.assertRaises(ValueError):
        m.outside(self.root, path)

  def test_cli_report_archive_collision(self):
    output = self.base / "collision"
    self.assertEqual(m.main(["bundle", "--root", str(self.root), "--candidate", self.sha,
                     "--artifact-manifest", str(self.manifest), "--report", str(output),
                     "--output", str(output)]), 1)
    self.assertFalse(output.exists())

  def test_private_symlink_target_refused(self):
    self.write(".env", b"synthetic-only")
    (self.root / "link").symlink_to(".env")
    self.git("add", "link")
    self.git("commit", "-qm", "synthetic link")
    self.sha = self.git("rev-parse", "HEAD")
    self.data["candidate_sha"] = self.sha
    self.save_manifest()
    with self.assertRaisesRegex(ValueError, "private"):
      self.verify()

  def test_cli_failure_nonzero_without_pass_report(self):
    report = self.base / "report.json"
    self.manifest.unlink()
    self.assertEqual(m.main(["verify", "--root", str(self.root), "--candidate", self.sha,
                     "--artifact-manifest", str(self.manifest), "--report", str(report)]), 1)
    self.assertFalse(report.exists())


if __name__ == "__main__":
  unittest.main()
