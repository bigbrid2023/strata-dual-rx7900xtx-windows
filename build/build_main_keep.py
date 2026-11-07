import re
import shutil
import subprocess
from pathlib import Path

root = Path(r'D:\anan-work\Strata-rdna3-fixed')
build = root / 'build-hip-win'
w = Path(__file__).resolve().parent
ninja = r'C:\Users\<YOUR_USER>\AppData\Local\Programs\Python\Python312\Scripts\ninja.exe'
cmds = subprocess.check_output([ninja, '-t', 'commands', 'strata.exe'], cwd=build, text=True).splitlines()
objects = [w / 'tp-upload.cpp.obj', w / 'verify-launch.cpp.obj']
for pattern, source, include in [
    (r'-c\s+\S*src[/\\]prefill[/\\]prefill\.cpp\s*$', 'prefill-main-keep.cpp', root / 'src' / 'prefill'),
    (r'-c\s+\S*src[/\\]program[/\\]generate\.cpp\s*$', 'generate-main-keep.cpp', root / 'src' / 'program'),
]:
    matches = [c for c in cmds if re.search(pattern, c)]
    assert len(matches) == 1, (source, len(matches))
    cmd = re.sub(r'\s+-M[TF]\s+\S+', '', matches[0]).replace(' -MD', '')
    cmd += ' -I' + str(include)
    obj = w / (source + '.obj')
    cmd = re.sub(r'-o\s+\S+', lambda m: '-o ' + str(obj), cmd, count=1)
    cmd = re.sub(r'-c\s+\S+', lambda m: '-c ' + str(w / source), cmd, count=1)
    (w / (source + '.command.txt')).write_text(cmd)
    print('COMPILING ' + source, flush=True)
    with (w / (source + '.build.log')).open('w', encoding='utf-8') as log:
        result = subprocess.run(cmd, cwd=build, shell=True, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        print((w / (source + '.build.log')).read_text(errors='replace')[-8000:])
        raise SystemExit(result.returncode)
    objects.append(obj)
engine = w / 'engine-main-keep'
engine.mkdir(exist_ok=True)
cmd = cmds[-1].replace('CMakeFiles/strata.dir/src/program/generate.cpp.obj', '')
cmd = cmd.replace(' -o strata.exe', ' ' + ' '.join(map(str, objects)) + ' -o ' + str(engine / 'strata.exe'))
cmd = cmd.replace('/implib:strata.lib', '/implib:' + str(engine / 'strata.lib')).replace('/pdb:strata.pdb', '/pdb:' + str(engine / 'strata.pdb'))
(w / 'main-keep-link.command.txt').write_text(cmd)
print('LINKING', flush=True)
with (w / 'main-keep-link.build.log').open('w', encoding='utf-8') as log:
    result = subprocess.run(cmd, cwd=build, shell=True, stdout=log, stderr=subprocess.STDOUT)
if result.returncode:
    print((w / 'main-keep-link.build.log').read_text(errors='replace')[-8000:])
    raise SystemExit(result.returncode)
for name in ['amdhip64_7.dll', 'amd_comgr.dll']:
    shutil.copy2(root / 'engine-fixed' / name, engine / name)
print('MAIN_KEEP_BUILD_PASS', flush=True)
