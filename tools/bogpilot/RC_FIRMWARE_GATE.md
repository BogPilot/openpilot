# Independent local candidate firmware gate

This read-only gate requires a **full final source commit**, a real clean checkout,
a matching exported archive, both preserved native builds, and hash manifests.
It never stamps, signs, flashes, modifies existing identity tooling, or promotes a
candidate. Missing evidence is FAIL, not SKIP/PASS. An output-artifact commit is
not the source commit. Never substitute an earlier integration tip for final SHA.

Checks independently implemented (does not import panda/build_identity.py):
- Real checkout HEAD equals explicit full candidate SHA, clean except documented
  generated identity/obj/SCons files. All source manifest inputs and full SHA256
  match actual source AND archive, source version and `dirty:false` required.
- Pinned build policy, checked on the source checkout and on the archive (no fixed
  baseline commit): SHA256 of the debug and release public certificates, every
  compiler/linker flag literal in panda/SConscript (in order), the DEBUG signing
  selection (in-repo debug key, both public keys embedded) and the toolchain
  (`arm-none-eabi-gcc` 13.2.1, Arm GNU Toolchain 13.2.rel1, from agnos:19.9-build),
  which must match the artifact record and the ELF `.comment` of both ELFs. Change a
  pin only together with a reviewed signing, flag or toolchain change, and rebuild
  the prebuilt firmware in the same release (panda/BUILD_IDENTITY.md, Release rule).
- Both signed panda_h7/body_h7 images contain exactly the expected full source
  SHA / clean / fingerprint / DEBUG version; size/trailer and existing SHA1/RSA
  debug public-key signatures are verified without reading a private key.
- Both H7 source compile-command records include existing ALLOW_DEBUG/H7 flags
  and correct body selection; generated version and ELF identities match.
- Artifact manifests bind both signed images and both ELFs to source identity
  and full output hashes. Two independently executed clean builds must produce
  identical output hashes. Same evidence directory cannot stand in for a repeat.
- Archive generated inventory exclusions: obj/cache/.o/.so/.pyc/SCons databases
  and compile_commands.json, and test files (tests directories, test_*.py,
  conftest.py), exactly as documented by panda/build_identity.py.

Limits: manifests and compile commands are unsigned local build evidence, not
host attestation. Gate cannot establish that somebody did not fabricate evidence
or merely copy the first build into a second directory. The release builder must
execute and log both builds. This gate is not firmware safety certification,
whole-system validation, device validation, or proof of safe road behavior.

## Final recipe (run by the firmware build step, not by this gate)

Do not execute long builds before final source SHA is frozen. Existing DEBUG,
ALLOW_DEBUG, signing and keys remain unchanged. No binary commits or device access.

1. Assemble all source changes, including gate, on an isolated candidate branch;
   commit with approved identity/hooks. Freeze `FINAL` to its full 40-hex SHA.
   Source checkout must be clean, not merely clean in firmware directories.
   Existing checked-in native outputs are not accepted as fresh build evidence.
2. From that exact checkout, with output paths outside the source tree:

```bash
SOURCE=/absolute/path/to/final-candidate-checkout
OUT=/absolute/path/to/private-firmware-evidence
mkdir -p "$OUT"
cd "$SOURCE"
FINAL=$(git rev-parse HEAD)
python3 panda/build_identity.py export
# Manifest is generated, never add it to Git. Preserve symlinks AND their tracked targets.
git archive --format=tar "$FINAL" > "$OUT/final-source.tar"
cp .panda-source.json "$OUT/source-manifest.json"
printf '%s\n' "$FINAL" > "$OUT/final-source-commit"
```

3. Transfer source tar and source-manifest.json to a NEW isolated VM build tree.
   Extract full tar (not just a symlink without its target); copy manifest as root
   `.panda-source.json`. Keep a separate extracted reference archive root. Never
   manufacture .git metadata. The firmware build step takes the normal build lock atomically,
   owns/reports liveness and releases in EXIT trap. Never steal another lock.
4. Build with the release build path (the cb8/cb11 combined build scripts on the
   AGNOS VM): **agnos:19.9-build**, a build slot lock, 4 GB memory cap, network
   off, `/dev/null` bound at `/dev/ion`, run as the VM user, no flash. Extract the
   source tar and manifest into two NEW separate trees (`build1`, `build2`) and build
   each once, from clean, mounted at `/data/openpilot`:

```bash
set -euo pipefail
unset RELEASE
export PATH=/usr/local/venv/bin:/usr/local/.cargo/bin:/usr/bin:/usr/local/bin:/bin HOME=/scratch/home
mkdir -p $HOME; cd /data/openpilot
rm -rf panda/board/obj panda/tests/libpanda/libpanda.so && mkdir -p panda/board/obj
python3 panda/build_identity.py verify            # DEV-<source commit>-c-<identity>-DEBUG
arm-none-eabi-gcc --version | head -1              # must equal the pinned toolchain
scons -j2 panda/board/obj/panda_h7.bin.signed panda/board/obj/body_h7.bin.signed \
  panda/board/obj/bootstub.panda_h7.bin panda/board/obj/bootstub.body_h7.bin \
  panda/tests/libpanda/libpanda.so compile_commands.json
```

   For each tree write the evidence directory: the four OUTPUTS, `panda/board/obj/version`,
   the root `compile_commands.json` and `rc-firmware-artifacts.json` with `source_commit`,
   `source_sha256` (from the manifest), `version`, `toolchain` (the first line above) and
   the SHA256 of the four OUTPUTS. Compare every output of the two trees byte for byte
   (all of `panda/board/obj` and `libpanda.so`) before any artifact commit.

5. Transfer preserved build1/build2 evidence back to private staging,
   without modifying the frozen source checkout, then run:

```bash
python3 "$SOURCE/tools/bogpilot/rc_firmware_gate.py" \
  --source "$SOURCE" --archive "$OUT/extracted-reference-archive" \
  --artifacts "$OUT/build1" --repeat "$OUT/build2" --candidate "$FINAL" \
  > "$OUT/firmware-gate-result.json"
```

Expected final native result is unrun until the firmware build step runs; synthetic
unit tests do not replace it. Gate source commit changes require a new export and
build; do not relabel earlier artifacts as the new source.
