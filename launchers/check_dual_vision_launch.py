"""Validate actual dual-GPU vision service, context advertisement and retrieval.

The tested configuration is the one used by the independent desktop launcher.
Only the service process created by this script is terminated.
"""
import argparse
import base64
import hashlib
import importlib.util
import json
import os
import struct
import subprocess
import sys
import time
import urllib.request
import zlib
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('--label', choices=['256K', '1M'], required=True)
p.add_argument('--near-limit', action='store_true')
p.add_argument('--config', help='Independent configuration filename; its stem names all result files.')
p.add_argument('--extra-length', action='append', type=int, default=[], help='Additional exact long-input correctness check.')
a = p.parse_args()
w = Path(__file__).resolve().parent
root = Path(r'D:\anan-work\Strata-rdna3-fixed')
path = w / a.config if a.config else w / ('dual7900-mtp-vision-' + a.label.lower() + '-test.json')
stem = path.stem
cfg = json.loads(path.read_text(encoding='utf-8'))
os.environ['PYTHONUTF8'] = '1'
if not sys.flags.utf8_mode:
    raise SystemExit('Use python -X utf8.')
sys.path.insert(0, str(root / 'rdna3'))
spec = importlib.util.spec_from_file_location('B', root / 'rdna3' / 'bench.py')
B = importlib.util.module_from_spec(spec)
spec.loader.exec_module(B)

def image_png():
    width, height = 768, 256
    rows = []
    for y in range(height):
        row = bytearray()
        for x in range(width):
            color = (255, 255, 255)
            if 58 <= x < 198 and 58 <= y < 198:
                color = (230, 20, 20)
            if (x - 384) ** 2 + (y - 128) ** 2 <= 72 ** 2:
                color = (15, 60, 230)
            if 46 <= y <= 210 and abs(x - 640) <= (y - 46) * 0.53:
                color = (245, 205, 0)
            row.extend(color)
        rows.append(b'\x00' + row)
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(b''.join(rows))) + chunk(b'IEND', b''))

meta = {'label': a.label, 'config': str(path),
        'config_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'engine_sha256': hashlib.sha256(Path(cfg['exe']).read_bytes()).hexdigest(),
        'rows': [], 'passed': False, 'near_limit_requested': a.near_limit}
out = (w / (stem + '.smoke.server.log')).open('wb')
err = (w / (stem + '.smoke.server.err')).open('wb')
proc = subprocess.Popen([sys.executable, '-X', 'utf8', str(root / 'serve' / 'server.py'),
                         '--engine', 'strata', '--config', str(path),
                         '--host', '0.0.0.0', '--port', '8080'], stdout=out, stderr=err, cwd=w)
print(json.dumps({'vision_launch_started': a.label, 'service_pid': proc.pid}), flush=True)
start = time.monotonic()
def save(name, result, passed):
    result['passed'] = bool(passed)
    (w / (stem + '-' + name + '.result.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    meta['rows'].append({'name': name, 'passed': bool(passed), 'timings': result.get('timings', {})})
    print(json.dumps({'vision_launch_case': name, 'passed': bool(passed),
                      'timings': result.get('timings', {}), 'preview': result.get('content', '')[:220]}), flush=True)
    if not passed:
        raise RuntimeError('Correctness failed: ' + name)

def retrieval(n, name):
    text_path = w / 'bench-prompts' / ('n' + str(n) + '-r0.txt')
    if not text_path.exists():
        print(json.dumps({'generating_exact_prompt': n}), flush=True)
        enc = B.encoder(cfg)
        text = B.exact_prompt(enc, cfg['model_name'], n, 0)
        text_path.write_text(text, encoding='utf-8', newline='')
    else:
        text = text_path.read_text(encoding='utf-8')
    print(json.dumps({'retrieval_start': name, 'target_tokens': n}), flush=True)
    r = B.request(8080, B.payload(cfg['model_name'], text, 256))
    t, u = r['timings'], r['usage']
    passed = u.get('prompt_tokens') == n and t.get('prompt_n') == n and not t.get('cache_n')
    # Strata service and engine both reserve CTX_SLACK=8. Its default fit_max_tokens
    # shortens the completion at the exact context boundary, which is not a wrong answer.
    expected_output = min(256, int(cfg['args'][cfg['args'].index('--max-context') + 1]) - n - 8)
    passed = passed and u.get('completion_tokens') == expected_output and all(c in r['content'] for c in B.CODES)
    r['target_prompt_tokens'] = n
    r['expected_completion_tokens'] = expected_output
    save(name, r, passed)

try:
    while True:
        if proc.poll() is not None:
            raise RuntimeError('Service exited: ' + str(proc.returncode))
        try:
            with urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2) as response:
                health = json.load(response)
            break
        except OSError:
            if time.monotonic() - start > 600:
                raise TimeoutError('Model and vision startup timed out.')
            time.sleep(2)
    expected = 262144 if a.label == '256K' else 1048576
    meta['health'] = health
    meta['ready_s'] = time.monotonic() - start
    if health.get('max_context') != expected or not health.get('images') or not health.get('loaded'):
        raise RuntimeError('Unexpected health capabilities: ' + repr(health))
    with urllib.request.urlopen('http://127.0.0.1:8080/v1/models', timeout=5) as response:
        meta['models'] = json.load(response)
    print(json.dumps({'vision_launch_ready': a.label, 'health': health}), flush=True)
    retrieval(65536, 'cold64')
    data = image_png()
    (w / 'vision-smoke-shapes.png').write_bytes(data)
    body = B.payload(cfg['model_name'], '', 192)
    body['messages'] = [{'role': 'user', 'content': [
        {'type': 'text', 'text': 'List the three large colored shapes from left to right. Name each shape and its color. Do not describe the white background.'},
        {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + base64.b64encode(data).decode()}}]}]
    r = B.request(8080, body)
    s = r['content'].lower()
    save('vision-shapes', r, all(k in s for k in ['red', 'square', 'blue', 'circle', 'yellow', 'triangle']) and '\ufffd' not in s)
    body = B.payload(cfg['model_name'], '用一句话回答：中国的首都是哪里？', 64)
    r = B.request(8080, body)
    save('zh-after-vision', r, '北京' in r['content'] and '\ufffd' not in r['content'])
    retrieval(65536, 'after-vision64')
    for length in a.extra_length:
        retrieval(length, 'extra' + str(length))
    if a.near_limit:
        retrieval(expected - 256, 'near-context-limit')
    meta['passed'] = all(r['passed'] for r in meta['rows'])
except Exception as e:
    meta['error'] = repr(e)
    print(json.dumps({'vision_launch_error': a.label, 'error': repr(e)}), flush=True)
finally:
    if proc.poll() is None:
        subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    proc.wait(timeout=30)
    out.close()
    err.close()
    meta['elapsed_s'] = time.monotonic() - start
    (w / (stem + '.smoke.json')).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'vision_launch_finished': a.label, 'passed': meta['passed'], 'stopped_pid': proc.pid}), flush=True)
if not meta['passed']:
    raise SystemExit(1)
