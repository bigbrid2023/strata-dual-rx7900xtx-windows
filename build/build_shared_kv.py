import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

root = Path(r'D:\anan-work\Strata-rdna3-fixed')
build = root / 'build-hip-win'
w = Path(__file__).resolve().parent
ninja = r'C:\Users\<YOUR_USER>\AppData\Local\Programs\Python\Python312\Scripts\ninja.exe'
objects = []
for name, target in [('layer', 'CMakeFiles/strata_engine.dir/src/core/layer.cpp.obj'),
                     ('session', 'CMakeFiles/strata_engine.dir/src/core/session.cpp.obj'),
                     ('generate', 'CMakeFiles/strata.dir/src/program/generate.cpp.obj')]:
    source = w / (name + '-shared-kv.cpp')
    obj = w / (name + '-shared-kv.cpp.obj')
    cmd = subprocess.check_output([ninja, '-t', 'commands', target], cwd=build, text=True).splitlines()[-1]
    cmd = re.sub(r'\s+-M[TF]\s+\S+', '', cmd).replace(' -MD', '')
    cmd = re.sub(r'-o\s+\S+', lambda m: '-o ' + str(obj), cmd, count=1)
    cmd = re.sub(r'-c\s+\S+\s*$', lambda m: '-c ' + str(source), cmd, count=1)
    (w / (name + '-shared-kv.command.txt')).write_text(cmd)
    print('COMPILING ' + source.name, flush=True)
    logpath = w / (name + '-shared-kv.build.log')
    with logpath.open('w', encoding='utf-8') as log:
        result = subprocess.run(cmd, cwd=build, shell=True, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        print(logpath.read_text(errors='replace')[-8000:])
        raise SystemExit(result.returncode)
    objects.append(obj)
engine = w / 'engine-shared-kv'
engine.mkdir(exist_ok=True)
cmd = subprocess.check_output([ninja, '-t', 'commands', 'strata.exe'], cwd=build, text=True).splitlines()[-1]
cmd = cmd.replace('CMakeFiles/strata.dir/src/program/generate.cpp.obj', '')
objects += [w / 'tp-upload.cpp.obj', w / 'verify-service.cpp.obj', w / 'prefill-main-keep.cpp.obj']
cmd = cmd.replace(' -o strata.exe', ' ' + ' '.join(map(str, objects)) + ' -o ' + str(engine / 'strata.exe'))
cmd = cmd.replace('/implib:strata.lib', '/implib:' + str(engine / 'strata.lib')).replace('/pdb:strata.pdb', '/pdb:' + str(engine / 'strata.pdb'))
(w / 'shared-kv-link.command.txt').write_text(cmd)
print('LINKING', flush=True)
logpath = w / 'shared-kv-link.build.log'
with logpath.open('w', encoding='utf-8') as log:
    result = subprocess.run(cmd, cwd=build, shell=True, stdout=log, stderr=subprocess.STDOUT)
if result.returncode:
    print(logpath.read_text(errors='replace')[-8000:])
    raise SystemExit(result.returncode)
for name in ['amdhip64_7.dll', 'amd_comgr.dll']:
    shutil.copy2(w / 'engine-service' / name, engine / name)
manifest = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in [engine / 'strata.exe'] + objects}
(w / 'shared-kv-build-manifest.json').write_text(json.dumps(manifest, indent=2))
print('SHARED_KV_BUILD_PASS', flush=True)
