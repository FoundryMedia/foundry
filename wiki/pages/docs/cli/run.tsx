import { WikiLayout } from "@/components/WikiLayout";

export default function RunCommandPage(): React.ReactElement {
  return (
    <WikiLayout title="foundry run" description="Run platform services locally.">
      <div className="prose-wiki max-w-3xl">
        <h1>foundry run</h1>
        <p>
          Start Foundry services locally in a unified Services UI. <code>run</code> is a command
          group with two subcommands — <code>dev</code> and <code>build</code>.
        </p>

        <h2>Usage</h2>
        <pre><code>{`foundry run [-d|--debug] dev   [--filter NAMES] [--migrate-db]
foundry run [-d|--debug] build [--filter NAMES]`}</code></pre>
        <p>
          The <code>-d/--debug</code> flag is on the group and must appear before the subcommand
          (aliases hoist it automatically).
        </p>

        <h2>Subcommands</h2>
        <table>
          <thead>
            <tr><th>Subcommand</th><th>Description</th></tr>
          </thead>
          <tbody>
            <tr><td><code>dev</code></td><td>Run the platform in development mode with the Services UI</td></tr>
            <tr><td><code>build</code></td><td>Run the build command for all services</td></tr>
          </tbody>
        </table>

        <h2>Options</h2>
        <table>
          <thead>
            <tr><th>Flag</th><th>Applies to</th><th>Description</th></tr>
          </thead>
          <tbody>
            <tr><td><code>--filter</code></td><td><code>dev</code>, <code>build</code></td><td>Comma-separated service names to run (dependencies are included automatically)</td></tr>
            <tr><td><code>--migrate-db, -mdb</code></td><td><code>dev</code></td><td>Run Liquibase migrations before starting services that have a <code>database</code> block</td></tr>
            <tr><td><code>--debug, -d</code></td><td>group</td><td>Show debug output</td></tr>
          </tbody>
        </table>

        <h2>The Services UI</h2>
        <p>
          <code>run dev</code> discovers each enabled service from{" "}
          <a href="/docs/config/workspace">.foundry/workspace.yml</a> and launches it in a managed
          runner. Sidecars appear as sub-items nested under their parent service. Service
          launch behavior — ports, commands, env, health checks — is resolved from the manifest{"'"}s{" "}
          <code>run</code> block and detected framework conventions, not from a separate runtime
          file.
        </p>

        <h2>Examples</h2>
        <pre><code>{`foundry run dev                       # all enabled services
foundry run dev --filter api,web      # just these (plus their deps)
foundry run dev --migrate-db          # migrate databases first
foundry run build                     # build all services`}</code></pre>
      </div>
    </WikiLayout>
  );
}
