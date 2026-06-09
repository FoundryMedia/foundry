import { WikiLayout } from "@/components/WikiLayout";

export default function ManifestOverviewPage(): React.ReactElement {
  return (
    <WikiLayout title="foundry.json" description="The Foundry platform manifest.">
      <div className="prose-wiki max-w-3xl">
        <h1>foundry.json — Platform Manifest</h1>

        <p>
          The manifest is the <strong>single source of truth</strong> for what
          your platform IS. It declares topology — services, databases, ecosystem
          — not how to run them.
        </p>

        <blockquote>
          Only the primary platform repository has a <code>foundry.json</code>.
          Satellite repos are referenced, not duplicated.
        </blockquote>

        <h2>Top-Level Fields</h2>
        <table>
          <thead>
            <tr><th>Field</th><th>Type</th><th>Required</th><th>Description</th></tr>
          </thead>
          <tbody>
            <tr><td><code>$schema</code></td><td>string</td><td>✓</td><td>JSON Schema URI for validation</td></tr>
            <tr><td><code>schemaVersion</code></td><td>string</td><td>✓</td><td>Manifest spec version (e.g. <code>0.3.0</code>)</td></tr>
            <tr><td><code>name</code></td><td>string</td><td>✓</td><td>Human-readable platform name</td></tr>
            <tr><td><code>repository</code></td><td>string</td><td>✓</td><td>Repository slug (kebab-case)</td></tr>
            <tr><td><code>foundry</code></td><td>object</td><td></td><td>CLI metadata (min version)</td></tr>
            <tr><td><code>template</code></td><td>object</td><td></td><td>Which template generated this manifest</td></tr>
            <tr><td><code>structure</code></td><td>object</td><td></td><td>Directory layout (<code>appsDir</code>, <code>ciDir</code>, <code>packagesDir</code>)</td></tr>
            <tr><td><code>ecosystem</code></td><td>object</td><td></td><td>GitHub org, prefix, related repos</td></tr>
            <tr><td><code>ci</code></td><td>object</td><td>✓</td><td>CI/CD provider and IaC tool</td></tr>
            <tr><td><code>databases</code></td><td>object</td><td></td><td>Database schemas and changelogs</td></tr>
            <tr><td><code>services</code></td><td>object</td><td>✓</td><td>Service definitions</td></tr>
          </tbody>
        </table>

        <h2>Name → Repository → Prefix</h2>
        <p>
          The platform name drives two derived values:
        </p>
        <pre><code>{`name: "An Average Platform"
  → repository: "an-average-platform"   (slugified)
  → prefix:     "aap"                   (first letters)`}</code></pre>
        <p>
          Both can be overridden explicitly, but the defaults are derived from
          the name. The prefix must be at least 2 characters.
        </p>

        <h2>Manifest vs Runtime</h2>
        <p>
          In schema v0.3.0+, services are <strong>lean</strong>. The manifest
          declares <code>kind</code>, <code>type</code>, <code>role</code>,{" "}
          <code>database</code>, and <code>apiLibModule</code>. Everything
          operational — ports, commands, env vars, health checks — lives in{" "}
          <code>.foundry/runtime.yml</code>.
        </p>
      </div>
    </WikiLayout>
  );
}
