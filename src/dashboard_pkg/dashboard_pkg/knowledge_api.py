#!/usr/bin/env python3
"""
DORI Dashboard — Knowledge Manager API Server
Provides REST endpoints for the KnowledgeTab frontend.

Endpoints:
  POST /api/knowledge/parse-menu            Receive menu files, run parser
  POST /api/knowledge/build-index           Start index build job
  GET  /api/knowledge/build-index/status/{job_id}  Poll job progress
  GET  /api/knowledge/index-info            Current FAISS index stats
  GET  /api/knowledge/documents             List indexed .txt files
  GET  /api/knowledge/buildings             Read campus_knowledge.json
  PUT  /api/knowledge/buildings/{key}       Update one building entry

Usage:
  pip install fastapi uvicorn python-multipart
  python3 knowledge_api.py [--port 3000] [--repo-root /path/to/dori] [--web-dir /path/to/web]
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

# ── Path resolution ────────────────────────────────────────────────────────────

def find_repo_root(start: Path) -> Path:
    """Walk up from start until we find the repo root (contains README.md + src/)."""
    for parent in [start, *start.parents]:
        if (parent / 'src').is_dir() and (parent / 'README.md').exists():
            return parent
    return start  # fallback


DEFAULT_REPO = find_repo_root(Path(__file__).resolve().parent)

parser_arg = argparse.ArgumentParser(add_help=False)
parser_arg.add_argument('--repo-root', default=str(DEFAULT_REPO))
parser_arg.add_argument('--port', type=int, default=3000)
parser_arg.add_argument('--web-dir', default='')
args, _ = parser_arg.parse_known_args()

REPO_ROOT   = Path(args.repo_root)
PARSER_SCRIPT  = REPO_ROOT / 'tools' / 'parser' / 'parse_cafeteria_menu.py'
BUILDER_SCRIPT = REPO_ROOT / 'src' / 'llm_pkg' / 'llm_pkg' / 'build_index.py'
PROCESSED_DIR  = REPO_ROOT / 'data' / 'campus' / 'processed'
INDEXED_DIR    = REPO_ROOT / 'data' / 'campus' / 'indexed'
KNOWLEDGE_FILE = INDEXED_DIR / 'campus_knowledge.json'

# ── Job registry ───────────────────────────────────────────────────────────────

_jobs: dict[str, dict] = {}
# job schema: { status: idle|running|done|error, lines: [str], total_chunks: int, error: str }


# ── App ────────────────────────────────────────────────────────────────────────

app = FastAPI(title='DORI Knowledge API', version='1.0.0')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*'],
)


def _resolve_web_dir() -> Path | None:
    if args.web_dir:
        candidate = Path(args.web_dir).expanduser().resolve()
        if candidate.is_dir():
            return candidate

    fallback = Path(__file__).resolve().parents[2] / 'web'
    if fallback.is_dir():
        return fallback

    return None



# ── /api/knowledge/parse-menu ─────────────────────────────────────────────────

@app.post('/api/knowledge/parse-menu')
async def parse_menu(files: list[UploadFile] = File(...)):
    """
    Receive one or more menu files (xlsx/pdf), save to a temp dir,
    run parse_cafeteria_menu.py, and return per-file results.
    """
    results = []
    out_dir = PROCESSED_DIR / 'cafeteria'
    out_dir.mkdir(parents=True, exist_ok=True)

    for upload in files:
        suffix = Path(upload.filename).suffix.lower()
        if suffix not in ('.xlsx', '.pdf'):
            results.append({'filename': upload.filename, 'ok': False,
                            'error': f'Unsupported file type: {suffix}'})
            continue

        # Save to temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await upload.read())
            tmp_path = tmp.name

        # Rename to match original filename so parser can detect cafeteria type
        named_path = Path(tmp_path).parent / upload.filename
        os.rename(tmp_path, named_path)

        try:
            result = subprocess.run(
                [sys.executable, str(PARSER_SCRIPT),
                 '--input', str(named_path),
                 '--output', str(out_dir)],
                capture_output=True, text=True, timeout=60
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or result.stdout.strip())

            # Find output files (parser prints "saved -> <path>")
            out_json = out_txt = ''
            for line in result.stdout.splitlines():
                if '[JSON] saved ->' in line:
                    out_json = line.split('->')[-1].strip()
                if '[TXT]  saved ->' in line:
                    out_txt = line.split('->')[-1].strip()

            results.append({
                'filename': upload.filename,
                'ok': True,
                'out_json': out_json,
                'out_txt': out_txt,
            })
        except Exception as e:
            results.append({'filename': upload.filename, 'ok': False, 'error': str(e)})
        finally:
            named_path.unlink(missing_ok=True)

    return {'results': results}


# ── /api/knowledge/build-index ────────────────────────────────────────────────

def _run_build_index(job_id: str, incremental: bool):
    """Run build_index.py in a background thread, capture stdout line by line."""
    job = _jobs[job_id]
    job['status'] = 'running'

    cmd = [sys.executable, str(BUILDER_SCRIPT),
           '--docs', str(PROCESSED_DIR),
           '--output', str(INDEXED_DIR)]
    if incremental:
        cmd.append('--incremental')

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, bufsize=1)
        total_chunks = 0
        for line in proc.stdout:
            line = line.rstrip()
            job['lines'].append(line)
            # Parse chunk count from build_index.py output
            if 'Total vectors' in line or 'chunks' in line.lower():
                parts = [w for w in line.split() if w.isdigit()]
                if parts:
                    total_chunks = int(parts[-1])
        proc.wait()
        if proc.returncode == 0:
            job['status'] = 'done'
            job['total_chunks'] = total_chunks
        else:
            job['status'] = 'error'
            job['error'] = f'Exit code {proc.returncode}'
    except Exception as e:
        job['status'] = 'error'
        job['error'] = str(e)


@app.post('/api/knowledge/build-index')
async def build_index(body: dict):
    incremental = body.get('incremental', True)
    job_id = str(uuid.uuid4())[:8]
    _jobs[job_id] = {'status': 'pending', 'lines': [], 'total_chunks': 0, 'error': ''}
    t = threading.Thread(target=_run_build_index, args=(job_id, incremental), daemon=True)
    t.start()
    return {'job_id': job_id}


@app.get('/api/knowledge/build-index/status/{job_id}')
async def build_index_status(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, 'Job not found')

    # Return new lines since last poll (client tracks cursor)
    # Simple approach: always return full lines (small output)
    return {
        'status': job['status'],
        'new_lines': job['lines'],
        'total_chunks': job['total_chunks'],
        'error': job['error'],
    }


# ── /api/knowledge/index-info ─────────────────────────────────────────────────

@app.get('/api/knowledge/index-info')
async def index_info():
    meta_file = INDEXED_DIR / 'metadata.json'
    index_file = INDEXED_DIR / 'index.faiss'

    if not meta_file.exists():
        return {'total_vectors': None, 'total_docs': None, 'built_at': None}

    with open(meta_file, 'r', encoding='utf-8') as f:
        meta = json.load(f)

    total_vectors = len(meta) if isinstance(meta, list) else None
    total_docs = len(set(m['source'] for m in meta)) if isinstance(meta, list) else None
    built_at = None
    if index_file.exists():
        ts = index_file.stat().st_mtime
        built_at = datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M')

    return {'total_vectors': total_vectors, 'total_docs': total_docs, 'built_at': built_at}


# ── /api/knowledge/documents ──────────────────────────────────────────────────

@app.get('/api/knowledge/documents')
async def list_documents():
    docs = []
    if not PROCESSED_DIR.exists():
        return docs

    for path in sorted(PROCESSED_DIR.rglob('*.txt')):
        stat = path.stat()
        # Count lines as rough chunk estimate
        try:
            text = path.read_text(encoding='utf-8')
            # Rough chunk count: chars / 300
            chunks = max(1, len(text) // 300)
        except Exception:
            chunks = 0

        docs.append({
            'source': str(path.relative_to(REPO_ROOT)),
            'chunks': chunks,
            'size_kb': round(stat.st_size / 1024, 1),
            'modified': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M'),
        })

    return docs


# ── /api/knowledge/buildings ──────────────────────────────────────────────────

def _load_knowledge() -> dict:
    if not KNOWLEDGE_FILE.exists():
        return {}
    with open(KNOWLEDGE_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data.get('locations', data)  # support both flat and nested formats


def _save_knowledge(locations: dict):
    if KNOWLEDGE_FILE.exists():
        with open(KNOWLEDGE_FILE, 'r', encoding='utf-8') as f:
            full = json.load(f)
    else:
        full = {}

    if 'locations' in full:
        full['locations'] = locations
    else:
        full = locations

    KNOWLEDGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(KNOWLEDGE_FILE, 'w', encoding='utf-8') as f:
        json.dump(full, f, ensure_ascii=False, indent=2)


@app.get('/api/knowledge/buildings')
async def get_buildings():
    return _load_knowledge()


@app.put('/api/knowledge/buildings/{key}')
async def update_building(key: str, body: dict):
    locations = _load_knowledge()
    if key not in locations:
        raise HTTPException(404, f'Building key not found: {key}')
    locations[key] = {**locations[key], **body}
    try:
        _save_knowledge(locations)
    except Exception as e:
        raise HTTPException(500, str(e))
    return {'ok': True, 'key': key}

# ── /api/tunnel-url ───────────────────────────────────────────────────────────
# 터널 WS URL을 반환. 프론트엔드가 외부 접속 시 폴링해서 WS URL 기본값 자동 설정.
#
# 우선순위:
#   1) 환경변수 DORI_WS_URL 이 설정되어 있으면 그 값을 사용 (고정 도메인용)
#   2) cloudflared 로그 파싱 (trycloudflare.com 임시 터널용, 후순위)

import re as _re
import os as _os

_CF_LOG_DASHBOARD = Path('/tmp/cloudflared_dashboard.log')
_CF_LOG_WS        = Path('/tmp/cloudflared_ws.log')
_CF_URL_RE        = _re.compile(r'https://[a-z0-9\-]+\.trycloudflare\.com')

# 고정 도메인 환경변수 (dashboard.launch.py 또는 systemd 에서 주입)
# 예: DORI_DASHBOARD_URL=https://dash.dgist-dori.xyz
#     DORI_WS_URL=wss://ws.dgist-dori.xyz
_FIXED_DASHBOARD_URL = _os.environ.get('DORI_DASHBOARD_URL', '').strip()
_FIXED_WS_URL        = _os.environ.get('DORI_WS_URL', '').strip()


def _parse_tunnel_url(log_path: Path) -> str | None:
    """Read a cloudflared log file and return the first trycloudflare URL found."""
    try:
        text = log_path.read_text(encoding='utf-8', errors='ignore')
        match = _CF_URL_RE.search(text)
        return match.group(0) if match else None
    except Exception:
        return None


@app.get('/api/tunnel-url')
async def get_tunnel_url():
    """
    Return Cloudflare Tunnel public URLs for the dashboard and rosbridge.

    Response:
      { "dashboard_url": str|null, "ws_url": str|null, "ready": bool }

    Priority:
      1) DORI_WS_URL / DORI_DASHBOARD_URL env vars (fixed custom domain)
      2) cloudflared log parsing (trycloudflare.com quick tunnel, fallback)

    ws_url must use wss:// — Cloudflare Tunnel always terminates TLS.
    """
    # 1순위: 고정 도메인 환경변수
    if _FIXED_WS_URL:
        return {
            'dashboard_url': _FIXED_DASHBOARD_URL or None,
            'ws_url':        _FIXED_WS_URL,
            'ready':         True,
        }

    # 2순위: trycloudflare.com 임시 터널 로그 파싱
    dashboard_url = _parse_tunnel_url(_CF_LOG_DASHBOARD)
    ws_http_url   = _parse_tunnel_url(_CF_LOG_WS)
    ws_url = ws_http_url.replace('https://', 'wss://', 1) if ws_http_url else None

    return {
        'dashboard_url': dashboard_url,
        'ws_url':        ws_url,
        'ready':         ws_url is not None,
    }

# ── Static file serving ────────────────────────────────────────────────────────
# MUST be registered after all /api/* routes.
# app.mount('/') is intentionally avoided — it shadows FastAPI routes.

WEB_DIR = _resolve_web_dir()

if WEB_DIR:
    from fastapi.responses import FileResponse as _FileResponse

    @app.get('/{full_path:path}', include_in_schema=False)
    async def serve_spa(full_path: str):
        # 실제 파일이 있으면 그대로 반환 (JS, CSS, 이미지 등)
        target = WEB_DIR / full_path
        if target.is_file():
            return _FileResponse(str(target))
        # 없으면 SPA fallback
        return _FileResponse(str(WEB_DIR / 'index.html'))

# ── /api/webhook + /api/deploy/* ──────────────────────────────────────────────
# GitHub Webhook receiver + async deploy pipeline
# Pipeline: git pull → npm run build (if web changed) → colcon build
#
# Env vars:
#   DORI_WEBHOOK_SECRET  : GitHub webhook secret (HMAC-SHA256)
#   DORI_ROS_DISTRO      : ROS distro name (default: humble)

import hashlib
import hmac
import shlex
import threading
from fastapi import Request

_WEBHOOK_SECRET = _os.environ.get('DORI_WEBHOOK_SECRET', '').encode()
_ROS_DISTRO     = _os.environ.get('DORI_ROS_DISTRO', 'humble')

# Single shared deploy job (only one deploy runs at a time)
_deploy_job: dict = {
    'status': 'idle',   # idle | running | done | error
    'steps':  [],       # list of { step, status, log }
    'error':  None,
    'started_at': None,
    'finished_at': None,
}
_deploy_lock = threading.Lock()


# ── Signature verification ────────────────────────────────────────────────────

def _verify_github_signature(body: bytes, sig_header: str | None) -> bool:
    """Verify X-Hub-Signature-256 against DORI_WEBHOOK_SECRET."""
    if not _WEBHOOK_SECRET:
        return True  # Dev mode: skip verification
    if not sig_header or not sig_header.startswith('sha256='):
        return False
    expected = 'sha256=' + hmac.new(_WEBHOOK_SECRET, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig_header)


# ── Deploy pipeline ───────────────────────────────────────────────────────────

def _run_step(step_name: str, cmd: list[str], cwd: str, env: dict | None = None) -> tuple[bool, str]:
    """Run a shell command, stream output into the deploy job log."""
    import subprocess

    step = {'step': step_name, 'status': 'running', 'log': ''}
    _deploy_job['steps'].append(step)

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env={**_os.environ, **(env or {})},
        )
        output_lines = []
        for line in proc.stdout:
            output_lines.append(line)
            step['log'] = ''.join(output_lines)   # live update

        proc.wait()
        step['log'] = ''.join(output_lines)

        if proc.returncode != 0:
            step['status'] = 'error'
            return False, step['log']

        step['status'] = 'done'
        return True, step['log']

    except Exception as e:
        step['status'] = 'error'
        step['log'] = str(e)
        return False, str(e)


def _web_dir() -> Path | None:
    """Return the web/ directory path if it exists."""
    candidate = REPO_ROOT / 'web'
    return candidate if candidate.is_dir() else None


def _changed_paths(pull_stdout: str) -> list[str]:
    """Parse 'git pull' stdout to extract list of changed file paths."""
    # git pull --ff-only output format:
    #   Updating abc1234..def5678
    #    path/to/file.py | 3 ++-
    lines = []
    for line in pull_stdout.splitlines():
        stripped = line.strip()
        if '|' in stripped:
            path = stripped.split('|')[0].strip()
            lines.append(path)
    return lines


def _deploy_pipeline():
    """Full deploy pipeline. Runs in a background thread."""
    import datetime

    _deploy_job.update({
        'status':      'running',
        'steps':       [],
        'error':       None,
        'started_at':  datetime.datetime.now().isoformat(),
        'finished_at': None,
    })

    repo = str(REPO_ROOT)
    ros_setup = f'/opt/ros/{_ROS_DISTRO}/setup.bash'

    # ── Step 1: git pull ──────────────────────────────────────────────────────
    ok, pull_log = _run_step(
        'git pull',
        ['git', 'pull', '--ff-only'],
        cwd=repo,
    )
    if not ok:
        _deploy_job.update({'status': 'error', 'error': 'git pull failed',
                            'finished_at': datetime.datetime.now().isoformat()})
        return

    changed = _changed_paths(pull_log)
    already_up_to_date = 'Already up to date' in pull_log

    if already_up_to_date:
        _deploy_job.update({'status': 'done',
                            'finished_at': datetime.datetime.now().isoformat()})
        return

    # ── Step 2: npm build (only if web/ files changed) ───────────────────────
    web_changed = any(p.startswith('web/') for p in changed)
    web = _web_dir()

    if web_changed and web:
        ok, _ = _run_step('npm ci', ['npm', 'ci'], cwd=str(web))
        if not ok:
            _deploy_job.update({'status': 'error', 'error': 'npm ci failed',
                                'finished_at': datetime.datetime.now().isoformat()})
            return

        ok, _ = _run_step('npm run build', ['npm', 'run', 'build'], cwd=str(web))
        if not ok:
            _deploy_job.update({'status': 'error', 'error': 'npm run build failed',
                                'finished_at': datetime.datetime.now().isoformat()})
            return

    # ── Step 3: colcon build ──────────────────────────────────────────────────
    ros_changed = any(p.startswith('src/') for p in changed)

    if ros_changed:
        ok, _ = _run_step(
            'colcon build',
            ['bash', '-c', f'source {ros_setup} && colcon build --symlink-install'],
            cwd=repo,
        )
        if not ok:
            _deploy_job.update({'status': 'error', 'error': 'colcon build failed',
                                'finished_at': datetime.datetime.now().isoformat()})
            return

    _deploy_job.update({'status': 'done',
                        'finished_at': datetime.datetime.now().isoformat()})


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post('/api/webhook')
async def github_webhook(request: Request):
    """Receive GitHub push webhook, trigger deploy pipeline on main branch."""
    body = await request.body()
    sig  = request.headers.get('X-Hub-Signature-256')

    if not _verify_github_signature(body, sig):
        return JSONResponse({'error': 'Invalid signature'}, status_code=403)

    event = request.headers.get('X-GitHub-Event', '')
    if event != 'push':
        return JSONResponse({'skipped': f'event={event}'})

    try:
        payload = json.loads(body)
    except Exception:
        return JSONResponse({'error': 'Invalid JSON'}, status_code=400)

    if payload.get('ref') != 'refs/heads/main':
        return JSONResponse({'skipped': f"ref={payload.get('ref')}"})

    with _deploy_lock:
        if _deploy_job['status'] == 'running':
            return JSONResponse({'skipped': 'deploy already in progress'}, status_code=409)
        thread = threading.Thread(target=_deploy_pipeline, daemon=True)
        thread.start()

    return JSONResponse({'ok': True, 'message': 'Deploy started'})


@app.get('/api/deploy/status')
async def deploy_status():
    """Poll deploy pipeline progress."""
    return JSONResponse(_deploy_job)


@app.post('/api/deploy/trigger')
async def deploy_trigger():
    """Manually trigger the deploy pipeline (no webhook needed, dev use)."""
    with _deploy_lock:
        if _deploy_job['status'] == 'running':
            return JSONResponse({'skipped': 'deploy already in progress'}, status_code=409)
        thread = threading.Thread(target=_deploy_pipeline, daemon=True)
        thread.start()
    return JSONResponse({'ok': True, 'message': 'Deploy started'})

# ── Entrypoint ─────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import uvicorn
    print(f'[DORI Knowledge API] Repo root : {REPO_ROOT}')
    print(f'[DORI Knowledge API] Parser    : {PARSER_SCRIPT}')
    print(f'[DORI Knowledge API] Builder   : {BUILDER_SCRIPT}')
    print(f'[DORI Knowledge API] Listening : http://0.0.0.0:{args.port}')
    uvicorn.run(app, host='0.0.0.0', port=args.port, log_level='warning')
