import { WikiLayout } from "@/components/WikiLayout";

export default function DotFoundryPage(): React.ReactElement {
  return (
    <WikiLayout title=".foundry/ Directory" description="The .foundry configuration directory.">
      <div className="prose-wiki max-w-3xl">
        <h1>.foundry/ Directory</h1>
        <p>
          The <code>.foundry/</code> directory lives alongside <code>foundry.json</code> at the
          project root. It holds one committed file and the local-only files, with the split
          enforced by a nested <code>.foundry/.gitignore</code> that Foundry writes.
        </p>

        <h2>File layout</h2>
        <pre><code>{`.foundry/
├── .gitignore            # Managed by Foundry — ignores config.yml
├── workspace.yml         # ✓ COMMITTED — service path map + drift
├── config.yml            # ✗ gitignored — personal config / credential pointers
└── config.defaults.yml   # optional, committed — shared defaults merged under config.yml`}</code></pre>

        <h2>Commit strategy</h2>
        <table>
          <thead>
            <tr><th>File</th><th>Committed?</th><th>Purpose</th></tr>
          </thead>
          <tbody>
            <tr><td><code>.gitignore</code></td><td>✓</td><td>Managed by Foundry — ignores <code>config.yml</code></td></tr>
            <tr><td><a href="/docs/config/workspace"><code>workspace.yml</code></a></td><td>✓</td><td>Resolved service→path map and drift; written by <code>foundry sync</code></td></tr>
            <tr><td><a href="/docs/config/local"><code>config.yml</code></a></td><td>✗</td><td>Personal preferences, tokens, SSH tunnels — never committed</td></tr>
            <tr><td><code>config.defaults.yml</code></td><td>✓ (optional)</td><td>Team-shared defaults, deep-merged <em>under</em> <code>config.yml</code></td></tr>
          </tbody>
        </table>

        <h2>How the gitignore works</h2>
        <p>
          Foundry does <strong>not</strong> add <code>.foundry/</code> to the root{" "}
          <code>.gitignore</code>. Instead it writes a nested <code>.foundry/.gitignore</code> that
          ignores only the local file:
        </p>
        <pre><code>{`# .foundry/.gitignore — managed by foundry
# Only workspace.yml is committed.
config.yml`}</code></pre>
        <p>
          So <code>workspace.yml</code> (and an optional <code>config.defaults.yml</code>) are
          tracked naturally, while <code>config.yml</code> stays local even if you{" "}
          <code>git add .</code>.
        </p>

        <h2>Legacy migration</h2>
        <p>
          If your root <code>.gitignore</code> still has a blanket <code>.foundry/</code> entry from
          an older Foundry version, <code>foundry init</code> removes it and switches to the nested
          strategy so <code>workspace.yml</code> is committed.
        </p>
      </div>
    </WikiLayout>
  );
}
