# Local firmware source identity

No safety behavior, signing keys or build policy changes: default remains DEBUG,
including ALLOW_DEBUG and the existing debug signer. Never flash as part of this workflow.

From a real checkout run `python3 panda/build_identity.py export`. Include the
resulting root `.panda-source.json` alongside `git archive HEAD` contents (the
manifest is intentionally not committed). Dirty builds must copy actual working
source files too; otherwise verification rejects the archive. Do not manufacture
`.git` directories. After edits, regenerate the manifest before building.

`python3 panda/build_identity.py verify` validates source content. SCons invokes
this same verification before generating gitversion.h and version. Archives
without a manifest, missing inputs, and changed/extra input files fail closed.
The manifest is an unsigned local provenance assertion, not cryptographic proof
that a named commit exists or certification of firmware safety. Keep it with the
build logs, compiler version, output SHA256 inventory and exact build command.

Version format: `DEV-<full source commit>-<c|d>-<8 hex content hash>-DEBUG`.
The full SHA256, source version header and input inventory live in the manifest;
the short content fingerprint in the USB string is not collision-proof. Dirty
means tracked or untracked checkout changes, excluding generated board/obj and
the manifest itself. It is relative to SOURCE commit, never the later commit that
might hold native outputs. No timestamps or host identities enter the version.

The content inventory covers panda (excluding obj/cache/native .o/.so outputs),
opendbc safety headers, root SConstruct and common/version.h. Test files are not
firmware inputs and are left out: every directory named `tests` (panda/tests,
opendbc/safety/tests, ...), and `test_*.py` and `conftest.py` files, so a test
only edit never changes the identity. This identifies firmware source inputs, not
the entire product tree or external compiler. Output ELFs and signatures still
require actual AGNOS19.9 repeated-build comparison; unit tests only establish
deterministic identity generation.

Build only in the serialized AGNOS19.9 VM, without RELEASE set, using existing
SCons targets. Retain rebuilt outputs in a separate local staging directory.
Compare embedded version, expected manifest and repeat-build SHA256s before any
artifact commit. Do not copy generated artifacts into a product branch implicitly.

## Release rule

Any change to a firmware source input (panda board code, opendbc safety modes or
headers, panda SConscript or SConstruct, common/version.h) rebuilds the prebuilt
panda firmware and libpanda in the same release. The prebuilt is built from the
commit that holds the final panda source (the source commit) and is committed in
the next commit, which holds only the build outputs; its version string names the
source commit and carries the identity of that source. Never ship a prebuilt whose
identity differs from the tree.

Checks that hold this rule:
- `tools/bogpilot/panda_prebuilt_guard.py`, run by the BogPilot pre-push hook on every
  pushed tip, refuses a push when the panda source identity differs from the prebuilt
  version string, or when the version's source commit is not an ancestor with that identity.
- `tools/bogpilot/err4_panda_pairing.py` (package time) computes the identity from the
  tree and requires the prebuilt version string to match.
- `tools/bogpilot/rc_firmware_gate.py` checks two clean native builds of the source commit.

Test: `python3 -m unittest discover -s panda/tests -p test_build_identity.py`.
