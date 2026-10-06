# BogPilot Tesla early (Phase 1)

Phase: **1** (base tree, docs, user-visible identity, failing early-platform smoke test). No Tesla actuation is in this phase. This is not a tagged release.

## Pinned SHAs

| Role | Repo | Branch | SHA |
| --- | --- | --- | --- |
| Architecture base | https://github.com/FrogAi/FrogPilot | `FrogPilot` | `1e23dec6352cef5a36a87be0af7d7a082b7c48a4` |
| Tesla behavior donor | https://github.com/bbqgloves/earlytesla-openpilot | `tesla_unity_dev` | `501c7de91b59c70510e9dc1585acfde9b7102c93` |
| Conflict map only (do not merge) | https://github.com/bbqgloves/openpilot | `frog_ap1` | `73a16cdd50033cb9f57a03fd619e2129558eef43` |

`SOURCES.md` has the pin notes. `RENAME_MAP.md` is the path map. `PORT_PLAN.md` is the feature plan. `HOTSPOTS.md` is the Phase 0 read of the hot files. Those four files were copied from the Phase 0 inventory. Clone paths recorded in them are where the sources were read, not this product tree. Product docs live in `docs/tesla/` in this repo.

Theme docs: [`THEME.md`](THEME.md) (BogPilot theme pack, color editing, startup alert note).

Safety replay: [`panda/tests/safety_replay/README.md`](../../panda/tests/safety_replay/README.md). `replay_ap1.py` runs recorded rlogs through the AP1 panda safety before a change goes on the road.

## Disclaimer

BogPilot is not a product. No warranty. The driver remains responsible. Comply with local law. It is not safe to drive until a human has validated it on a bench and in a car.
