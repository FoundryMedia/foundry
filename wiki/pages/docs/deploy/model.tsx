import { WikiLayout } from "@/components/WikiLayout";

export default function DeployModelPage(): React.ReactElement {
  return (
    <WikiLayout title="Deploy Model" description="How a deploy flows from a push to live infrastructure.">
      <div className="prose-wiki max-w-3xl">
        <h1>Deploy Model</h1>
        <p>
          A multi-repo deploy is manifest-driven and orchestrated centrally. A service repo holds
          almost no deploy logic — it just calls into <code>foundry-ops</code>, which owns the
          pipeline.
        </p>

        <h2>The flow</h2>
        <pre><code>{`service-repo push
  → thin caller workflow (in the service repo)
    → foundry-ops reusable deploy.yml  (workflow_call)
      → orchestrator (orchestrator/deploy.py)
        → reads foundry-ops/platform.json, dispatches on deploy.strategy
          → smart IaC: tofu plan → apply ONLY on change
          → build
          → publish (e.g. S3 sync + CloudFront invalidate for static)`}</code></pre>

        <h2>Who owns what</h2>
        <table>
          <thead>
            <tr><th>Piece</th><th>Lives in</th><th>Role</th></tr>
          </thead>
          <tbody>
            <tr><td>Platform shape</td><td><a href="/docs/manifest/central"><code>foundry-ops/platform.json</code></a></td><td>Declares services, strategies, IaC targets</td></tr>
            <tr><td><a href="/docs/deploy/thin-caller">Thin caller</a></td><td>Each service repo</td><td>Minimal workflow that calls foundry-ops</td></tr>
            <tr><td>Reusable workflow + <a href="/docs/deploy/orchestrator">orchestrator</a></td><td><code>foundry-ops</code></td><td>Checkout, credentials, and the deploy engine</td></tr>
            <tr><td>Infrastructure</td><td><a href="/docs/iac/layout"><code>foundry-iac</code></a> + per-repo <code>ci/iac</code></td><td>Shared control plane + app-edge stacks</td></tr>
          </tbody>
        </table>

        <h2>Smart IaC</h2>
        <p>
          The orchestrator plans the service{"'"}s IaC stack with{" "}
          <code>tofu plan -detailed-exitcode</code> and only applies when there is an actual change
          (exit code 2); a no-change plan (exit 0) skips the apply. This keeps every deploy cheap
          and idempotent. Details in <a href="/docs/deploy/orchestrator">Orchestrator &amp; Strategies</a>.
        </p>

        <h2>Two deploy models coexist today</h2>
        <blockquote>
          <strong>Monorepo (in-repo):</strong> <a href="/docs/cli/generate"><code>foundry generate</code></a>{" "}
          emits a self-contained pipeline + <code>ci/scripts/</code> that run inside the same repo
          as the manifest. This is what a single-repo platform uses.
          <br /><br />
          <strong>Multi-repo (orchestrated):</strong> the flow above, owned by{" "}
          <code>foundry-ops</code>. Today it implements the <code>static</code> strategy
          end-to-end; <code>service</code>, <code>desktop</code>, and <code>game-publisher</code>{" "}
          are stubbed. Thin callers are generated from the central manifest by{" "}
          <a href="/docs/cli/generate"><code>foundry generate callers</code></a>; the reusable
          workflow and orchestrator engine are hand-maintained in the ops repo.
        </blockquote>
      </div>
    </WikiLayout>
  );
}
