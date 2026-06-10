import { WikiLayout } from "@/components/WikiLayout";

export default function DeployStrategiesPage(): React.ReactElement {
  return (
    <WikiLayout title="Deploy Strategies" description="The deploy.strategy enum and what each value means.">
      <div className="prose-wiki max-w-3xl">
        <h1>Deploy Strategies</h1>
        <p>
          Every deployable service has a <code>deploy.strategy</code>. It is the{" "}
          <strong>single selector the orchestrator dispatches on</strong> — it absorbed the
          concept that <code>foundry-ops</code> previously called <code>kind</code>. The
          convention engine derives the other <code>deploy</code> fields (Dockerfile, build
          context, secrets) from <code>stack</code> + <code>scope</code>.
        </p>

        <h2>The enum</h2>
        <table>
          <thead>
            <tr><th>Strategy</th><th>Meaning</th></tr>
          </thead>
          <tbody>
            <tr><td><code>service</code></td><td>Containerized — ECS Fargate</td></tr>
            <tr><td><code>static</code></td><td>S3 / CDN static hosting (SPA or static site)</td></tr>
            <tr><td><code>desktop</code></td><td>Tauri desktop release — signed installers + updater manifest</td></tr>
            <tr><td><code>game-publisher</code></td><td>UE5 game build / publish</td></tr>
            <tr><td><code>none</code></td><td>Not deployed (libraries / packages)</td></tr>
          </tbody>
        </table>

        <h2>Convention defaults</h2>
        <p>
          When a discovered service is added by <code>foundry init</code>, the strategy is
          inferred from <code>stack</code>: a <code>backend</code> defaults to{" "}
          <code>service</code>, a plain <code>frontend</code> to <code>static</code> (a Next.js
          frontend can be <code>service</code> for SSR), and a <code>package</code> to{" "}
          <code>none</code>. You can override any of these in the manifest.
        </p>

        <h2>Common deploy fields</h2>
        <table>
          <thead>
            <tr><th>Field</th><th>Used by</th><th>Description</th></tr>
          </thead>
          <tbody>
            <tr><td><code>strategy</code></td><td>all</td><td>The selector (required for deployable services)</td></tr>
            <tr><td><code>buildCommand</code></td><td><code>static</code></td><td>Shell command that builds the static assets</td></tr>
            <tr><td><code>cdn</code></td><td><code>static</code></td><td>Enable CloudFront in front of the bucket</td></tr>
            <tr><td><code>dockerfile</code> / <code>buildContext</code></td><td><code>service</code></td><td>Docker build inputs (defaulted by convention)</td></tr>
            <tr><td><code>secrets</code></td><td><code>service</code></td><td>Secrets to fetch from Secrets Manager into the container</td></tr>
            <tr><td><code>dependsOn</code></td><td>all</td><td>Services/phases that must finish first (e.g. <code>iac</code>, <code>database:&#123;name&#125;</code>)</td></tr>
            <tr><td><code>iac</code></td><td>all</td><td>Provider-specific deploy config passed through to IaC (compute, ALB, stack path, domain, …)</td></tr>
          </tbody>
        </table>

        <h2>Implementation status</h2>
        <blockquote>
          The <code>deploy.strategy</code> enum is fully defined in the schema, but the{" "}
          <a href="/docs/deploy/orchestrator">orchestrator</a> only implements{" "}
          <code>static</code> end-to-end today. <code>service</code>, <code>desktop</code>, and{" "}
          <code>game-publisher</code> are stubbed pending engine relocation — see{" "}
          <a href="/docs/deploy/orchestrator">Orchestrator &amp; Strategies</a> for the live
          status table.
        </blockquote>
      </div>
    </WikiLayout>
  );
}
