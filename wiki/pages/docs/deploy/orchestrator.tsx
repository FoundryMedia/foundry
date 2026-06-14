import { WikiLayout } from "@/components/WikiLayout";

export default function OrchestratorPage(): React.ReactElement {
  return (
    <WikiLayout title="Orchestrator & Strategies" description="The orchestrator and what each deploy strategy does.">
      <div className="prose-wiki max-w-3xl">
        <h1>Orchestrator &amp; Strategies</h1>
        <p>
          The orchestrator (the ops repo{"'"}s <code>orchestrator/deploy.py</code>) is the single
          deploy brain. It reads the central manifest, looks up one service, and dispatches on its{" "}
          <code>deploy.strategy</code>. It uses only the Python standard library plus the{" "}
          <code>tofu</code>, <code>aws</code>, and shell tools available on the runner.
        </p>

        <h2>Invocation</h2>
        <pre><code>{`python3 orchestrator/deploy.py deploy \\
  --service web --env prod \\
  --manifest ops/platform.json \\
  --repo-root caller [--auto-approve]`}</code></pre>
        <p>
          The reusable workflow supplies these arguments — see{" "}
          <a href="/docs/deploy/thin-caller">the thin-caller &amp; reusable workflow</a>.
        </p>

        <h2>What each strategy does</h2>
        <table>
          <thead>
            <tr><th>Strategy</th><th>Behavior</th></tr>
          </thead>
          <tbody>
            <tr><td><code>static</code></td><td>Smart IaC → build → S3 sync → CloudFront invalidate</td></tr>
            <tr><td><code>service</code></td><td>Containerized build/push → ECS Fargate rollout</td></tr>
            <tr><td><code>desktop</code></td><td>Signed desktop installers + an updater manifest</td></tr>
            <tr><td><code>game-publisher</code></td><td>Game build / publish pipeline</td></tr>
            <tr><td><code>none</code></td><td>No-op — logs that there is nothing to deploy and returns</td></tr>
          </tbody>
        </table>

        <h2>The static path</h2>
        <ol>
          <li>
            <strong>Smart IaC.</strong> <code>tofu init</code>, then{" "}
            <code>tofu plan -detailed-exitcode</code>: exit <code>0</code> = no changes (skip
            apply), exit <code>2</code> = changes (apply the saved plan), exit <code>1</code> =
            error (fail). It then reads the bucket and distribution id from the stack{"'"}s OpenTofu
            outputs.
          </li>
          <li>
            <strong>Build.</strong> Runs the service{"'"}s <code>buildCommand</code> from the caller
            repo root, with <code>deploy.iac.buildEnv</code> merged into the environment.
          </li>
          <li>
            <strong>Publish.</strong> <code>aws s3 sync &lt;distDir&gt; s3://&lt;bucket&gt; --delete</code>{" "}
            then a CloudFront invalidation of <code>/*</code>.
          </li>
        </ol>

        <h2>Approval</h2>
        <p>
          The reusable workflow passes <code>--auto-approve</code>, so the orchestrator never
          blocks on a prompt. Manual approval for an environment is enforced by the GitHub
          Environment{"'"}s required reviewers, driven by{" "}
          <a href="/docs/manifest/environments"><code>autoApprove</code></a> — not by the script.
        </p>
      </div>
    </WikiLayout>
  );
}
