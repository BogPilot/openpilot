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
- Board, safety and signing/build files unchanged against immutable policy
  baseline f5928f3b168159129bc88b8f65c9f53b3f73039d. That baseline is **only** a
  policy comparison, never the firmware source version.
- Both signed panda_h7/body_h7 images contain exactly the expected full source
  SHA / clean / fingerprint / DEBUG version; size/trailer and existing SHA1/RSA
  debug public-key signatures are verified without reading a private key.
- Both H7 source compile-command records include existing ALLOW_DEBUG/H7 flags
  and correct body selection; generated version and ELF identities match.
- Artifact manifests bind both signed images and both ELFs to source identity
  and full output hashes. Two independently executed clean builds must produce
  identical output hashes. Same evidence directory cannot stand in for a repeat.
- Archive generated inventory exclusions: obj/cache/.o/.so/.pyc/SCons databases
  and compile_commands.json, exactly as documented by existing panda tooling.

Limits: manifests and compile commands are unsigned local build evidence, not
host attestation. Gate cannot establish that somebody did not fabricate evidence
or merely copy the first build into a second directory. The build coordinator must
execute and log both builds. This gate is not firmware safety certification,
whole-system validation, device validation, or proof of safe road behavior.

## Final recipe (track10 owns execution, not this track)

Do not execute long builds before final source SHA is frozen. Existing DEBUG,
ALLOW_DEBUG, signing and keys remain unchanged. No binary commits or device access.

1. Assemble all source changes, including gate, on an isolated candidate branch;
   commit with approved identity/hooks. Freeze `FINAL` to its full 40-hex SHA.
   Source checkout must be clean, not merely clean in firmware directories.
   Existing checked-in native outputs are not accepted as fresh build evidence.
2. From that exact checkout (on M4P48), outside output paths in the source tree:

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
   manufacture .git metadata. Track10 acquires normal VM build lock atomically,
   owns/reports liveness and releases in EXIT trap. Never steal another lock.
4. In **agnos:19.9-build**, mount isolated tree at `/data/openpilot`, existing
   matching dependency venv read-only, matching `/opt/uv-python` read-only, and
   evidence directory at `/evidence`. Set the existing compiler environment:

```bash
set -euo pipefail
unset RELEASE
export PATH=/data/openpilot/.venv/bin:/usr/bin:/usr/local/venv/bin:/bin
export PYTHONPATH=/data/openpilot:/data/openpilot/opendbc_repo
cat /VERSION > /evidence/agnos-version
arm-none-eabi-gcc --version > /evidence/compiler-version
cd /data/openpilot
python3 panda/build_identity.py verify > /evidence/source-version
python3 -m unittest discover -s panda/tests -p test_build_identity.py
python3 -m unittest discover -s tools/bogpilot/tests -p test_rc_firmware_gate.py
cd panda
for run in 1 2; do
  scons -c board/obj/panda_h7.bin.signed board/obj/body_h7.bin.signed compile_commands.json > "/evidence/clean${run}.log" 2>&1
  scons -j6 board/obj/panda_h7.bin.signed board/obj/body_h7.bin.signed compile_commands.json > "/evidence/build${run}.log" 2>&1
  RUN="$run" python3 - <<'PY'
import hashlib, json, os, shutil
from pathlib import Path
root = Path('/data/openpilot')
dest = Path('/evidence') / ('build' + os.environ['RUN'])
dest.mkdir(exist_ok=False)
manifest = json.loads((root / '.panda-source.json').read_text())
outputs = ('panda/board/obj/panda_h7.bin.signed', 'panda/board/obj/body_h7.bin.signed',
           'panda/board/obj/panda_h7/main.elf', 'panda/board/obj/body_h7/main.elf')
for name in (*outputs, 'panda/board/obj/version', 'panda/compile_commands.json'):
    target = dest / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(root / name, target)
record = dict(source_commit=manifest['source_commit'], source_sha256=manifest['source_sha256'],
              version=(root / 'panda/board/obj/version').read_text(),
              sha256={name: hashlib.sha256((dest / name).read_bytes()).hexdigest() for name in outputs})
(dest / 'rc-firmware-artifacts.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
PY
  python3 ../panda/build_identity.py verify --root .. > "/evidence/source-after${run}.txt"
done
```

5. Transfer preserved build1/build2 evidence back to private staging on M4P48,
   without modifying the frozen source checkout, then run:

```bash
python3 "$SOURCE/tools/bogpilot/rc_firmware_gate.py" \
  --source "$SOURCE" --archive "$OUT/extracted-reference-archive" \
  --artifacts "$OUT/build1" --repeat "$OUT/build2" --candidate "$FINAL" \
  > "$OUT/firmware-gate-result.json"
```

Expected final native result is unrun until track10 executes these steps; synthetic
unit tests do not replace it. Gate source commit changes require a new export and
build; do not relabel earlier artifacts as the new source.
