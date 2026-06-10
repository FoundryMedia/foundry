import { WikiLayout } from "@/components/WikiLayout";

export default function InitCommandPage(): React.ReactElement {
  return (
    <WikiLayout title="foundry init" description="Initialize or refresh a Foundry platform.">
      <div className="prose-wiki max-w-3xl">
        <h1>foundry init</h1>
        <p>Initialize or refresh a Foundry platform in the current directory.</p>

        <h2>Usage</h2>
        <pre><code>foundry init [OPTIONS]</code></pre>

        <h2>Options</h2>
        <table>
          <thead>
            <tr><th>Flag</th><th>Description</th></tr>
          </thead>
          <tbody>
            <tr><td><code>--name, -n</code></td><td>Platform name (kebab-case). Defaults to the current directory name.</td></tr>
            <tr><td><code>--template, -t</code></td><td>Template to scaffold from. <em>Not yet implemented</em> — any value other than <code>default</code> falls back to the default scaffold.</td></tr>
            <tr><td><code>--dry-run</code></td><td>Show what would be created without writing any files.</td></tr>
            <tr><td><code>--force, -f</code></td><td>Force regeneration of <code>.foundry/workspace.yml</code> even if it already exists.</td></tr>
          </tbody>
        </table>

        <h2>Behavior</h2>
        <p><code>foundry init</code> detects the project state and acts accordingly:</p>

        <h3>Fresh directory (no foundry.json)</h3>
        <p>
          Runs the interactive wizard: scans the filesystem for components, lists what it found
          (with detected runtime), and offers to add them to the manifest. Discovered services are
          written with a <code>stack</code> block, an inferred <code>scope</code>, and a{" "}
          <code>deploy.strategy</code> (<code>service</code> for backends, <code>static</code> for
          frontends; packages get no <code>deploy</code> block). It then prompts for the cloud
          provider and IaC tool and writes <code>foundry.json</code> (<code>schemaVersion 0.5.0</code>),{" "}
          <code>.foundry/</code>, and updates <code>.gitignore</code>.
        </p>

        <h3>Existing manifest, no .foundry/ (upgrade)</h3>
        <p>
          Creates the <code>.foundry/</code> directory, generates <code>workspace.yml</code>, and
          updates the <code>.gitignore</code> — bringing a manifest-only project up to date.
        </p>

        <h3>Already initialized</h3>
        <p>
          Prints a project summary (name, schema version, services) and regenerates{" "}
          <code>.foundry/workspace.yml</code>. If it already exists, use <code>--force</code> (or
          run <a href="/docs/cli/sync"><code>foundry sync</code></a>) to rewrite it. Drift between
          the manifest and the filesystem is reported.
        </p>

        <h2>What it writes</h2>
        <pre><code>{`foundry.json            # the manifest (schemaVersion 0.5.0)
.foundry/
  workspace.yml         # committed — service path map + drift
  config.yml            # gitignored — personal config (only when created)
  .gitignore            # managed — ignores config.yml
.gitignore              # legacy blanket .foundry/ ignore is removed`}</code></pre>

        <h2>Prefix derivation</h2>
        <p>The platform prefix is derived from the first letter of each word in the name:</p>
        <pre><code>{`"Acme Cloud Platform" → prefix "aap"
"My Cool Service"     → prefix "mcs"`}</code></pre>
        <p>Override it with a top-level <code>prefix</code> (minimum 2 characters).</p>

        <h2>Structure</h2>
        <p>
          A monorepo service lives at <code>apps/&#123;type&#125;/&#123;name&#125;</code> (or{" "}
          <code>packages/&#123;name&#125;</code>). The top-level <code>structure</code> block can
          rename the top directories (<code>appsDir</code>, <code>ciDir</code>,{" "}
          <code>packagesDir</code>). Services in other repos use{" "}
          <a href="/docs/manifest/multi-repo"><code>repository</code> / <code>path</code></a>{" "}
          instead.
        </p>
      </div>
    </WikiLayout>
  );
}
