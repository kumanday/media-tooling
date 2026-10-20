# Cloud rendering with `media-cloud-render`

`media-cloud-render` renders a HyperFrames project on Google Cloud Run (HyperFrames' own distributed renderer:
chunks of frames rendered in parallel, then joined) and downloads the MP4. It picks which GCP project pays through a
**render profile**, so client work and personal work never share a stack or a bill.

Narration (`media-tts-frames`), music (`media-video-music`) and generated shots (`media-generated` / fal) are API
calls and run the same anywhere; only the HyperFrames render moves to the cloud. Browser captures that need a GPU
(WebGL maps) stay local.

## Prerequisites

- the Google Cloud CLI (`gcloud`) and Node.js (the Cloud Run adapter SDK runs in Node)
- Terraform or OpenTofu. Homebrew removed `terraform` from homebrew-core after the license change, so
  `brew install terraform` fails with "No available formula"; install it from HashiCorp's tap, or install OpenTofu:

  ```bash
  brew tap hashicorp/tap
  brew install hashicorp/tap/terraform
  ```

  ```bash
  brew install opentofu
  ```

  `media-cloud-render` runs `terraform` when it is on `PATH` and `tofu` otherwise (for `init`, `apply`, `output` and
  `destroy`); `setup` reports which one it found.

## Profiles

Profiles live in `profiles.toml` in your private media-tooling folder (`~/.config/media-tooling/`, or
`MEDIA_TOOLING_CONFIG_DIR`; see [`LOCAL-CONFIG.md`](./LOCAL-CONFIG.md)). A profile used for cloud rendering needs a
gcloud configuration and a GCP project. No secrets:

```toml
default_profile = "personal"

[profiles.client]
gcloud_configuration = "client-cfg"     # a named gcloud configuration (gcloud config configurations list)
account = "me@client.example"
project = "client-gcp-project"
region = "us-central1"
hyperframes_version = "0.8.163"         # image version the stack is built with

[profiles.personal]
gcloud_configuration = "personal-cfg"
account = "me@example.com"
project = "personal-gcp-project"
region = "us-central1"

[[rules]]                               # first match wins
path = "~/dev/client/**"
profile = "client"
```

Optional per profile: `cpu`, `memory`, `max_instances` (Cloud Run sizing), `tfstate_bucket`, `adc_file`.

Which profile applies, highest first:

1. `--profile NAME`
2. `profile = "NAME"` (or `render_profile`) in the nearest `media-tooling.toml`, searched from the project folder upward
3. the first `[[rules]]` path that contains the project folder
4. `default_profile`

`media-cloud-render which <project>` prints the profile, the reason, the account and the GCP project.

## How the profiles stay apart

- Every gcloud, Terraform and SDK call runs with `CLOUDSDK_ACTIVE_CONFIG_NAME` set to the profile's configuration
  and `GOOGLE_APPLICATION_CREDENTIALS` set to the profile's own credential file. Your active gcloud configuration and
  global Application Default Credentials are never used, and never changed by a render.
- Each profile has its own stack coordinates (`~/.config/media-tooling/cloudrun/<profile>/stack.json`) and its own
  Terraform state, kept in a versioned bucket inside that profile's GCP project (`<project>-hyperframes-tfstate`).
- Why not `hyperframes cloudrun deploy`: it keeps one global `~/.hyperframes/cloudrun-state.json` and runs Terraform
  inside the npm package directory. A deploy to a second project would plan to replace the first project's stack,
  and clearing the npm cache would orphan the Terraform state. `media-cloud-render` applies the same Terraform module
  from its own working copy and drives renders through the adapter SDK with explicit coordinates.

## One-time setup per profile

```bash
media-cloud-render setup --profile client     # creates the gcloud configuration if missing, then reports
gcloud auth login me@client.example --configuration client-cfg
gcloud auth application-default login         # sign in as the profile's account
media-cloud-render setup --profile client --save-adc
```

`--save-adc` copies the current Application Default Credentials into `~/.config/media-tooling/adc/<profile>.json`
(mode 600, quota project set to the profile's project). Afterwards you can sign Application Default Credentials back
into your usual account; the profile keeps its own copy.

The browser sign-in of `gcloud auth application-default login` does not show which of your Google accounts it used,
so `--save-adc` checks first: it mints a short-lived access token from the credentials and asks Google's tokeninfo
endpoint for the account's email (the token travels only in request bodies and is never printed). If that email is
not the profile's `account` (compared case-insensitively), the command exits with an error that names both accounts,
saves nothing, and asks you to run `gcloud auth application-default login` again with the right account. A profile
without `account` is saved with a warning that shows the detected email. Only user credentials can be checked; to use
a service-account key, point the profile's `adc_file` at it instead.

Plain `setup` reports the account of the profile's saved credential file (`adc_account`), flags `adc_file` when that
account is not the profile's `account`, and shows whether it found `terraform` or `tofu`.

## Deploy (billable; asks first)

```bash
media-cloud-render deploy --profile client
```

Enables the Cloud Run, Workflows, Artifact Registry, Cloud Build, Monitoring and Storage APIs, and creates the
Workflows service agent (Google creates it lazily, and until it exists creating the workflow fails); builds the render
image with Cloud Build from the HyperFrames source at the profile's version (the npm package cannot build it); creates
the Terraform state bucket; applies the stack (render bucket, Cloud Run service, Workflows definition, two
least-privilege service accounts, alert policies). The stack scales to zero when idle; costs come from renders, the
image in Artifact Registry and objects in the buckets.

The image build uploads only the files the image's Dockerfile copies (under 10 MB; the rest of the HyperFrames
checkout is close to 1 GB, mostly test fixtures), stops before uploading if the checkout lacks one of them, and builds
with BuildKit for `linux/amd64`, the platform Cloud Run runs. To redeploy with an image the profile's project already
has (for example after a failed Terraform step), pass `--image REGISTRY/PATH:TAG` to skip the build.

## Render

```bash
media-cloud-render render path/to/slot --dry-run     # profile, account, project, upload size, frames; no upload
media-cloud-render render path/to/slot               # stage, upload, render, download, record
```

- The output goes to `<slot>/renders/cloud-<utc>.mp4` (or `--out`), with a `.json` record next to it: profile,
  project, stack version, frames, cost reported by the renderer and wall time.
- Staging leaves out generated outputs (`renders/`, `snapshots/`, `qa/`, `.hyperframes/`, `capture/**/frames/`,
  `.git/`, `node_modules/`, plus `.hyperframesignore` and `--exclude` patterns) and audio/video files no composition
  references. It fails if a composition references a local file that is not in the project (override with
  `--allow-missing-refs`) or that an exclusion would remove.
- Defaults: `--quality high`, `--max-parallel-chunks 16`, the composition's own size and fps.
- If the project pins a different HyperFrames version than the stack was built with, the command warns; compare
  against a local render before relying on it.
- Loudness normalization and delivery stay local steps on the downloaded master (for example `media-loudnorm`, or the
  project's delivery script), followed by `media-verify`.

## Other commands

`media-cloud-render status [--profile P]` prints the deployed coordinates; `media-cloud-render destroy --profile P`
removes the stack (asks first; the Terraform state bucket is kept).
