import { WikiLayout } from "@/components/WikiLayout";

export default function ThinCallerPage(): React.ReactElement {
  return (
    <WikiLayout title="Thin Caller & Reusable Workflow" description="How a service repo invokes the foundry-ops deploy workflow.">
      <div className="prose-wiki max-w-3xl">
        <h1>Thin Caller &amp; Reusable Workflow</h1>
        <p>
          A service repo does not contain deploy logic. It contains a <strong>thin caller</strong>{" "}
          — a small GitHub Actions workflow that invokes the reusable{" "}
          <code>workflow_call</code> in <code>foundry-ops</code>. All the real work happens in the
          reusable workflow and the <a href="/docs/deploy/orchestrator">orchestrator</a>.
        </p>

        <h2>The reusable workflow</h2>
        <p>
          <code>foundry-ops/.github/workflows/deploy.yml</code> is a reusable workflow. Its inputs:
        </p>
        <table>
          <thead>
            <tr><th>Input</th><th>Required</th><th>Default</th><th>Description</th></tr>
          </thead>
          <tbody>
            <tr><td><code>service</code></td><td>yes</td><td>—</td><td>Service key in <code>platform.json</code> (e.g. <code>web</code>)</td></tr>
            <tr><td><code>environment</code></td><td>no</td><td><code>prod</code></td><td>Environment to deploy (maps to a branch in the manifest)</td></tr>
          </tbody>
        </table>

        <h2>What it does</h2>
        <ol>
          <li>Checks out the caller repo.</li>
          <li>Mints a short-lived GitHub App token scoped to read <code>foundry-ops</code>.</li>
          <li>Checks out <code>foundry-ops</code> (manifest + orchestrator).</li>
          <li>Reads <code>platform.json</code> to resolve the service{"'"}s AWS <code>roleArn</code> and <code>region</code>.</li>
          <li>Sets up Node + corepack + OpenTofu.</li>
          <li>Configures AWS credentials via OIDC (assumes the resolved role — no long-lived keys).</li>
          <li>Runs the orchestrator against the checked-out caller repo.</li>
        </ol>

        <h2>The caller workflow</h2>
        <p>A service repo{"'"}s deploy workflow is just this:</p>
        <pre><code>{`name: Deploy
on:
  workflow_dispatch:
    inputs:
      service: { description: Service, required: true, type: string }
      environment: { description: Environment, required: false, default: prod, type: string }

jobs:
  deploy:
    uses: FoundryMedia/foundry-ops/.github/workflows/deploy.yml@main
    with:
      service: \${{ inputs.service }}
      environment: \${{ inputs.environment }}
    secrets: inherit`}</code></pre>
        <p>
          <code>secrets: inherit</code> forwards the org-level secrets (the GitHub App credentials)
          the reusable workflow needs. No deploy steps, no AWS wiring, no strategy logic live in
          the service repo.
        </p>
      </div>
    </WikiLayout>
  );
}
