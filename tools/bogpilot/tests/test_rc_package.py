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
    self.write("openpilot/common/version.h", b'#define COMMA_VERSION "0.0.0-synthetic"\n')
    self.write("RELEASES.md", b"Version 0.0.0 (synthetic)\n* notes\n\nolder\n")
    for name in ("git.py", "basedir.py", "swaglog.py"):
      self.write("openpilot/common/" + name, b"# synthetic\n")
    self.write("openpilot/common/version.py", b'BUILD_METADATA_FILENAME = "build.json"\n'
               b"def build_metadata_from_dict(d): pass\ndef get_build_metadata(p): pass\n")
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
    self.git("init", "-q", "-b", "port/synthetic-metadata")
    self.git("remote", "add", "origin", "git@github.com:Example/synthetic.git")
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

  def privacy_fixture(self, report, review_links=False):
    # SYNTHETIC acceptance envelope only; actual track9 smoke is separate.
    shipping = dict(schema_version=1, source_commit=self.sha,
                    files={name: row["sha256"] for name, row in report["entries"].items()},
                    source_exclusions=report.get("source_exclusions", {}))
    self.shipping = self.base / "shipping.json"
    self.shipping.write_bytes(m.canonical(shipping))
    self.evidence = self.base / "privacy.json"
    evidence = dict(schema_version=1, status="pass", checks=[], source=dict(commit=self.sha, clean=True),
                    source_catalog_sha256=report["source_catalog_sha256"],
                    source_catalog_entries=len(report["source_catalog"]), source_scope=report["source_scope"],
                    source_exclusions=[dict(path_id=m.path_id(name), **row) for name,row in sorted(report["source_exclusions"].items())],
                    shipping=dict(manifest_sha256=__import__("hashlib").sha256(m.canonical(shipping)).hexdigest(),
                                  declared_files=len(shipping["files"]), scanned_files=len(shipping["files"]), reviewed_links=[]))
    self.review = None
    if review_links:
      records = {}
      for name,row in report["entries"].items():
        if "target" not in row:
          continue
        original = report["source_catalog"][name]
        target = row["resolved_target"]
        target_hash = report["entries"][target]["sha256"]
        records[name] = dict(kind="internal_link", source_mode=original["mode"], source_blob=original["blob"],
                             shipping_sha256=row["sha256"], link_sha256=row["sha256"], target=target,
                             target_sha256=target_hash, representation="symlink")
        evidence["shipping"]["reviewed_links"].append(dict(path_id=m.path_id(name), source_mode=original["mode"],
          source_blob=original["blob"], link_sha256=row["sha256"], target_path_id=m.path_id(target),
          target_sha256=target_hash, representation="symlink"))
      review = dict(schema_version=1, source_commit=self.sha, source_catalog_sha256=report["source_catalog_sha256"],
                    manifest_sha256=evidence["shipping"]["manifest_sha256"], records=records)
      self.review = self.base / "review.json"
      self.review.write_bytes(m.canonical(review))
      evidence["review"] = dict(sha256=__import__("hashlib").sha256(m.canonical(review)).hexdigest(),
                                source_catalog_sha256=report["source_catalog_sha256"], record_count=len(records))
    self.evidence.write_text(json.dumps(evidence))
    return m.bind_provenance(report, self.evidence, self.shipping, self.review)

  def reviewed_link_fixture(self):
    (self.root / "link").symlink_to("SConstruct")
    self.commit()
    report = self.verify()
    return report, self.privacy_fixture(report, review_links=True)

  def test_exact_reviewed_link_bundle_preserves_source_catalogue(self):
    report, accepted = self.reviewed_link_fixture()
    output = self.base / "reviewed.tar"
    m.bundle(self.root, accepted, output)
    with tarfile.open(output) as tar:
      self.assertTrue(tar.getmember("link").issym())
      metadata = json.load(tar.extractfile("RC_PACKAGE.json"))
      self.assertEqual(metadata["source_catalog"]["link"]["mode"], "120000")
      self.assertEqual(metadata["source_catalog"]["link"]["blob"], report["source_catalog"]["link"]["blob"])

  def test_review_required_for_links(self):
    report, _ = self.reviewed_link_fixture()
    with self.assertRaises(ValueError):
      m.bind_provenance(report, self.evidence, self.shipping)

  def test_review_wrong_source_inventory_catalogue(self):
    report, _ = self.reviewed_link_fixture()
    original = json.loads(self.review.read_text())
    for key,value in (("source_commit", "0"*40), ("manifest_sha256", "0"*64), ("source_catalog_sha256", "0"*64)):
      data = dict(original)
      data[key] = value
      self.review.write_text(json.dumps(data))
      with self.assertRaises(ValueError):
        m.bind_provenance(report, self.evidence, self.shipping, self.review)

  def test_review_link_payload_blob_target_representation_tamper(self):
    report, _ = self.reviewed_link_fixture()
    original = json.loads(self.review.read_text())
    for key,value in (("source_blob", "0"*40), ("link_sha256", "0"*64), ("target_sha256", "0"*64),
                      ("target", "missing"), ("representation", "regular")):
      data = json.loads(json.dumps(original))
      data["records"]["link"][key] = value
      self.review.write_bytes(m.canonical(data))
      # Even a rehashed report must not bypass direct package link checks.
      evidence = json.loads(self.evidence.read_text())
      evidence["review"]["sha256"] = __import__("hashlib").sha256(m.canonical(data)).hexdigest()
      self.evidence.write_text(json.dumps(evidence))
      with self.assertRaises(ValueError):
        m.bind_provenance(report, self.evidence, self.shipping, self.review)

  def test_gate_link_attestation_missing_extra_tampered(self):
    report, _ = self.reviewed_link_fixture()
    original = json.loads(self.evidence.read_text())
    for rows in ([], original["shipping"]["reviewed_links"] * 2):
      data = json.loads(json.dumps(original));data["shipping"]["reviewed_links"] = rows
      self.evidence.write_text(json.dumps(data))
      with self.assertRaises(ValueError):
        m.bind_provenance(report, self.evidence, self.shipping, self.review)

  def excluded_fixture(self, name=".env"):
    self.write(name, b"synthetic nonshipping fixture")
    self.commit()
    original = m.source_catalog(self.root, self.sha)[name]
    exclusion = dict(source_mode=original["mode"], source_blob=original["blob"], reason="private_or_build_host_only")
    self.shipping = self.base / "exclusions.json"
    self.shipping.write_text(json.dumps(dict(schema_version=1, source_commit=self.sha, source_exclusions={name:exclusion})))
    report = m.verify(self.root, self.sha, self.manifest, self.shipping)
    return report

  def test_exclusions_are_catalogued_not_full_source_and_not_opened(self):
    report = self.excluded_fixture()
    self.assertNotIn(".env", report["entries"])
    self.assertIn(".env", report["source_catalog"])
    self.assertEqual(report["source_scope"], "cataloged_source_with_explicit_exclusions")
    self.assertNotEqual(report["kind"], "full-tree-test-build")
    accepted = self.privacy_fixture(report)
    self.assertTrue(accepted["provenance_gate_pass"])

  def test_cli_static_excluded_source_does_not_claim_privacy_pass(self):
    self.excluded_fixture()
    output = self.base / "static-report.json"
    self.assertEqual(m.main(["verify", "--root", str(self.root), "--candidate", self.sha,
      "--artifact-manifest", str(self.manifest), "--shipping-manifest", str(self.shipping),
      "--report", str(output)]), 0)
    result = json.loads(output.read_text())
    self.assertEqual(result["source_scope"], "cataloged_source_with_explicit_exclusions")
    self.assertFalse(result["provenance_gate_pass"])

  def test_exclusions_bad_blob_or_required_notice_blocked(self):
    report = self.excluded_fixture()
    source = json.loads(self.shipping.read_text())
    source["source_exclusions"][".env"]["source_blob"] = "0" * 40
    self.shipping.write_text(json.dumps(source))
    with self.assertRaises(ValueError):
      m.verify(self.root, self.sha, self.manifest, self.shipping)
    with self.assertRaisesRegex(ValueError, "exclusion"):
      self.excluded_fixture("LICENSE")

  def test_attested_exclusion_scope_tamper_blocked(self):
    report = self.excluded_fixture()
    self.privacy_fixture(report)
    data = json.loads(self.evidence.read_text())
    data["source_scope"] = "complete_tracked_source_and_explicit_artifacts"
    self.evidence.write_text(json.dumps(data))
    with self.assertRaises(ValueError):
      m.bind_provenance(report, self.evidence, self.shipping)

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

  def test_public_certificate_after_long_comment(self):
    self.write("openpilot/common/esim/gsma_ci_bundle.pem", b"# synthetic public bundle comment\n" * 12 + b"-----BEGIN CERTIFICATE-----\nsynthetic\n-----END CERTIFICATE-----\n")
    self.commit()
    self.verify()

  def test_private_marker_after_public_certificate_refused(self):
    self.write("openpilot/common/esim/gsma_ci_bundle.pem", b"# synthetic comment\n" * 20 + b"-----BEGIN CERTIFICATE-----\nsynthetic\n-----END CERTIFICATE-----\n" + b"-----BEGIN " + b"PRIVATE KEY-----\nsynthetic only\n")
    self.commit()
    with self.assertRaisesRegex(ValueError, "public CA"):
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


class BuildMetadataTests(PackageTests):
  """Regression: archives previously shipped without build.json (bench startup stopped)."""
  def bundle_ok(self):
    report = self.privacy_fixture(self.verify())
    out = self.base / "meta.tar"
    m.bundle(self.root, report, out)
    return report, out

  def test_archive_contains_validated_bound_build_json(self):
    report, out = self.bundle_ok()
    with tarfile.open(out) as tar:
      raw = tar.extractfile("build.json").read()
    data = m.validate_build_metadata(raw, self.sha)
    self.assertEqual(data["openpilot"]["git_commit"], self.sha)
    self.assertFalse(data["openpilot"]["is_dirty"])
    self.assertEqual(data["channel"], "port/synthetic-metadata")
    self.assertEqual(data["openpilot"]["version"], "0.0.0-synthetic")
    self.assertEqual(m.check_archive(out, self.sha), report["build_metadata_sha256"])
    self.assertEqual(m.main(["check-archive", "--root", str(self.root), "--candidate", self.sha,
                             "--artifact-manifest", str(self.manifest), "--report", str(self.base / "x.json"),
                             "--output", str(out)]), 0)

  def test_archive_without_build_json_fails(self):
    _, out = self.bundle_ok()
    stripped = self.base / "stripped.tar"
    with tarfile.open(out) as src, tarfile.open(stripped, "w") as dst:
      for info in src.getmembers():
        if info.name != "build.json":
          dst.addfile(info, src.extractfile(info) if info.isfile() else None)
    with self.assertRaisesRegex(ValueError, "missing"):
      m.check_archive(stripped, self.sha)

  def test_wrong_candidate_sha_fails(self):
    _, out = self.bundle_ok()
    with self.assertRaisesRegex(ValueError, "SHA mismatch"):
      m.check_archive(out, "f" * 40)

  def test_invalid_json_and_schema_fail(self):
    good = m.generate_build_metadata(self.root, self.sha)
    with self.assertRaisesRegex(ValueError, "valid JSON"):
      m.validate_build_metadata(b"{not json", self.sha)
    data = json.loads(good)
    for mutate in (lambda d: d.pop("channel"), lambda d: d["openpilot"].pop("version"),
                   lambda d: d["openpilot"].__setitem__("extra", "x"),
                   lambda d: d["openpilot"].__setitem__("is_dirty", True),
                   lambda d: d["openpilot"].__setitem__("is_dirty", "false"),
                   lambda d: d["openpilot"].__setitem__("build_style", "release"),
                   lambda d: d.__setitem__("channel", "release-tizi"),
                   lambda d: d.__setitem__("channel", "HEAD"),
                   lambda d: d["openpilot"].__setitem__("git_origin", "https://user:token@github.com/a/b.git"),
                   lambda d: d["openpilot"].__setitem__("git_origin", "/Users/someone/private-repo"),
                   lambda d: d["openpilot"].__setitem__("git_commit_date", "yesterday")):
      bad = json.loads(good)
      mutate(bad)
      with self.assertRaises(ValueError):
        m.validate_build_metadata(json.dumps(bad).encode(), self.sha)

  def test_dirty_or_wrong_head_refuses_generation(self):
    self.write("SConstruct", b"# modified\n")
    with self.assertRaisesRegex(ValueError, "dirty"):
      m.generate_build_metadata(self.root, self.sha)
    with self.assertRaisesRegex(ValueError, "HEAD"):
      m.generate_build_metadata(self.root, "0" * 40)

  def test_detached_head_refused_not_fabricated(self):
    self.git("checkout", "-q", "--detach")
    with self.assertRaisesRegex(ValueError, "channel"):
      m.generate_build_metadata(self.root, self.sha)

  def test_missing_runtime_prerequisite_blocks_verify(self):
    for name in ("openpilot/common/version.py", "RELEASES.md"):
      self.git("rm", "-q", name)
      self.commit()
      with self.assertRaisesRegex(ValueError, "prerequisite"):
        self.verify()
      self.git("checkout", "-q", "HEAD~1", "--", name)
      (self.root / name).chmod(0o644)  # independent of host umask
      self.commit()

  def test_runtime_api_drift_blocks_verify(self):
    self.write("openpilot/common/version.py", b'BUILD_METADATA_FILENAME = "meta.json"\n')
    self.commit()
    with self.assertRaisesRegex(ValueError, "runtime API"):
      self.verify()

  def test_tracked_build_json_refused(self):
    self.write("build.json", b"{}")
    self.commit()
    with self.assertRaises(ValueError):
      self.verify()


class RealVersionModuleTests(unittest.TestCase):
  """Deserialize generated metadata with THIS checkout's openpilot/common/version.py.
  Logging/git helper modules are stubbed (only the build.json branch is exercised);
  this is the source schema API check, not a packaged-device runtime import."""
  def test_real_schema_roundtrip(self):
    repo = Path(__file__).resolve().parents[3]
    import sys, types, dataclasses
    stubs = {"openpilot": types.ModuleType("openpilot"), "openpilot.common": types.ModuleType("openpilot.common"),
             "openpilot.common.basedir": types.ModuleType("b"), "openpilot.common.swaglog": types.ModuleType("s"),
             "openpilot.common.git": types.ModuleType("g")}
    stubs["openpilot.common.basedir"].BASEDIR = str(repo)
    stubs["openpilot.common.swaglog"].cloudlog = None
    for n in ("get_commit", "get_origin", "get_branch", "get_short_branch", "get_commit_date"):
      setattr(stubs["openpilot.common.git"], n, lambda *a, **k: "")
    with patch.dict(sys.modules, stubs):
      vs = importlib.util.spec_from_file_location("op_version_real", repo / "openpilot/common/version.py")
      v = importlib.util.module_from_spec(vs)
      vs.loader.exec_module(v)
      if subprocess.call(["git", "-C", str(repo), "rev-parse", "--show-toplevel"], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL) != 0:
        self.skipTest("not run from a Git checkout")
      head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"]).decode().strip()
      dirty = subprocess.check_output(["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=no"]).strip()
      branch = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"]).decode().strip()
      if dirty or branch == "HEAD":
        self.skipTest("real checkout dirty/detached; generation correctly refuses")
      raw = m.generate_build_metadata(repo, head)
      with tempfile.TemporaryDirectory() as d:
        Path(d, v.BUILD_METADATA_FILENAME).write_bytes(raw)
        meta = v.get_build_metadata(d)
      self.assertEqual(dataclasses.asdict(meta), json.loads(raw))
      self.assertEqual(meta.openpilot.git_commit, head)
      self.assertFalse(meta.release_channel)
      self.assertFalse(meta.tested_channel)
