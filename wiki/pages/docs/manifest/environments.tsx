import { WikiLayout } from "@/components/WikiLayout";

export default function EnvironmentsPage(): React.ReactElement {
  return (
    <WikiLayout title="Environments & Branches" description="How environments map to Git branches.">
      <div className="prose-wiki max-w-3xl">
        <h1>Environments &amp; Branches</h1>
        <p>
          A Foundry environment is a named deployment target mapped to a single Git branch. A push
          to that branch is what triggers a deploy to the environment. Environments are declared
          under <code>ci.environments</code>, and multi-repo services can override the mapping
          per-service.
        </p>

        <h2>ci.environments</h2>
        <p>
          The platform-wide map lives at <code>ci.environments</code>: keys are environment names,
          values are an <code>environmentConfig</code>. The CLI defaults, if you don{"'"}t declare
          them, are:
        </p>
        <pre><code>{`prod  → release
dev   → develop
test  → qa`}</code></pre>

        <h2>environmentConfig</h2>
        <table>
          <thead>
            <tr><th>Field</th><th>Type</th><th>Default</th><th>Description</th></tr>
          </thead>
          <tbody>
            <tr><td><code>branch</code></td><td>string</td><td>—</td><td>Git branch that triggers this environment (required)</td></tr>
            <tr><td><code>enabled</code></td><td>boolean</td><td><code>true</code></td><td>Disabled environments are excluded from pipeline triggers and tfvars generation</td></tr>
            <tr><td><code>autoApprove</code></td><td>boolean</td><td><code>false</code></td><td>Whether IaC changes apply without manual approval</td></tr>
            <tr><td><code>iac</code></td><td>object</td><td>—</td><td>Provider-specific config for this env (region, account, domain, …). Supports <code>&#123;name_prefix&#125;</code>, <code>&#123;prefix&#125;</code>, <code>&#123;env&#125;</code> template vars</td></tr>
          </tbody>
        </table>

        <h2>Example</h2>
        <pre><code>{`"ci": {
  "iac": "opentofu",
  "provider": "aws",
  "environments": {
    "prod": { "branch": "release", "autoApprove": false },
    "dev":  { "branch": "develop", "autoApprove": true }
  }
}`}</code></pre>

        <h2>Per-service overrides (multi-repo)</h2>
        <p>
          Services in different repos may follow different branch conventions. A service-level{" "}
          <code>environments</code> block overrides <code>ci.environments</code> for that service;
          any environment it omits falls back to the platform-wide value. For example, a service
          whose repo deploys prod from <code>main</code>:
        </p>
        <pre><code>{`"web": {
  "repository": "FoundryMedia/foundry-app",
  "environments": { "prod": { "branch": "main" } },
  "deploy": { "strategy": "static" }
}`}</code></pre>
        <p>
          Where <code>autoApprove</code> is <code>false</code>, the orchestrated pipeline gates the
          apply through a GitHub Environment{"'"}s required reviewers rather than the orchestrator
          script itself. See <a href="/docs/deploy/orchestrator">Orchestrator &amp; Strategies</a>.
        </p>
      </div>
    </WikiLayout>
  );
}
