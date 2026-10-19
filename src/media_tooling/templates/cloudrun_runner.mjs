// One HyperFrames Cloud Run render, driven through the adapter SDK with explicit stack coordinates (no shared
// ~/.hyperframes/cloudrun-state.json), then downloaded. Copied next to a pinned hyperframes + @hyperframes/gcp-cloud-run
// install by media-cloud-render, which also sets the profile's credentials in the environment.
//
// stdin: {projectDir, config, bucketName, projectId, location, workflowId, serviceUrl, renderId, out, pollSeconds}
// stderr: one JSON progress line per poll; stdout: the final JSON result.
import { renderToCloudRun, getRenderProgress } from "@hyperframes/gcp-cloud-run/sdk";
import { Storage } from "@google-cloud/storage";

const chunks = [];
for await (const c of process.stdin) chunks.push(c);
const job = JSON.parse(Buffer.concat(chunks).toString("utf8"));

const handle = await renderToCloudRun({
  projectDir: job.projectDir,
  config: job.config,
  bucketName: job.bucketName,
  projectId: job.projectId,
  location: job.location,
  workflowId: job.workflowId,
  serviceUrl: job.serviceUrl,
  renderId: job.renderId,
});
console.error(JSON.stringify({ started: handle.executionName ?? handle.renderId, renderId: handle.renderId }));

let progress;
for (;;) {
  progress = await getRenderProgress({ executionName: handle.executionName, vcpu: job.vcpu, memoryGib: job.memoryGib });
  console.error(
    JSON.stringify({
      status: progress.status,
      progress: Math.round((progress.overallProgress ?? 0) * 1000) / 10,
      frames: progress.framesRendered,
      total: progress.totalFrames,
      cost: progress.costs?.displayCost,
    }),
  );
  if (progress.status !== "running") break;
  await new Promise((r) => setTimeout(r, (job.pollSeconds ?? 10) * 1000));
}

const result = {
  status: progress.status,
  renderId: handle.renderId,
  executionName: handle.executionName,
  framesRendered: progress.framesRendered,
  totalFrames: progress.totalFrames,
  cost: progress.costs?.displayCost ?? null,
  costs: progress.costs ?? null,
  errors: progress.errors ?? [],
  startedAt: progress.startedAt,
  endedAt: progress.endedAt,
  gcsUri: progress.outputFile?.gcsUri ?? null,
};

if (progress.status === "succeeded" && result.gcsUri) {
  const m = /^gs:\/\/([^/]+)\/(.+)$/.exec(result.gcsUri);
  await new Storage({ projectId: job.projectId }).bucket(m[1]).file(m[2]).download({ destination: job.out });
  result.downloaded = job.out;
}
console.log(JSON.stringify(result));
