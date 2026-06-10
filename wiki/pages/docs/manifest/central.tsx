import { WikiLayout } from "@/components/WikiLayout";

export default function CentralManifestPage(): React.ReactElement {
  return (
    <WikiLayout title="Central Manifest" description="The multi-repo manifest in foundry-ops.">
      <div className="prose-wiki max-w-3xl">
        <h1>Central Manifest — foundry-ops/platform.json</h1>
        <p>
          In a multi-repo platform, the authoritative manifest lives in <code>foundry-ops</code>{" "}
          as <code>platform.json</code>. It is an ordinary v0.7.0 manifest, but its services point
          at other repositories via <code>repository</code> / <code>path</code>. Individual service
          repos carry no manifest — only a <a href="/docs/deploy/thin-caller">thin caller</a>{" "}
          workflow.
        </p>

        <h2>What the orchestrator reads</h2>
        <p>
          For each service, the <a href="/docs/deploy/orchestrator">orchestrator</a> dispatches on{" "}
          <code>deploy.strategy</code> and reads <code>deploy.iac</code> for the concrete deploy
          targets. The fields used by the current <code>static</code> path:
        </p>
        <table>
          <thead>
            <tr><th>Field (<code>deploy.iac</code>)</th><th>Purpose</th></tr>
          </thead>
          <tbody>
            <tr><td><code>stackPath</code></td><td>Path to the per-repo OpenTofu stack (e.g. <code>ci/iac/web</code>)</td></tr>
            <tr><td><code>region</code></td><td>AWS region (defaults to <code>us-east-2</code>)</td></tr>
            <tr><td><code>roleArn</code></td><td>IAM role the workflow assumes via OIDC (the tofu-runner)</td></tr>
            <tr><td><code>domain</code></td><td>The service{"'"}s domain</td></tr>
            <tr><td><code>distDir</code></td><td>Build output directory to sync to S3 (caller-repo-relative)</td></tr>
            <tr><td><code>bucketOutput</code> / <code>distributionIdOutput</code></td><td>OpenTofu output names for the bucket + CloudFront distribution (default <code>bucket_name</code> / <code>distribution_id</code>)</td></tr>
            <tr><td><code>buildEnv</code></td><td>Environment variables injected into <code>buildCommand</code></td></tr>
          </tbody>
        </table>

        <h2>Example entry</h2>
        <pre><code>{`"web": {
  "repository": "FoundryMedia/foundry-app",
  "path": "app",
  "environments": { "prod": { "branch": "main" } },
  "scope": "public",
  "stack": { "type": "frontend", "framework": "vite", "language": "typescript" },
  "deploy": {
    "strategy": "static",
    "buildCommand": "pnpm install --frozen-lockfile && pnpm --filter app build",
    "cdn": true,
    "dependsOn": ["iac"],
    "iac": {
      "stackPath": "ci/iac/web",
      "domain": "foundryplatform.app",
      "distDir": "app/dist",
      "region": "us-east-2",
      "roleArn": "arn:aws:iam::<acct>:role/foundry-app-web-tofu-runner",
      "bucketOutput": "bucket_name",
      "distributionIdOutput": "distribution_id",
      "buildEnv": { "VITE_TARGET": "web", "VITE_API_BASE_URL": "https://api.foundryplatform.app" }
    }
  }
}`}</code></pre>

        <h2>Services it currently describes</h2>
        <table>
          <thead>
            <tr><th>Service</th><th>Repo / path</th><th>Strategy</th></tr>
          </thead>
          <tbody>
            <tr><td><code>web</code></td><td><code>foundry-app</code> / <code>app</code></td><td><code>static</code></td></tr>
            <tr><td><code>launcher</code></td><td><code>foundry-app</code> / root</td><td><code>desktop</code></td></tr>
            <tr><td><code>wiki</code></td><td><code>foundry</code> / <code>wiki</code></td><td><code>static</code></td></tr>
          </tbody>
        </table>
        <blockquote>
          Only <code>static</code> (<code>web</code>, <code>wiki</code>) deploys end-to-end today.{" "}
          <code>launcher</code> is declared with <code>desktop</code> but the orchestrator{"'"}s
          desktop path is still stubbed — see <a href="/docs/deploy/orchestrator">Orchestrator</a>.
        </blockquote>
      </div>
    </WikiLayout>
  );
}
