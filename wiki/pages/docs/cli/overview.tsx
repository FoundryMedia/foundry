import { WikiLayout } from "@/components/WikiLayout";

export default function CliOverviewPage(): React.ReactElement {
  return (
    <WikiLayout title="CLI Reference" description="The foundry command set.">
      <div className="prose-wiki max-w-3xl">
        <h1>CLI Reference</h1>
        <p>
          The <code>foundry</code> CLI scaffolds a platform, reconciles it with the filesystem,
          runs it locally, generates its CI/CD, and performs database operations. Each command is
          documented in detail on its own page.
        </p>

        <h2>Commands</h2>
        <table>
          <thead>
            <tr><th>Command</th><th>What it does</th><th>Writes</th></tr>
          </thead>
          <tbody>
            <tr><td><a href="/docs/cli/init"><code>foundry init</code></a></td><td>Create or refresh a platform</td><td><code>foundry.json</code>, <code>.foundry/</code></td></tr>
            <tr><td><a href="/docs/cli/generate"><code>foundry generate</code></a></td><td>Generate pipeline, deploy scripts, and tfvars</td><td><code>.github/workflows/deploy.yml</code>, <code>ci/scripts/</code>, <code>ci/iac/&#123;env&#125;/</code></td></tr>
            <tr><td><a href="/docs/cli/sync"><code>foundry sync</code></a></td><td>Reconcile manifest ↔ filesystem</td><td><code>.foundry/workspace.yml</code></td></tr>
            <tr><td><a href="/docs/cli/run"><code>foundry run</code></a></td><td>Run services locally (Services UI)</td><td>—</td></tr>
            <tr><td><a href="/docs/cli/db"><code>foundry db</code></a></td><td>Liquibase ops with auto SSH tunnels</td><td>—</td></tr>
            <tr><td><a href="/docs/cli/github"><code>foundry github</code></a></td><td>GitHub token + cross-repo discovery</td><td><code>.foundry/config.yml</code> (with <code>--save</code>)</td></tr>
            <tr><td><a href="/docs/cli/config"><code>foundry config</code></a></td><td>Show toolchain + project status</td><td>—</td></tr>
            <tr><td><a href="/docs/cli/alias"><code>foundry alias</code></a></td><td>Manage command aliases</td><td>shim binaries</td></tr>
          </tbody>
        </table>

        <h2>The shape of a Foundry project</h2>
        <p>
          Most commands operate on the current directory and expect a <code>foundry.json</code> at
          the root. <code>init</code> creates it; <code>sync</code> keeps the workspace map
          current; <code>run</code> reads the workspace to launch services; <code>generate</code>{" "}
          emits the in-repo CI/CD for a monorepo. <code>db</code>, <code>github</code>,{" "}
          <code>config</code>, and <code>alias</code> are utilities around that core.
        </p>
      </div>
    </WikiLayout>
  );
}
