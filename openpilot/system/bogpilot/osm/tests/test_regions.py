import json

from openpilot.system.bogpilot.osm import regions as R


def test_catalog_sizes_and_known_regions():
  cat = R.catalog()
  assert len(cat["nation"]) == 173
  assert len(cat["state"]) == 56
  wy = cat["state"]["WY"]
  assert wy.name == "Wyoming" and wy.kind == "state"
  assert cat["nation"]["US"].name


def test_groups_only_list_downloadable_codes_and_cover_all_states():
  g = R.groups()
  cat = R.catalog()
  for key, kind in (("nations", "nation"), ("states", "state")):
    for _label, regs in g[key]:
      for code, _name in regs:
        assert code in cat[kind]
  assert {c for _, regs in g["states"] for c, _ in regs} == set(cat["state"])
  # PR is a mapd "nation" that the 0.9.7 panel only offered as a US territory
  assert R.ungrouped_codes() == {"nations": ["PR"], "states": []}
  # 0.9.7 listed 7 nations (BH GD HK KM MO MV SG) that mapd has no bounding box for: they must not be offered
  offered = {c for _, regs in g["nations"] for c, _ in regs}
  assert not ({"BH", "GD", "HK", "KM", "MO", "MV", "SG"} & offered)
  assert "GM" in {c for _, regs in g["states"] for c, _ in regs} and "GU" not in {c for _, regs in g["states"] for c, _ in regs}


def test_group_labels_match_097_panel():
  assert [l for l, _ in R.groups()["states"]] == [
    "United States - Midwest", "United States - Northeast", "United States - South", "United States - West",
    "United States - Territories"]
  assert [l for l, _ in R.groups()["nations"]][0] == "Africa"


def test_parse_selection_roundtrip_097_format():
  sel = R.parse_selection('{"nations":["US","CA"],"states":["WY","MT"]}')
  assert sel.nations == ("US", "CA") and sel.states == ("WY", "MT")
  assert sel.to_param() == '{"nations":["US","CA"],"states":["WY","MT"]}'
  assert R.parse_selection(sel.to_param()) == sel


def test_parse_selection_fails_closed():
  for bad in (None, "", b"\xff\xfe", "not json", "[]", "5", '{"nations":"US"}', '{"nations":[1,null,{}]}', '{"states":{"WY":1}}'):
    assert R.parse_selection(bad).is_empty()
  s = R.parse_selection('{"nations":["ZZ","US","US"],"states":["XX","WY"]}')
  assert s.nations == ("US",) and s.states == ("WY",)       # unknown dropped, duplicates collapsed


def test_saved_097_guam_code_is_migrated_not_dropped():
  assert R.parse_selection('{"states":["GU","WY"]}').states == ("GM", "WY")
  assert R.parse_selection('{"states":["GU","GM"]}').states == ("GM",)
  assert R.parse_selection('{"nations":["GU"]}').is_empty()          # alias is state-only


def test_selection_cap():
  codes = list(R.catalog()["nation"])[:150] * 2
  s = R.parse_selection(json.dumps({"nations": codes}))
  assert len(s.nations) <= R.MAX_SELECTED_REGIONS


def test_adjusted_bounds_matches_mapd_port():
  wy = R.catalog()["state"]["WY"]
  # catalog box snapped outward to the 2-degree grid, as mapd adjustedBounds does
  assert R.adjusted_bounds(wy) == (40, -112, 46, -104)
  assert R.files_for_region(wy) == ((46 - 40) // 2) * ((-104 + 112) // 2) == 12
  assert sorted(R.cells_for_region(wy)) == sorted((i, j) for i in (40, 42, 44) for j in (-112, -110, -108, -106))


def test_exact_grid_edge_is_not_extended():
  r = R.Region("T", "t", "state", 2.0, -4.0, 4.0, -2.0)
  assert R.adjusted_bounds(r) == (2, -4, 4, -2)
  assert R.files_for_region(r) == 1


def test_estimate_unique_vs_total():
  sel = R.parse_selection('{"states":["WY","MT","ID"]}')
  e = R.estimate(sel)
  assert e.total_files >= e.unique_cells > 0
  assert e.est_bytes == e.unique_cells * R.ESTIMATED_CELL_BYTES
  assert e.worst_bytes == e.total_files * R.ESTIMATED_CELL_BYTES
  assert R.estimate(R.Selection()).total_files == 0


def test_cell_for_point():
  assert R.cell_for_point(2.5, -3.2) == (2, -4)
  assert R.cell_for_point(-0.5, 0.5) == (-2, 0)
