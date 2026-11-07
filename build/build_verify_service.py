import re
import shutil
import subprocess
from pathlib import Path

root = Path(r'D:\anan-work\Strata-rdna3-fixed')
build = root / 'build-hip-win'
w = Path(__file__).resolve().parent
ninja = r'C:\Users\<YOUR_USER>\AppData\Local\Programs\Python\Python312\Scripts\ninja.exe'
cmd = subprocess.check_output([ninja, '-t', 'commands', 'CMakeFiles/strata_engine.dir/src/core/verify.cpp.obj'], cwd=build, text=True).splitlines()[-1]
cmd = re.sub(r'\s+-M[TF]\s+\S+', '', cmd).replace(' -MD', '')
obj = w / 'verify-service.cpp.obj'
cmd = re.sub(r'-o\s+\S+', lambda m: '-o ' + str(obj), cmd, count=1)
cmd = re.sub(r'-c\s+\S+\s*$', lambda m: '-c ' + str(w / 'verify-service.cpp'), cmd, count=1)
(w / 'verify-service.command.txt').write_text(cmd)
print('COMPILING verify-service.cpp', flush=True)
with (w / 'verify-service.build.log').open('w', encoding='utf-8') as log:
    result = subprocess.run(cmd, cwd=build, shell=True, stdout=log, stderr=subprocess.STDOUT)
if result.returncode:
    print((w / 'verify-service.build.log').read_text(errors='replace')[-8000:])
    raise SystemExit(result.returncode)
engine = w / 'engine-service'
engine.mkdir(exist_ok=True)
cmd = subprocess.check_output([ninja, '-t', 'commands', 'strata.exe'], cwd=build, text=True).splitlines()[-1]
cmd = cmd.replace('CMakeFiles/strata.dir/src/program/generate.cpp.obj', '')
objects = [w / 'tp-upload.cpp.obj', obj, w / 'prefill-main-keep.cpp.obj', w / 'generate-main-keep.cpp.obj']
cmd = cmd.replace(' -o strata.exe', ' ' + ' '.join(map(str, objects)) + ' -o ' + str(engine / 'strata.exe'))
cmd = cmd.replace('/implib:strata.lib', '/implib:' + str(engine / 'strata.lib')).replace('/pdb:strata.pdb', '/pdb:' + str(engine / 'strata.pdb'))
(w / 'verify-service-link.command.txt').write_text(cmd)
print('LINKING', flush=True)
with (w / 'verify-service-link.build.log').open('w', encoding='utf-8') as log:
    result = subprocess.run(cmd, cwd=build, shell=True, stdout=log, stderr=subprocess.STDOUT)
if result.returncode:
    print((w / 'verify-service-link.build.log').read_text(errors='replace')[-8000:])
    raise SystemExit(result.returncode)
for name in ['amdhip64_7.dll', 'amd_comgr.dll']:
    shutil.copy2(root / 'engine-fixed' / name, engine / name)
print('VERIFY_SERVICE_BUILD_PASS', flush=True)
