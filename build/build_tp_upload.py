import re, subprocess, shutil
from pathlib import Path
root=Path(r'D:\anan-work\Strata-rdna3-fixed'); build=root/'build-hip-win';w=Path(__file__).resolve().parent
ninja=r'C:\Users\<YOUR_USER>\AppData\Local\Programs\Python\Python312\Scripts\ninja.exe'
target='CMakeFiles/strata_engine.dir/src/core/tp.cpp.obj'
cmd=subprocess.check_output([ninja,'-t','commands',target],cwd=build,text=True).splitlines()[-1]
cmd=re.sub(r'\s+-M[TF]\s+\S+','',cmd).replace(' -MD','')
cmd=re.sub(r'-o\s+\S+',lambda m:'-o '+str(w/'tp-upload.cpp.obj'),cmd,count=1)
cmd=re.sub(r'-c\s+\S+\s*$',lambda m:'-c '+str(w/'tp-upload.cpp'),cmd,count=1)
with open(w/'tp-upload.build.log','w',encoding='utf-8') as log:
    result=subprocess.run(cmd,cwd=build,shell=True,stdout=log,stderr=subprocess.STDOUT)
if result.returncode:
    print((w/'tp-upload.build.log').read_text(errors='replace')[-8000:]);raise SystemExit(result.returncode)
print('TP_UPLOAD_COMPILED',flush=True)
cmd=subprocess.check_output([ninja,'-t','commands','strata.exe'],cwd=build,text=True).splitlines()[-1]
engine=w/'engine-upload'; engine.mkdir(exist_ok=True)
cmd=cmd.replace(' -o strata.exe',' '+str(w/'tp-upload.cpp.obj')+' -o '+str(engine/'strata.exe'))
cmd=cmd.replace('/implib:strata.lib','/implib:'+str(engine/'strata.lib')).replace('/pdb:strata.pdb','/pdb:'+str(engine/'strata.pdb'))
(w/'tp-upload-link.command.txt').write_text(cmd)
with open(w/'tp-upload-link.build.log','w',encoding='utf-8') as log:
    result=subprocess.run(cmd,cwd=build,shell=True,stdout=log,stderr=subprocess.STDOUT)
if result.returncode:
    print((w/'tp-upload-link.build.log').read_text(errors='replace')[-8000:]);raise SystemExit(result.returncode)
for name in ['amdhip64_7.dll','amd_comgr.dll']:
    if (root/'engine-fixed'/name).exists():shutil.copy2(root/'engine-fixed'/name,engine/name)
print('TP_UPLOAD_BUILD_PASS',flush=True)
