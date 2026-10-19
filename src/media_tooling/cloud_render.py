"""Render a HyperFrames project on Google Cloud Run, billed to the GCP project its render profile names.

``hyperframes cloudrun`` renders a composition in parallel chunks on Cloud Run + Workflows. This command adds what
running several GCP projects from one machine needs:

- **Profiles.** The private ``profiles.toml`` in your local media-tooling folder (``~/.config/media-tooling/``, see
  ``media_tooling.local_config``) names, per profile, the gcloud configuration (account), GCP project and region::

      [profiles.work]
      gcloud_configuration = "work-cfg"
      account = "me@work.example"
      project = "work-gcp-project"
      region = "us-central1"

  The same rules that pick a project's private rules pick its render profile (``--profile``, a pin in
  ``media-tooling.toml``, path rules, ``default_profile``).
- **Isolation.** Every gcloud, Terraform and SDK call runs with the profile's gcloud configuration
  (``CLOUDSDK_ACTIVE_CONFIG_NAME``) and the profile's Application Default Credentials file, so the global active
  account is never switched. Each profile keeps its own stack coordinates (``cloudrun/<profile>/stack.json``) and its
  own Terraform state in a versioned bucket inside its own GCP project. Upstream ``hyperframes cloudrun deploy``
  keeps one global state file and runs Terraform inside the npm package directory, so a second project would plan
  to replace the first one's stack; this command never uses it.
- **Clean uploads.** The Cloud Run SDK tars the whole project folder (no ignore file). Renders are staged first,
  without generated outputs (``renders/``, ``qa/``, capture frame dumps and the patterns in ``.hyperframesignore``)
  and without audio/video files no composition references (HyperFrames only plays media declared with a ``src``),
  and every local asset the compositions reference is checked to be present in the stage.
- **Explicit spending.** ``deploy`` and ``destroy`` create or remove billable resources and ask first (``--yes`` to
  skip); ``render`` prints the account, project, upload size and chunk plan before it starts, and ``--dry-run``
  stops there.

Subcommands: ``which``, ``setup``, ``deploy``, ``render``, ``status``, ``destroy``.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from media_tooling.local_config import (
    LocalConfigError,
    Resolved,
    cache_dir,
    config_dir,
    load_config,
    resolve_profile,
)

DEFAULT_REGION = "us-central1"
DEFAULT_HYPERFRAMES_VERSION = "0.8.163"
HYPERFRAMES_REPO = "https://github.com/heygen-com/hyperframes"
ARTIFACT_REPO = "hyperframes"
GCP_APIS = (
    "run.googleapis.com",
    "workflows.googleapis.com",
    "workflowexecutions.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "monitoring.googleapis.com",
    "storage.googleapis.com",
)
# root-relative, gitignore-like: a trailing "/" matches a directory, "**" any depth
DEFAULT_EXCLUDES = (
    ".git/",
    "node_modules/",
    ".hyperframes/",
    "renders/",
    "snapshots/",
    "qa/",
    "capture/**/frames/",
    "**/.DS_Store",
)
# HyperFrames plays only media declared as elements with a src, so unreferenced audio/video never renders
MEDIA_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".m4v", ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
REF_ATTR = re.compile(r"""\b(?:src|href|poster|data-src)\s*=\s*["']([^"'#?]+)""", re.I)
REF_URL = re.compile(r"""url\(\s*["']?([^"')#?]+)""", re.I)
PIN = re.compile(r"hyperframes@(\d+\.\d+\.\d+)")


class CloudRenderError(RuntimeError):
    pass


# ── configuration ────────────────────────────────────────────────────────────────────────────────────────────────


def resolve_cloud(project_dir: Path | None, cli_profile: str | None) -> Resolved:
    """The applicable profile, which must name a gcloud configuration and a GCP project for cloud rendering."""
    r = resolve_profile(project_dir, load_config(), cli_profile)
    assert r is not None
    missing = [k for k in ("gcloud_configuration", "project") if not r.profile.get(k)]
    if missing:
        raise CloudRenderError(f"profile {r.name!r} has no {', '.join(missing)}; add them to "
                               f"{config_dir() / 'profiles.toml'} to render it in the cloud")
    return r


def profile_dir(name: str) -> Path:
    return config_dir() / "cloudrun" / name


def adc_path(name: str, profile: dict[str, Any]) -> Path:
    return Path(profile.get("adc_file") or config_dir() / "adc" / f"{name}.json").expanduser()


def profile_env(name: str, profile: dict[str, Any], base: dict[str, str] | None = None) -> dict[str, str]:
    """Environment for every gcloud / Terraform / SDK call made for this profile."""
    env = dict(os.environ if base is None else base)
    env["CLOUDSDK_ACTIVE_CONFIG_NAME"] = profile["gcloud_configuration"]
    env["CLOUDSDK_CORE_PROJECT"] = profile["project"]
    env["GOOGLE_CLOUD_PROJECT"] = profile["project"]
    env.pop("GOOGLE_OAUTH_ACCESS_TOKEN", None)
    adc = adc_path(name, profile)
    if adc.exists():
        env["GOOGLE_APPLICATION_CREDENTIALS"] = str(adc)
    else:
        env.pop("GOOGLE_APPLICATION_CREDENTIALS", None)
    return env


# ── project inspection and staging ───────────────────────────────────────────────────────────────────────────────


def read_ignore_file(project_dir: Path) -> list[str]:
    f = project_dir / ".hyperframesignore"
    if not f.exists():
        return []
    return [ln.strip() for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]


def is_excluded(rel: str, is_dir: bool, patterns: list[str] | tuple[str, ...]) -> bool:
    rel = rel.strip("/")
    for raw in patterns:
        pat = raw.strip()
        dir_only = pat.endswith("/")
        pat = pat.strip("/")
        if dir_only and not is_dir:
            continue
        if "/" not in pat and "**" not in pat:
            # bare name: any path component (gitignore semantics)
            if fnmatch.fnmatch(rel.rsplit("/", 1)[-1], pat):
                return True
            continue
        if fnmatch.fnmatch(rel, pat) or (pat.startswith("**/") and fnmatch.fnmatch(rel, pat[3:])):
            return True
        if "**/" in pat and fnmatch.fnmatch(rel, pat.replace("**/", "")):
            return True
    return False


def stage_project(src: Path, dest: Path, patterns: list[str] | tuple[str, ...]) -> tuple[int, int, list[str]]:
    """Mirror src into dest (hard links where possible) without excluded paths. Returns files, bytes, skipped."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    files = total = 0
    skipped: list[str] = []
    for root, dirs, names in os.walk(src):
        rel_root = Path(root).relative_to(src).as_posix()
        rel_root = "" if rel_root == "." else rel_root
        keep = []
        for sub in dirs:
            rel = f"{rel_root}/{sub}" if rel_root else sub
            if is_excluded(rel, True, patterns):
                skipped.append(rel + "/")
            else:
                keep.append(sub)
        dirs[:] = keep
        for n in names:
            rel = f"{rel_root}/{n}" if rel_root else n
            if is_excluded(rel, False, patterns):
                skipped.append(rel)
                continue
            src_file, dst_file = Path(root) / n, dest / rel
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(src_file, dst_file)
            except OSError:
                shutil.copy2(src_file, dst_file)
            files += 1
            total += src_file.stat().st_size
    return files, total, skipped


def referenced_assets(project_dir: Path) -> set[str]:
    """Project-relative paths of local files referenced from index.html and composition HTML."""
    refs: set[str] = set()
    pages = [project_dir / "index.html", *sorted((project_dir / "compositions").rglob("*.html"))]
    for page in pages:
        if not page.exists():
            continue
        text = page.read_text(encoding="utf-8", errors="replace")
        for m in [*REF_ATTR.finditer(text), *REF_URL.finditer(text)]:
            ref = m.group(1).strip()
            if not ref or re.match(r"^(?:[a-z]+:|//|\$|\{)", ref, re.I) or ref.startswith("#"):
                continue
            # composition sources resolve against the project root (HyperFrames mounts them there)
            while ref.startswith("./"):
                ref = ref[2:]
            refs.add(ref.lstrip("/"))
    return {r for r in refs if not r.startswith("../")}


def drop_unreferenced_media(project_dir: Path, staged: Path) -> tuple[int, int]:
    """Remove staged audio/video files no composition references. Returns files, bytes removed."""
    refs = referenced_assets(project_dir)
    n = total = 0
    for f in sorted(staged.rglob("*")):
        if f.is_file() and f.suffix.lower() in MEDIA_EXTS and f.relative_to(staged).as_posix() not in refs:
            total += f.stat().st_size
            f.unlink()
            n += 1
    return n, total


def missing_references(project_dir: Path, staged: Path) -> list[str]:
    return sorted(r for r in referenced_assets(project_dir) if (project_dir / r).exists() and not (staged / r).exists())


def project_dims(project_dir: Path) -> tuple[int, int, int]:
    html = (project_dir / "index.html").read_text(encoding="utf-8", errors="replace")
    root = re.search(r"<[^>]*data-composition-id[^>]*>", html)
    head = root.group(0) if root else html

    def attr(name: str, default: int | None) -> int:
        m = re.search(rf'data-{name}="(\d+)"', head) or re.search(rf'data-{name}="(\d+)"', html)
        if m:
            return int(m.group(1))
        if default is None:
            raise CloudRenderError(f"index.html has no data-{name}")
        return default

    return attr("width", None), attr("height", None), attr("fps", 30)


def pinned_version(project_dir: Path) -> str | None:
    pkg = project_dir / "package.json"
    if not pkg.exists():
        return None
    m = PIN.search(pkg.read_text(encoding="utf-8"))
    return m.group(1) if m else None


def composition_duration(project_dir: Path) -> float | None:
    html = (project_dir / "index.html").read_text(encoding="utf-8", errors="replace")
    root = re.search(r"<[^>]*data-composition-id[^>]*>", html)
    m = re.search(r'data-duration="([\d.]+)"', root.group(0)) if root else None
    return float(m.group(1)) if m else None


# ── processes ────────────────────────────────────────────────────────────────────────────────────────────────────


def run(cmd: list[str], env: dict[str, str], cwd: Path | None = None, capture: bool = False, check: bool = True) -> str:
    print("→", " ".join(cmd), file=sys.stderr)
    res = subprocess.run(cmd, env=env, cwd=cwd, text=True, capture_output=capture)
    if check and res.returncode != 0:
        raise CloudRenderError(f"{cmd[0]} exited {res.returncode}" + (f": {res.stderr.strip()[-600:]}" if capture else ""))
    return res.stdout if capture else ""


def quiet(cmd: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, env=env, text=True, capture_output=True)


def confirm(message: str, assume_yes: bool) -> None:
    if assume_yes:
        return
    if not sys.stdin.isatty():
        raise CloudRenderError(f"{message} — needs confirmation; re-run with --yes")
    if input(f"{message} [y/N] ").strip().lower() not in ("y", "yes"):
        raise CloudRenderError("cancelled")


def ensure_runtime(version: str) -> Path:
    """A pinned hyperframes + Cloud Run adapter install outside the npx cache (its Terraform module and SDK)."""
    rt = cache_dir() / "hyperframes-cloudrun" / version
    marker = rt / "node_modules" / "@hyperframes" / "gcp-cloud-run" / "package.json"
    if not marker.exists():
        rt.mkdir(parents=True, exist_ok=True)
        (rt / "package.json").write_text(json.dumps({"name": "hf-cloudrun-runtime", "private": True, "type": "module"}))
        run(["npm", "install", "--no-audit", "--no-fund", f"hyperframes@{version}",
             f"@hyperframes/gcp-cloud-run@{version}"], dict(os.environ), cwd=rt)
    shutil.copy2(Path(__file__).with_name("templates") / "cloudrun_runner.mjs", rt / "cloudrun_runner.mjs")
    return rt


def run_runner(rt: Path, job: dict[str, Any], env: dict[str, str]) -> dict[str, Any]:
    proc = subprocess.Popen(["node", "cloudrun_runner.mjs"], cwd=rt, env=env, text=True,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=sys.stderr)
    out, _ = proc.communicate(json.dumps(job))
    if proc.returncode != 0:
        raise CloudRenderError(f"cloud render runner exited {proc.returncode}")
    return json.loads(out.strip().splitlines()[-1])


# ── subcommands ──────────────────────────────────────────────────────────────────────────────────────────────────


def load_stack(name: str) -> dict[str, Any]:
    f = profile_dir(name) / "stack.json"
    if not f.exists():
        raise CloudRenderError(f"profile {name!r} has no deployed stack; run `media-cloud-render deploy --profile {name}`")
    return json.loads(f.read_text())


def cmd_which(args: argparse.Namespace) -> int:
    r = resolve_cloud(Path(args.project).resolve() if args.project else None, args.profile)
    stack = profile_dir(r.name) / "stack.json"
    print(json.dumps({"profile": r.name, "reason": r.reason, "gcloud_configuration": r.profile["gcloud_configuration"],
                      "account": r.profile.get("account"), "project": r.profile["project"],
                      "region": r.profile.get("region", DEFAULT_REGION), "stack_deployed": stack.exists()}, indent=1))
    return 0


def cmd_setup(args: argparse.Namespace) -> int:
    r = resolve_cloud(None, args.profile)
    p, name = r.profile, r.name
    conf = p["gcloud_configuration"]
    env = profile_env(name, p)
    configs = json.loads(quiet(["gcloud", "config", "configurations", "list", "--format=json"], dict(os.environ)).stdout or "[]")
    if conf not in {c["name"] for c in configs}:
        run(["gcloud", "config", "configurations", "create", conf, "--no-activate"], dict(os.environ))
        if p.get("account"):
            run(["gcloud", "config", "set", "account", p["account"], "--configuration", conf], dict(os.environ))
        # the project is optional here (every call gets CLOUDSDK_CORE_PROJECT); setting it validates against a login
        quiet(["gcloud", "config", "set", "project", p["project"], "--configuration", conf, "--quiet"], dict(os.environ))
        print(f"created gcloud configuration {conf} (not activated)")
    ok_login = quiet(["gcloud", "auth", "print-access-token"], env).returncode == 0
    adc = adc_path(name, p)
    if args.save_adc:
        src = Path("~/.config/gcloud/application_default_credentials.json").expanduser()
        if not src.exists():
            raise CloudRenderError("no Application Default Credentials; run `gcloud auth application-default login` first")
        data = json.loads(src.read_text())
        data["quota_project_id"] = p["project"]
        adc.parent.mkdir(parents=True, exist_ok=True)
        adc.write_text(json.dumps(data))
        adc.chmod(0o600)
        print(f"saved Application Default Credentials for {name} to {adc} (quota project {p['project']})")
    report = {
        "profile": name, "gcloud_configuration": conf, "account": p.get("account"), "project": p["project"],
        "gcloud_login": "ok" if ok_login else f"run: gcloud auth login {p.get('account', '')} --configuration {conf}".strip(),
        "adc_file": "ok" if adc.exists() else (
            f"run: gcloud auth application-default login (sign in as {p.get('account', 'the profile account')}), "
            f"then: media-cloud-render setup --profile {name} --save-adc"),
        "terraform": "ok" if shutil.which("terraform") else "missing: brew install terraform",
        "node": "ok" if shutil.which("node") else "missing",
    }
    print(json.dumps(report, indent=1))
    return 0 if all(v == "ok" for k, v in report.items() if k in ("gcloud_login", "adc_file", "terraform", "node")) else 1


def cmd_deploy(args: argparse.Namespace) -> int:
    r = resolve_cloud(None, args.profile)
    p, name = r.profile, r.name
    project, region = p["project"], p.get("region", DEFAULT_REGION)
    version = args.hyperframes_version or p.get("hyperframes_version") or DEFAULT_HYPERFRAMES_VERSION
    if not shutil.which("terraform"):
        raise CloudRenderError("terraform is required: brew install terraform")
    env = profile_env(name, p)
    if "GOOGLE_APPLICATION_CREDENTIALS" not in env:
        raise CloudRenderError(f"profile {name!r} has no ADC file; run `media-cloud-render setup --profile {name}`")
    image = args.image or f"{region}-docker.pkg.dev/{project}/{ARTIFACT_REPO}/hyperframes-render:{version}"
    state_bucket = p.get("tfstate_bucket") or f"{project}-hyperframes-tfstate"
    confirm(f"Deploy the HyperFrames Cloud Run stack {version} to {project} ({region}) as {p.get('account', p['gcloud_configuration'])}? "
            "This enables APIs, builds an image with Cloud Build, and creates billable resources", args.yes)

    run(["gcloud", "services", "enable", *GCP_APIS, "--project", project], env)
    if quiet(["gcloud", "artifacts", "repositories", "describe", ARTIFACT_REPO, "--location", region, "--project", project], env).returncode:
        run(["gcloud", "artifacts", "repositories", "create", ARTIFACT_REPO, "--repository-format=docker",
             "--location", region, "--project", project], env)
    if not args.image:
        src = cache_dir() / "hyperframes-src" / version
        if not (src / "packages" / "gcp-cloud-run" / "Dockerfile").exists():
            src.parent.mkdir(parents=True, exist_ok=True)
            run(["git", "clone", "--depth", "1", "--branch", f"v{version}", HYPERFRAMES_REPO, str(src)], dict(os.environ))
        build = src / ".cloudbuild-hyperframes.yaml"
        build.write_text("\n".join([
            "steps:", "- name: gcr.io/cloud-builders/docker",
            f'  args: ["build","-f","packages/gcp-cloud-run/Dockerfile","-t","{image}","."]',
            f'images: ["{image}"]', "timeout: 3600s", "options:", "  machineType: E2_HIGHCPU_8", ""]))
        run(["gcloud", "builds", "submit", str(src), "--project", project, "--region", region,
             "--config", str(build), "--timeout", "3600s"], env)

    if quiet(["gcloud", "storage", "buckets", "describe", f"gs://{state_bucket}", "--project", project], env).returncode:
        run(["gcloud", "storage", "buckets", "create", f"gs://{state_bucket}", "--project", project,
             "--location", region, "--uniform-bucket-level-access"], env)
        run(["gcloud", "storage", "buckets", "update", f"gs://{state_bucket}", "--versioning"], env)

    rt = ensure_runtime(version)
    tf = profile_dir(name) / "terraform"
    if tf.exists():
        for child in tf.iterdir():   # refresh the module files, keep .terraform (provider cache)
            if child.name != ".terraform":
                shutil.rmtree(child) if child.is_dir() else child.unlink()
    shutil.copytree(rt / "node_modules" / "@hyperframes" / "gcp-cloud-run" / "terraform", tf, dirs_exist_ok=True)
    (tf / "backend_override.tf").write_text(
        f'terraform {{\n  backend "gcs" {{\n    bucket = "{state_bucket}"\n    prefix = "hyperframes-cloudrun"\n  }}\n}}\n')
    tfvars = ["-var", f"project_id={project}", "-var", f"region={region}", "-var", f"image={image}"]
    for key in ("cpu", "memory", "max_instances"):
        if p.get(key) is not None:
            tfvars += ["-var", f"{key}={p[key]}"]
    run(["terraform", "init", "-input=false", "-reconfigure"], env, cwd=tf)
    run(["terraform", "apply", "-input=false", "-auto-approve", *tfvars], env, cwd=tf)

    def out(key: str) -> str:
        return run(["terraform", "output", "-raw", key], env, cwd=tf, capture=True).strip()

    stack = {"profile": name, "project": project, "region": region, "bucketName": out("render_bucket_name"),
             "serviceUrl": out("service_url"), "workflowId": out("workflow_name"), "image": image,
             "hyperframes_version": version, "tfstate_bucket": state_bucket,
             "deployed_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}
    (profile_dir(name) / "stack.json").write_text(json.dumps(stack, indent=1))
    print(json.dumps(stack, indent=1))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    cfg = load_config()
    names = [args.profile] if args.profile else sorted(cfg["profiles"])
    out = {}
    for n in names:
        f = profile_dir(n) / "stack.json"
        out[n] = json.loads(f.read_text()) if f.exists() else None
    print(json.dumps(out, indent=1))
    return 0


def cmd_destroy(args: argparse.Namespace) -> int:
    r = resolve_cloud(None, args.profile)
    p, name = r.profile, r.name
    stack = load_stack(name)
    env = profile_env(name, p)
    confirm(f"Destroy the Cloud Run render stack in {stack['project']} (bucket {stack['bucketName']} and its renders)?", args.yes)
    tf = profile_dir(name) / "terraform"
    tfvars = ["-var", f"project_id={stack['project']}", "-var", f"region={stack['region']}", "-var", f"image={stack['image']}"]
    run(["terraform", "init", "-input=false", "-reconfigure"], env, cwd=tf)
    run(["terraform", "destroy", "-input=false", "-auto-approve", *tfvars], env, cwd=tf)
    (profile_dir(name) / "stack.json").rename(profile_dir(name) / f"stack.destroyed-{int(time.time())}.json")
    print(f"destroyed the {name} stack; the Terraform state bucket gs://{stack['tfstate_bucket']} is kept")
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    project_dir = Path(args.project).resolve()
    if not (project_dir / "index.html").exists():
        raise CloudRenderError(f"{project_dir} has no index.html (run `hyperframes` assemble first)")
    r = resolve_cloud(project_dir, args.profile)
    p, name = r.profile, r.name
    width, height, fps = project_dims(project_dir)
    if args.fps:
        fps = args.fps
    pin = pinned_version(project_dir)
    stack = None if args.dry_run and not (profile_dir(name) / "stack.json").exists() else load_stack(name)
    stack_version = stack["hyperframes_version"] if stack else None

    stage = cache_dir() / "cloudrun-stage" / name / project_dir.name
    patterns = [*DEFAULT_EXCLUDES, *read_ignore_file(project_dir), *(args.exclude or [])]
    files, size, skipped = stage_project(project_dir, stage, patterns)
    dropped = (0, 0) if args.keep_unreferenced_media else drop_unreferenced_media(project_dir, stage)
    files, size = files - dropped[0], size - dropped[1]
    missing = missing_references(project_dir, stage)
    duration = composition_duration(project_dir)
    frames = round(duration * fps) if duration else None
    summary = {
        "profile": name, "why": r.reason, "account": p.get("account"), "gcloud_configuration": p["gcloud_configuration"],
        "gcp_project": p["project"], "region": p.get("region", DEFAULT_REGION),
        "stack": stack and {k: stack[k] for k in ("bucketName", "workflowId", "hyperframes_version")},
        "project_dir": str(project_dir), "size": f"{width}x{height}@{fps}", "duration_s": duration, "frames": frames,
        "quality": args.quality, "max_parallel_chunks": args.max_parallel_chunks,
        "upload": {"files": files, "mb": round(size / 1e6, 1), "excluded_paths": len(skipped),
                   "unreferenced_media_left_out": {"files": dropped[0], "mb": round(dropped[1] / 1e6, 1)}},
        "project_pins_hyperframes": pin,
    }
    print(json.dumps(summary, indent=1))
    if missing:
        raise CloudRenderError(f"excluded paths remove referenced assets: {missing[:10]}")
    if pin and stack_version and pin != stack_version:
        print(f"warning: the project pins hyperframes@{pin}, the {name} stack renders with {stack_version}; "
              "check the result against a local render", file=sys.stderr)
    if args.dry_run:
        print(f"dry run: staged at {stage}; nothing uploaded", file=sys.stderr)
        return 0
    assert stack is not None
    env = profile_env(name, p)
    if "GOOGLE_APPLICATION_CREDENTIALS" not in env:
        raise CloudRenderError(f"profile {name!r} has no ADC file; run `media-cloud-render setup --profile {name}`")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = Path(args.out).resolve() if args.out else project_dir / "renders" / f"cloud-{stamp}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    config: dict[str, Any] = {"fps": fps, "width": width, "height": height, "format": "mp4", "quality": args.quality,
                              "maxParallelChunks": args.max_parallel_chunks}
    if args.chunk_size:
        config["chunkSize"] = args.chunk_size
    rt = ensure_runtime(stack["hyperframes_version"])
    t0 = time.time()
    result = run_runner(rt, {
        "projectDir": str(stage), "config": config, "bucketName": stack["bucketName"], "projectId": stack["project"],
        "location": stack["region"], "workflowId": stack["workflowId"], "serviceUrl": stack["serviceUrl"],
        "renderId": f"{re.sub(r'[^A-Za-z0-9._-]', '-', project_dir.name)}-{stamp}", "out": str(out),
        "pollSeconds": args.poll_seconds, "vcpu": int(p.get("cpu", 4)),
        "memoryGib": int(str(p.get("memory", "16Gi")).rstrip("Gi") or 16)}, env)
    record = {**summary, "render": result, "output": str(out), "wall_s": round(time.time() - t0, 1),
              "rendered_at": stamp}
    out.with_suffix(".json").write_text(json.dumps(record, indent=1))
    print(json.dumps({"output": str(out), "wall_s": record["wall_s"], "cost": result.get("cost")}, indent=1))
    if not args.keep_stage:
        shutil.rmtree(stage, ignore_errors=True)
    return 0 if result.get("status") == "succeeded" else 1


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="media-cloud-render", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("which", help="show the profile, account and GCP project a project would render with")
    w.add_argument("project", nargs="?")
    w.add_argument("--profile")
    s = sub.add_parser("setup", help="create the profile's gcloud configuration and check its credentials")
    s.add_argument("--profile", required=True)
    s.add_argument("--save-adc", action="store_true",
                   help="copy the current Application Default Credentials into this profile's credential file")
    d = sub.add_parser("deploy", help="build the image and apply the render stack in the profile's GCP project")
    d.add_argument("--profile", required=True)
    d.add_argument("--hyperframes-version")
    d.add_argument("--image", help="use an existing render image instead of building one")
    d.add_argument("--yes", action="store_true")
    st = sub.add_parser("status", help="print deployed stack coordinates per profile")
    st.add_argument("--profile")
    x = sub.add_parser("destroy", help="remove the profile's render stack (keeps the Terraform state bucket)")
    x.add_argument("--profile", required=True)
    x.add_argument("--yes", action="store_true")
    rn = sub.add_parser("render", help="render a HyperFrames project on the profile's stack and download the MP4")
    rn.add_argument("project")
    rn.add_argument("--profile")
    rn.add_argument("--out", help="output MP4 (default: <project>/renders/cloud-<utc>.mp4)")
    rn.add_argument("--quality", default="high", choices=("draft", "standard", "high"))
    rn.add_argument("--fps", type=int)
    rn.add_argument("--max-parallel-chunks", type=int, default=16)
    rn.add_argument("--chunk-size", type=int)
    rn.add_argument("--exclude", action="append", help="extra root-relative exclude pattern (repeatable)")
    rn.add_argument("--poll-seconds", type=int, default=10)
    rn.add_argument("--keep-stage", action="store_true")
    rn.add_argument("--keep-unreferenced-media", action="store_true",
                    help="upload audio/video files no composition references (left out by default)")
    rn.add_argument("--dry-run", action="store_true", help="resolve, stage and check; upload nothing")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handler = {"which": cmd_which, "setup": cmd_setup, "deploy": cmd_deploy, "status": cmd_status,
               "destroy": cmd_destroy, "render": cmd_render}[args.cmd]
    try:
        return handler(args)
    except (CloudRenderError, LocalConfigError) as exc:
        print(f"media-cloud-render: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
