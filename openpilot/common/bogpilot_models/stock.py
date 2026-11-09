"""Pinned facts about the stock 0.11.2 models this tree ships. Generated once from the shipped files by
tools that read them with abi.py; tests re-derive every value from the real files and fail on any drift.
"""
from __future__ import annotations

MODELS_SUBDIR = "openpilot/selfdrive/modeld/models"

# sha256 of the six stock model files (must never change; see tools/bogpilot/c3x_stock_models_f7db927.json)
STOCK_HASHES = {
  "dm_warp_1344x760_tinygrad.pkl": "fbfc371f6cde5ee86eae031301ac169983bf22966fd25c3bb09ce84188ee89f0",
  "dm_warp_1928x1208_tinygrad.pkl": "b296e29eb8c1b88a930e743ba3efb1f0c4b12081ef805112fe1d91faad76e29f",
  "dmonitoring_model_tinygrad.pkl": "57c553527efbe9655fa65bb024f031db3d6511659b60cb183c0e652807c48d23",
  "driving_tinygrad.pkl": "6398a4b0e474eac003280599cef701cd01c670a42c0d74c7df72583bfc923329",
  "driving_warp_1344x760_tinygrad.pkl": "6bfe4ecc35bd7711a36741087efadb52cedfc47fcb727add30708cde3fdcde8a",
  "driving_warp_1928x1208_tinygrad.pkl": "6f7289eac4d673cc2102299dc6652ff69f70b878560936a8ccc3a10a31f72021",
}

# manifest roles -> stock file names (the "pair": driving program + the warp that feeds its new_img input)
ROLE_STOCK_FILES = {
  "driving_model": "driving_tinygrad.pkl",
  "driving_warp_1344x760": "driving_warp_1344x760_tinygrad.pkl",
  "driving_warp_1928x1208": "driving_warp_1928x1208_tinygrad.pkl",
}

STOCK_DRIVING_ABI = {'classes': ['tinygrad.device.BufferSpec', 'tinygrad.dtype.AddrSpace', 'tinygrad.dtype.DType',
             'tinygrad.engine.jit.CapturedJit', 'tinygrad.engine.jit._TinyJit', 'tinygrad.helpers.Target',
             'tinygrad.renderer.Estimates', 'tinygrad.runtime.support.hcq2.HCQInfo', 'tinygrad.uop.Ops',
             'tinygrad.uop.ops.AxisType', 'tinygrad.uop.ops.CallInfo', 'tinygrad.uop.ops.CustomFunction',
             'tinygrad.uop.ops.KernelInfo', 'tinygrad.uop.ops.ParamArg', 'tinygrad.uop.ops.ProgramInfo',
             'tinygrad.uop.ops.UOp'],
 'input_shapes': {'action_t': [1, 2],
                  'desire': [8],
                  'new_img': [2, 6, 128, 256],
                  'state_desire_q': [100, 1, 8],
                  'state_feat_q': [96, 1, 512],
                  'state_img_q': [2, 5, 6, 128, 256],
                  'traffic_convention': [1, 2]},
 'input_specs': {'action_t': [[1, 2], 'float32', 'QCOM'],
                 'desire': [[8], 'float32', 'QCOM'],
                 'new_img': [[2, 6, 128, 256], 'uint8', 'QCOM'],
                 'state_desire_q': [[100, 1, 8], 'float32', 'QCOM'],
                 'state_feat_q': [[96, 1, 512], 'float32', 'QCOM'],
                 'state_img_q': [[2, 5, 6, 128, 256], 'uint8', 'QCOM'],
                 'traffic_convention': [[1, 2], 'float32', 'QCOM']},
 'output_shapes': {'next_state_desire_q': [100, 1, 8],
                   'next_state_feat_q': [96, 1, 512],
                   'next_state_img_q': [2, 5, 6, 128, 256],
                   'outputs': [1, 2576]},
 'output_slices': {'desire_pred': [55, 87],
                   'desire_state': [2566, 2574],
                   'hidden_state': [1064, 1576],
                   'lane_lines': [117, 645],
                   'lane_lines_prob': [645, 653],
                   'lead': [917, 1061],
                   'lead_prob': [1061, 1064],
                   'meta': [0, 55],
                   'pad': [-2, None],
                   'plan': [1576, 2566],
                   'pose': [87, 99],
                   'road_edges': [653, 917],
                   'road_transform': [105, 117],
                   'wide_from_device_euler': [99, 105]},
 'output_specs': {'next_state_desire_q': [[100, 1, 8], 'float32', 'QCOM'],
                  'next_state_feat_q': [[96, 1, 512], 'float32', 'QCOM'],
                  'next_state_img_q': [[2, 5, 6, 128, 256], 'uint8', 'QCOM'],
                  'outputs': [[1, 2576], 'float32', 'QCOM']},
 'run': 'tinygrad.engine.jit._TinyJit'}

STOCK_WARP_ABI = {'driving_warp_1344x760': {'classes': ['builtins.bytearray', 'tinygrad.device.Buffer', 'tinygrad.device.BufferSpec',
                                       'tinygrad.dtype.AddrSpace', 'tinygrad.dtype.DType',
                                       'tinygrad.engine.jit.CapturedJit', 'tinygrad.engine.jit._TinyJit',
                                       'tinygrad.helpers.Target', 'tinygrad.renderer.Estimates',
                                       'tinygrad.runtime.support.hcq2.HCQInfo', 'tinygrad.tensor.Tensor',
                                       'tinygrad.uop.Ops', 'tinygrad.uop.ops.AxisType', 'tinygrad.uop.ops.CallInfo',
                                       'tinygrad.uop.ops.CustomFunction', 'tinygrad.uop.ops.KernelInfo',
                                       'tinygrad.uop.ops.ParamArg', 'tinygrad.uop.ops.ProgramInfo',
                                       'tinygrad.uop.ops.UOp'],
                           'input_specs': {'M_inv': [[2, 3, 3], '<f4', 'QCOM'],
                                           'input_frame': [[2, 1622016], '|u1', 'QCOM']},
                           'run': 'tinygrad.engine.jit._TinyJit'},
 'driving_warp_1928x1208': {'classes': ['builtins.bytearray', 'tinygrad.device.Buffer', 'tinygrad.device.BufferSpec',
                                        'tinygrad.dtype.AddrSpace', 'tinygrad.dtype.DType',
                                        'tinygrad.engine.jit.CapturedJit', 'tinygrad.engine.jit._TinyJit',
                                        'tinygrad.helpers.Target', 'tinygrad.renderer.Estimates',
                                        'tinygrad.runtime.support.hcq2.HCQInfo', 'tinygrad.tensor.Tensor',
                                        'tinygrad.uop.Ops', 'tinygrad.uop.ops.AxisType', 'tinygrad.uop.ops.CallInfo',
                                        'tinygrad.uop.ops.CustomFunction', 'tinygrad.uop.ops.KernelInfo',
                                        'tinygrad.uop.ops.ParamArg', 'tinygrad.uop.ops.ProgramInfo',
                                        'tinygrad.uop.ops.UOp'],
                            'input_specs': {'M_inv': [[2, 3, 3], '<f4', 'QCOM'],
                                            'input_frame': [[2, 3735552], '|u1', 'QCOM']},
                            'run': 'tinygrad.engine.jit._TinyJit'}}
