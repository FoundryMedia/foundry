import { WikiLayout } from "@/components/WikiLayout";

export default function OnboardServicePage(): React.ReactElement {
  return (
    <WikiLayout title="Onboard a New Repo/Service" description="Add a multi-repo service to the orchestrated deploy.">
      <div className="prose-wiki max-w-3xl">
        <h1>Onboard a New Repo/Service</h1>
        <p>
          This is the happy path for adding a new <strong>static</strong> service (the strategy the
          orchestrator implements today) to the multi-repo, orchestrated deploy. Four pieces wire
          it together.
        </p>

        <h2>1. Add a service to the central manifest</h2>
        <p>
          In <a href="/docs/manifest/central"><code>foundry-ops/platform.json</code></a>, add an
          entry with <code>repository</code> / <code>path</code>, a <code>stack</code>, a{" "}
          <code>deploy.strategy</code>, the environment→branch map, and a <code>deploy.iac</code>{" "}
          block:
        </p>
        <pre><code>{`"docs": {
  "repository": "FoundryMedia/my-repo",
  "path": ".",
  "environments": { "prod": { "branch": "main" } },
  "scope": "public",
  "stack": { "type": "frontend", "framework": "vite", "language": "typescript" },
  "deploy": {
    "strategy": "static",
    "buildCommand": "npm ci && npm run build",
    "cdn": true,
    "dependsOn": ["iac"],
    "iac": {
      "stackPath": "ci/iac/prod",
      "domain": "docs.example.com",
      "distDir": "dist",
      "region": "us-east-2",
      "roleArn": "arn:aws:iam::<acct>:role/my-repo-tofu-runner",
      "bucketOutput": "bucket_name",
      "distributionIdOutput": "distribution_id"
    }
  }
}`}</code></pre>

        <h2>2. Add the per-repo app-edge stack</h2>
        <p>
          In the service repo, create the OpenTofu stack at <code>deploy.iac.stackPath</code>{" "}
          (e.g. <code>ci/iac/prod</code>) — bucket, certificate, CloudFront, DNS, and the
          tofu-runner IAM role. It must expose the outputs named in the manifest
          (<code>bucket_name</code>, <code>distribution_id</code>). See{" "}
          <a href="/docs/iac/layout">IaC Layout</a>.
        </p>

        <h2>3. Generate the thin caller workflow</h2>
        <p>
          Run <a href="/docs/cli/generate"><code>foundry generate callers</code></a> against the
          central manifest to emit the service{"'"}s thin-caller workflow into its repo — it
          delegates to the ops repo{"'"}s reusable deploy workflow with{" "}
          <code>secrets: inherit</code>. See <a href="/docs/deploy/thin-caller">Thin Caller</a>.
        </p>

        <h2>4. Create the tofu-runner role</h2>
        <p>
          Provision the IAM role referenced by <code>deploy.iac.roleArn</code> as a GitHub OIDC
          assume-role, scoped to the repo. The reusable workflow assumes it to plan/apply the
          stack and publish the build.
        </p>

        <h2>Deploy</h2>
        <p>
          Trigger the caller workflow (push to the mapped branch or <code>workflow_dispatch</code>).
          The <a href="/docs/deploy/orchestrator">orchestrator</a> runs smart IaC on the stack,
          builds, syncs to S3, and invalidates CloudFront.
        </p>

        <blockquote>
          Only <code>static</code> works end-to-end through the orchestrator today.{" "}
          <code>service</code>, <code>desktop</code>, and <code>game-publisher</code> are stubbed —
          see <a href="/docs/deploy/orchestrator">Orchestrator &amp; Strategies</a>.
        </blockquote>
      </div>
    </WikiLayout>
  );
}
