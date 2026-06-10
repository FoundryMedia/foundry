import { WikiLayout } from "@/components/WikiLayout";

export default function SyncCommandPage(): React.ReactElement {
  return (
    <WikiLayout title="foundry sync" description="Reconcile the manifest with the filesystem.">
      <div className="prose-wiki max-w-3xl">
        <h1>foundry sync</h1>
        <p>
          Reconcile intent (the manifest) against reality (the filesystem) and write{" "}
          <code>.foundry/workspace.yml</code> — a path map telling Foundry where each declared
          service actually lives on disk, plus any drift.
        </p>

        <h2>Usage</h2>
        <pre><code>foundry sync [--dry-run]</code></pre>

        <h2>Options</h2>
        <table>
          <thead>
            <tr><th>Flag</th><th>Description</th></tr>
          </thead>
          <tbody>
            <tr><td><code>--dry-run</code></td><td>Show what would be resolved without writing <code>workspace.yml</code></td></tr>
          </tbody>
        </table>

        <h2>When to run it</h2>
        <ul>
          <li>After adding or removing services in <code>foundry.json</code></li>
          <li>After renaming a service directory</li>
          <li>After pulling changes that modify the project structure</li>
          <li>Any time you want to verify the workspace state</li>
        </ul>

        <h2>Drift</h2>
        <p>Sync reports three kinds of drift between the manifest and the filesystem:</p>
        <table>
          <thead>
            <tr><th>Kind</th><th>Meaning</th></tr>
          </thead>
          <tbody>
            <tr><td><strong>Undeclared</strong></td><td>A component directory exists on disk but is not in the manifest</td></tr>
            <tr><td><strong>Missing</strong></td><td>A service is declared in the manifest but has no directory on disk</td></tr>
            <tr><td><strong>Mismatch</strong></td><td>The detected runtime differs from the manifest{"'"}s declared <code>stack.framework</code></td></tr>
          </tbody>
        </table>

        <h2>workspace.yml</h2>
        <p>
          The output is intentionally minimal — service→path mappings plus drift. All other
          service metadata stays in <code>foundry.json</code>. <code>workspace.yml</code> is{" "}
          <strong>committed</strong> (team-shared); see{" "}
          <a href="/docs/config/workspace">.foundry/workspace.yml</a> for its structure.
        </p>
      </div>
    </WikiLayout>
  );
}
