"""Prepare independent dual-GPU vision launchers; install only after smoke checks.

These are testing launchers: the known intermittent DP wrong answer remains open.
Original desktop BATs and profiles are not modified.
"""
import argparse
import copy
import hashlib
import json
import shutil
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('--base', default='mtp-m2-dp-stage2-validate64.json')
p.add_argument('--install', action='store_true')
a = p.parse_args()
w = Path(__file__).resolve().parent
base = json.loads((w / a.base).read_text(encoding='utf-8'))
old = json.loads(Path(r'D:\strata-qwen224\profile-qwen0156df2-era-route0.json').read_text(encoding='utf-8'))
python = r'%LOCALAPPDATA%\Programs\Python\Python312\python.exe'
server = r'D:\anan-work\Strata-rdna3-fixed\serve\server.py'
era = Path(r'D:\strata-qwen224\era-route0-profile.bin')
manifest = []
for label, context in [('256K', 262144), ('1M', 1048576)]:
    stem = 'dual7900-mtp-vision-' + label.lower() + '-test'
    config = w / (stem + '.json')
    bat = w / ('Strata-Dual7900-MTP-Vision-' + label + '-Test.bat')
    if not a.install:
        cfg = copy.deepcopy(base)
        cfg.update(host='0.0.0.0', port=8080, open_browser=False,
                   log=str(w / (stem + '.engine.log')),
                   vision=copy.deepcopy(old['vision']))
        cfg['args'][cfg['args'].index('--max-context') + 1] = str(context)
        if '--vision' not in cfg['args']:
            cfg['args'].append('--vision')
        profile = w / (stem + '.bin')
        shutil.copy2(era, profile)
        for i, arg in enumerate(cfg['args']):
            if arg in ('--expert-profile', '--expert-profile-save'):
                cfg['args'][i + 1] = str(profile)
        for key in ('STRATA_TRACE', 'STRATA_TP_TIMING', 'STRATA_VERIFY_TRACE',
                    'STRATA_DECODE_TIMING', 'STRATA_PREFILL_TRACE'):
            cfg['env'].pop(key, None)
        for k in ('exe', 'cpu_exe', 'mmproj', 'model'):
            if not Path(cfg['vision'][k]).is_file():
                raise SystemExit('Missing vision file: ' + cfg['vision'][k])
        config.write_text(json.dumps(cfg, indent=2), encoding='utf-8')
        lines = [
            '@echo off', 'setlocal', 'chcp 65001 >nul', 'set "PYTHONUTF8=1"',
            'title Strata Dual RX 7900 XTX MTP Vision ' + label + ' - port 8080',
            'echo ================================================================',
            'echo   Qwen3.8 Flash Next IQ4_XS - dual RX 7900 XTX - MTP - Vision ON',
            'echo   Context: ' + label + ' (' + str(context) + ' tokens)',
            'echo   Testing build. See the desktop validation report.',
            'echo   Local: http://127.0.0.1:8080/v1',
            'echo   LAN:   http://<PC-LAN-IP>:8080/v1',
            'echo   Bind:  0.0.0.0:8080',
            'echo   Run one Strata launcher at a time. Ctrl+C to stop.',
            'echo ================================================================',
            'cd /d "' + str(w) + '"',
            '"' + python + '" -X utf8 "' + server + '" --engine strata --config "' + str(config) + '" --host 0.0.0.0 --port 8080',
            'echo.', 'echo The server stopped.', 'pause', '',
        ]
        bat.write_bytes('\r\n'.join(lines).encode('ascii'))
    else:
        review_path = w / (stem + '.smoke.review.json')
        validation_path = review_path if review_path.exists() else w / (stem + '.smoke.json')
        validation = json.loads(validation_path.read_text(encoding='utf-8'))
        cfg = json.loads(config.read_text(encoding='utf-8'))
        if not validation.get('passed'):
            raise SystemExit('Refusing to install a launcher with failed smoke checks: ' + label)
        if validation['config_sha256'] != hashlib.sha256(config.read_bytes()).hexdigest():
            raise SystemExit('Configuration changed after smoke checks: ' + label)
        engine_validation = validation
        if 'engine_sha256' not in engine_validation and validation.get('original_summary'):
            engine_validation = json.loads(Path(validation['original_summary']).read_text(encoding='utf-8'))
        if engine_validation.get('engine_sha256') != hashlib.sha256(Path(cfg['exe']).read_bytes()).hexdigest():
            raise SystemExit('Engine changed after smoke checks: ' + label)
        # Refresh only the launcher text; the tested config and old desktop BATs stay intact.
        text = bat.read_text(encoding='ascii')
        if 'echo   Dashboard:' not in text:
            text = text.replace('echo   Local:', 'echo   Dashboard: http://<PC-LAN-IP>:8080/\necho   Local:', 1)
            bat.write_bytes(text.replace('\r\n', '\n').replace('\n', '\r\n').encode('ascii'))
        shutil.copy2(bat, Path.home() / 'Desktop' / bat.name)
    actual_cfg = json.loads(config.read_text(encoding='utf-8'))
    manifest.append({'context': context, 'label': label, 'config': str(config),
                     'bat': str(bat), 'desktop_bat': str(Path.home() / 'Desktop' / bat.name),
                     'host': '0.0.0.0', 'port': 8080, 'vision': True,
                     'exe': actual_cfg['exe'],
                     'arena_pin_gib': actual_cfg['env'].get('STRATA_ARENA_PIN_GIB'),
                     'dashboard': 'http://<PC-LAN-IP>:8080/',
                     'validation': str(validation_path) if a.install else None,
                     'status': 'testing; intermittent DP wrong-answer cause unresolved',
                     'installed': a.install})
(w / 'dual-vision-launchers-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
if a.install:
    selected_path = w / 'dual-vision-selected-config.json'
    if selected_path.exists():
        selected = json.loads(selected_path.read_text(encoding='utf-8'))
        selected['requires_live_smoke'] = False
        selected['installed_after_live_smoke'] = True
        selected_path.write_text(json.dumps(selected, indent=2), encoding='utf-8')
print(json.dumps({'dual_vision_launchers': manifest}), flush=True)
