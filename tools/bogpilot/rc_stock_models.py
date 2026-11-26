"""Candidate-only explicit stock QCOM asset verification; never loads/invokes models."""
from pathlib import Path
import hashlib, json, pickletools, struct, glob, re
STOCK = 'f7db927c728bab57bb1263e05465766a8f28fc9d'
MANIFEST_SHA256 = '933974835b4d6aa7617a128e18ce8aa60aff6b73099c2f31801e687566d09b57'
BEGIN = b'\n# BEGIN VERIFIED STOCK MODELS\n'
END = b'# END VERIFIED STOCK MODELS\n'
NAMES = ('driving_tinygrad.pkl','dmonitoring_model_tinygrad.pkl','driving_warp_1344x760_tinygrad.pkl','driving_warp_1928x1208_tinygrad.pkl','dm_warp_1344x760_tinygrad.pkl','dm_warp_1928x1208_tinygrad.pkl')
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def inputs(root):
  paths={p for p in glob.glob('tinygrad_repo/**',root_dir=root,recursive=True) if 'pycache' not in p and (root/p).is_file()}
  for folder in ('openpilot/selfdrive/modeld','openpilot/common/transformations','openpilot/system/camerad/cameras'):
    paths.update(p.relative_to(root).as_posix() for p in (root/folder).rglob('*.py') if '__pycache__' not in p.parts)
  paths.update(p.relative_to(root).as_posix() for p in (root/'openpilot/selfdrive/modeld/models').glob('*.onnx'))
  return paths|{'pyproject.toml','uv.lock'}
def verify(root, arch='comma_arm64'):
  root=Path(root).resolve()
  if arch!='comma_arm64':raise ValueError('stock QCOM assets only for comma_arm64')
  raw=(root/'tools/bogpilot/c3x_stock_models_f7db927.json').read_bytes()
  if hashlib.sha256(raw).hexdigest()!=MANIFEST_SHA256:raise ValueError('stock model manifest digest mismatch')
  m=json.loads(raw)
  if m['stock_commit']!=STOCK or m['backend']!='QCOM':raise ValueError('wrong stock provenance/backend')
  if set(m['inputs'])!=inputs(root):raise ValueError('compiler/runtime input inventory drift')
  for rel,item in m['inputs'].items():
    if digest(root/rel)!=item['sha256']:raise ValueError('compiler/runtime/transform input drift: '+rel)
  builder=(root/'openpilot/selfdrive/modeld/SConscript').read_bytes()
  if builder.count(BEGIN)!=1 or builder.count(END)!=1:raise ValueError('unrecognized model builder guard')
  a=builder.index(BEGIN);b=builder.index(END,a)+len(END)
  if hashlib.sha256(builder[:a]+builder[b:]).hexdigest()!=m['default_builder_sha256']:raise ValueError('default model builder changed')
  expected={'openpilot/selfdrive/modeld/models/'+n for n in NAMES}
  if set(m['assets'])!=expected:raise ValueError('incomplete stock model set')
  for rel,item in m['assets'].items():
    p=root/rel
    if p.is_symlink() or digest(p)!=item['sha256']:raise ValueError('missing/drifted stock model: '+rel)
    data=p.read_bytes()
    if data[:1]!=b'\x80':
      if len(data)<8:raise ValueError('invalid model format')
      n=struct.unpack('<q',data[:8])[0]
      if not 0<n<=len(data)-8:raise ValueError('invalid model opcode length')
      data=data[8:8+n]
    if not any(isinstance(arg,str) and arg=='QCOM' for op,arg,pos in pickletools.genops(data)):raise ValueError('non-QCOM asset')
  candidate=None
  identity=root/'.panda-source.json'
  if not identity.exists():raise ValueError("missing source-bound candidate identity")
  if identity.exists():
    i=json.loads(identity.read_text());candidate=i['source_commit']
    if i.get('dirty') is not False or not re.fullmatch('[0-9a-f]{40}',candidate):raise ValueError('invalid candidate identity')
  return dict(status='pass',candidate_sha=candidate,stock_commit=STOCK,manifest_sha256=MANIFEST_SHA256,model_origin='PRECOMPILED-STOCK; NOT freshly generated',assets=m['assets'],input_count=len(m['inputs']))
if __name__=='__main__':
  import argparse
  ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);a=ap.parse_args()
  print(json.dumps(verify(a.root),indent=2))
