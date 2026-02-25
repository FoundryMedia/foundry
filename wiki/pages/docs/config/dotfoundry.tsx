import { WikiLayout } from "@/components/WikiLayout";

export default function DotFoundryPage(): React.ReactElement {
  return (
    <WikiLayout title=".foundry/ Directory" description="The .foundry configuration directory.">
      <div className="prose-wiki max-w-3xl">
        <h1>.foundry/ Directory</h1>

        <p>
          The <code>.foundry/</code> directory lives alongside <code>foundry.json</code>
          at the project root. It contains both <strong>committed</strong> and{" "}
          <strong>local-only</strong> files.
        </p>

        <h2>File Layout</h2>
        <pre><code>{`.foundry/
├── .gitignore      # Managed by Foundry — excludes local files
├── runtime.yml     # ✓ COMMITTED — team-shared launch config
├── state.yml       # ✗ gitignored — local drift snapshot
└── config.yml      # ✗ gitignored — personal preferences / tokens`}</code></pre>

        <h2>Commit Strategy</h2>
        <table>
          <thead>
            <tr><th>File</th><th>Committed?</th><th>Purpose</th></tr>
          </thead>
          <tbody>
            <tr><td><code>.gitignore</code></td><td>✓</td><td>Managed by Foundry — controls what is/isn{"'"}t tracked</td></tr>
            <tr><td><code>runtime.yml</code></td><td>✓</td><td>Ports, commands, health checks — shared with team</td></tr>
            <tr><td><code>state.yml</code></td><td>✗</td><td>Filesystem drift snapshot — machine-specific</td></tr>
            <tr><td><code>config.yml</code></td><td>✗</td><td>Personal overrides, tokens — never committed</td></tr>
          </tbody>
        </table>

        <h2>How It Works</h2>
        <p>
          Foundry does <strong>not</strong> add <code>.foundry/</code> to the root{" "}
          <code>.gitignore</code>. Instead, it manages a <strong>nested</strong>{" "}
          <code>.foundry/.gitignore</code> that selectively excludes only the
          local-only files:
        </p>
        <pre><code>{`# .foundry/.gitignore (managed by foundry init)
state.yml
config.yml`}</code></pre>

        <p>
          This means <code>runtime.yml</code> is naturally tracked by Git (it{"'"}s
          not excluded), while <code>state.yml</code> and <code>config.yml</code>
          stay local.
        </p>

        <h2>Legacy Migration</h2>
        <p>
          If your root <code>.gitignore</code> has a blanket <code>.foundry/</code>
          entry from an earlier Foundry version, <code>foundry init</code>{" "}
          automatically removes it and switches to the nested strategy.
        </p>
      </div>
    </WikiLayout>
  );
}
