import { WikiLayout } from "@/components/WikiLayout";

export default function WorkspaceConfigPage(): React.ReactElement {
  return (
    <WikiLayout title="workspace.yml" description="The committed workspace path map.">
      <div className="prose-wiki max-w-3xl">
        <h1>.foundry/workspace.yml</h1>
        <p>
          <code>workspace.yml</code> is the one <strong>committed</strong> file in{" "}
          <code>.foundry/</code>. It is the resolved path map — where each declared service
          actually lives on disk — plus any drift. It is written by{" "}
          <a href="/docs/cli/sync"><code>foundry sync</code></a> (and by{" "}
          <a href="/docs/cli/init"><code>foundry init</code></a>), and is intentionally minimal:
          all other service metadata stays in <code>foundry.json</code>.
        </p>

        <h2>Structure</h2>
        <pre><code>{`generatedAt: "2026-01-01T00:00:00+00:00"
schemaVersion: "0.5.0"
services:
  api: apps/backend/api          # resolved path on disk
  web: apps/frontend/web
  legacy-worker: null            # declared but not found on disk
drift:
  undeclared:                    # on disk, not in the manifest
    scratch-tool:
      kind: backend
      path: apps/backend/scratch-tool
      detectedRuntime: uvicorn
  missing:                       # in the manifest, not on disk
    - legacy-worker
  mismatches:                    # declared framework != detected runtime
    api:
      - "framework: manifest=spring-boot, detected=uvicorn"`}</code></pre>

        <h2>Fields</h2>
        <table>
          <thead>
            <tr><th>Field</th><th>Meaning</th></tr>
          </thead>
          <tbody>
            <tr><td><code>generatedAt</code></td><td>UTC timestamp of the last sync</td></tr>
            <tr><td><code>schemaVersion</code></td><td>The manifest schema version at sync time</td></tr>
            <tr><td><code>services</code></td><td>Map of service name → resolved repo-relative path, or <code>null</code> if not found</td></tr>
            <tr><td><code>drift</code></td><td>Present only when there is drift — <code>undeclared</code>, <code>missing</code>, <code>mismatches</code></td></tr>
          </tbody>
        </table>

        <h2>Why it{"'"}s committed</h2>
        <p>
          Sharing the resolved path map means every teammate{"'"}s tooling agrees on where services
          live, and drift is visible in code review. Local-only, per-developer settings belong in{" "}
          <a href="/docs/config/local"><code>config.yml</code></a> instead, which is gitignored.
        </p>

        <blockquote>
          Note: launch behavior (ports, commands, env, health checks) is not stored here — it is
          resolved at <a href="/docs/cli/run"><code>foundry run</code></a> time from the manifest{"'"}s{" "}
          <code>run</code> block and framework detection.
        </blockquote>
      </div>
    </WikiLayout>
  );
}
