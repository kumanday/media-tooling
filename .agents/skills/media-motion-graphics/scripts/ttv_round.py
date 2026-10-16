#!/usr/bin/env python3
"""One TTV file-handoff round for an already-sent media-generated request.

Two steps, so the plan is reviewed before anything is spent:

  plan     TTV plans the request (no provider spend); the plan is imported and
           its prompts, models, variants and costs are printed for review.
  execute  records an approval for every planned variant (or the --variant list),
           sends it, has TTV run the job, and imports the result.

Run from anywhere; paths are explicit. Credentials come from the environment:
FAL_KEY or FAL_API_KEY for fal.ai, and the image provider's key (see
--image-provider). The TTV runtime config is written to a pipe, never to disk,
so keys never land in project files. If your keys live in a login shell, run
this under it (for example `zsh -lic 'python3 ttv_round.py ...'`).

Example (H3 Max Turbo drafts, then H3 Max finals):

    ttv_round.py plan    --project P --ttv-checkout T --request request-3
    ttv_round.py execute --project P --ttv-checkout T --request request-3 \
        --approval approval-3 --budget 10 --model minimax/h3-max-turbo/image-to-video --resolution 768P
    ttv_round.py execute ... --model minimax/h3-max/image-to-video --resolution 1080P

`--mode keyframes` runs a keyframe-only approval for visual review of first
frames before video generation (see docs/generated-media.md).
"""
import argparse
import json
import os
import subprocess
import sys
import threading


def config_yaml(a):
    lines = ['default_backend: fal', 'integration_publish_gcs: false', 'integration_asset_roots:', f'  - {a.project}',
             *[f'  - {r}' for r in a.asset_root], 'integration_generate_last_frame: false']
    if a.image_provider == 'gateway':
        lines += [f'image_generation_model: {a.image_model}', 'image_generation_gateway:', f'  api_key_env: {a.image_key_env}',
                  f'  size: {a.image_size}', f'  quality: {a.image_quality}']
        if a.image_base_url:
            lines.append(f'  base_url: {a.image_base_url}')
    else:
        key = os.environ.get(a.image_key_env or 'GEMINI_API_KEY', '')
        if not key and not a.print_config:
            sys.exit(f'{a.image_key_env or "GEMINI_API_KEY"} is not set')
        shown = '<redacted>' if a.print_config else key
        lines += [f'image_generation_model: {a.image_model or "gemini-3-pro-image"}', f'image_size: {a.gemini_size}', f'gemini_api_key: "{shown}"']
    lines += ['fal:', f'  model: {a.model}', '  default_input:', f'    resolution: {a.resolution}',
              '    prompt_expansion_mode: disabled', '    enable_safety_checker: true',
              'remote_api_settings:', '  max_retries: 1', '  polling_interval: 2', '  timeout: 600']
    return '\n'.join(lines) + '\n'


def ttv(a, *args, out):
    """Run TTV's file adapter with the config on an inherited pipe; stdout goes to `out`."""
    r, w = os.pipe()
    data = config_yaml(a).encode()
    threading.Thread(target=lambda: (os.write(w, data), os.close(w)), daemon=True).start()
    err = out + '.err'
    cmd = ['uv', 'run', '--locked', 'python', '-m', 'api.generation_handoff', '--root', a.ttv_root, '--config', f'/dev/fd/{r}', *args]
    with open(out, 'w') as so, open(err, 'w') as se:
        p = subprocess.run(cmd, cwd=a.ttv_checkout, stdout=so, stderr=se, pass_fds=(r,))
    os.close(r)
    if p.returncode:
        sys.exit(f'TTV {args[0]} failed ({p.returncode}); see {err}')


def mg(a, *args):
    p = subprocess.run(['media-generated', '--project', a.project, *args], capture_output=True, text=True)
    if p.returncode:
        sys.exit(f'media-generated {args[0]} failed: {p.stderr.strip() or p.stdout.strip()}')
    return p.stdout


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('step', choices=['plan', 'execute'])
    ap.add_argument('--project', required=True, help='media-tooling project root')
    ap.add_argument('--ttv-checkout', required=True, help='TTV Pipeline checkout (uv project)')
    ap.add_argument('--request', required=True, help='request ID already sent with `media-generated send request --handoff`')
    ap.add_argument('--handoff', help='exchange directory (default PROJECT/generation/handoff)')
    ap.add_argument('--ttv-root', help='TTV integration store (default PROJECT/generation/ttv-root)')
    ap.add_argument('--asset-root', action='append', default=[], help='extra directory TTV may read reference assets from')
    ap.add_argument('--model', default='minimax/h3-max-turbo/image-to-video', help='fal image-to-video model')
    ap.add_argument('--resolution', default='768P', help='fal resolution (runtime config, not the plan): 768P drafts, 1080P finals')
    ap.add_argument('--image-provider', choices=['gemini', 'gateway'], default='gateway')
    ap.add_argument('--image-model', default='gpt-image-2.5-sunburst', help='keyframe image model')
    ap.add_argument('--image-key-env', default=None, help='env var holding the image key (gateway default OPENAI_API_KEY, gemini default GEMINI_API_KEY)')
    ap.add_argument('--image-base-url', default=None, help='OpenAI-compatible gateway base URL (omit for api.openai.com)')
    ap.add_argument('--image-size', default='2560x1440', help='gateway image size; both sides divisible by 16')
    ap.add_argument('--image-quality', default='high')
    ap.add_argument('--gemini-size', default='2K')
    ap.add_argument('--approval', help='approval ID to create (execute)')
    ap.add_argument('--budget', help='approval budget in USD (execute)')
    ap.add_argument('--mode', choices=['video', 'keyframes'], default='video')
    ap.add_argument('--variant', action='append', default=[], help='approve only these variant IDs (default: every planned variant)')
    ap.add_argument('--print-config', action='store_true', help='print the runtime config with keys redacted and exit')
    a = ap.parse_args()
    a.project = os.path.abspath(a.project)
    a.handoff = os.path.abspath(a.handoff or os.path.join(a.project, 'generation/handoff'))
    a.ttv_root = os.path.abspath(a.ttv_root or os.path.join(a.project, 'generation/ttv-root'))
    if a.image_key_env is None:
        a.image_key_env = 'OPENAI_API_KEY' if a.image_provider == 'gateway' else 'GEMINI_API_KEY'
    if a.image_provider == 'gemini' and a.image_model == 'gpt-image-2.5-sunburst':
        a.image_model = 'gemini-3-pro-image'
    if a.print_config:
        print(config_yaml(a), end='')
        return
    if not (os.environ.get('FAL_KEY') or os.environ.get('FAL_API_KEY')):
        sys.exit('FAL_KEY or FAL_API_KEY is not set')
    H = a.handoff
    for d in ('plans', 'jobs', 'results'):
        os.makedirs(os.path.join(H, d), exist_ok=True)
    plan_path = os.path.join(H, 'plans', f'plan-{a.request}.json')

    if a.step == 'plan':
        ttv(a, 'plan', os.path.join(H, 'requests', f'{a.request}.json'), out=plan_path)
        mg(a, 'import', 'plan', plan_path)
        plan = json.load(open(plan_path))
        print(f"plan {plan['plan_id']} for {a.request}: review before execute")
        for s in plan['scenes']:
            for v in s['variants']:
                cost = v.get('estimated_cost') or {}
                print(f"  {s['scene_id']}  variant {v['variant_id']}  model {v.get('model')}  est {cost.get('amount')} {cost.get('currency', '')}")
                for sh in v.get('shots', []):
                    print(f"    {sh.get('nominal_duration_s')} s: {sh.get('prompt_snapshot', '')[:300]}")
        return

    if not (a.approval and a.budget):
        sys.exit('execute needs --approval and --budget')
    if not os.path.exists(plan_path):
        sys.exit(f'{plan_path} not found: run the plan step first')
    plan = json.load(open(plan_path))
    variants = a.variant or [v['variant_id'] for s in plan['scenes'] for v in s['variants']]
    mg(a, 'approve', plan_path, '--mode', a.mode, *sum((['--variant', v] for v in variants), []), '--id', a.approval, '--key', a.approval,
       '--allow-unknown-cost', '--budget-usd', str(a.budget))
    mg(a, 'send', 'approval', os.path.join(a.project, 'rough-cuts/manifests/approvals', f'{a.approval}.json'), '--handoff', H)
    job_path = os.path.join(H, 'jobs', f'job-{a.approval}.json')
    ttv(a, 'approve', os.path.join(H, 'approvals', f'{a.approval}.json'), out=job_path)
    job = json.load(open(job_path))['id']
    res_path = os.path.join(H, 'results', f'result-{a.approval}.json')
    ttv(a, 'run', job, out=res_path)
    mg(a, 'import', 'result', res_path, '--asset-root', a.ttv_root)
    result = json.load(open(res_path))
    print(json.dumps({'request': a.request, 'plan': plan['plan_id'], 'approval': a.approval, 'job': job, 'result': result['result_id'],
                      'status': result['terminal_status'],
                      'takes': {s['scene_id']: [t['take_id'] for t in s['takes']] for s in result['scenes']},
                      'warnings': {s['scene_id']: s['warnings'] for s in result['scenes'] if s['warnings']}}, indent=1))


if __name__ == '__main__':
    main()
