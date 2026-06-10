import { WikiLayout } from "@/components/WikiLayout";

export default function ManifestOverviewPage(): React.ReactElement {
  return (
    <WikiLayout title="foundry.json" description="The Foundry platform manifest.">
      <div className="prose-wiki max-w-3xl">
        <h1>foundry.json — Platform Manifest</h1>

        <p>
          The manifest is the <strong>single source of truth</strong> for what a platform IS:
          its services, their stacks, how each one deploys, and which environments exist. It
          declares topology — not how to run things locally (that is resolved into{" "}
          <a href="/docs/config/workspace">.foundry/workspace.yml</a>).
        </p>

        <blockquote>
          In a monorepo the manifest is the repo{"'"}s own <code>foundry.json</code>. In a
          multi-repo platform the authoritative manifest is{" "}
          <a href="/docs/manifest/central">foundry-ops/platform.json</a>, and service repos carry
          no manifest of their own.
        </blockquote>

        <h2>Schema version</h2>
        <p>
          The manifest spec is at <strong>v0.7.0</strong>. <code>foundry init</code> currently
          scaffolds a <code>schemaVersion 0.5.0</code> manifest; the v0.7.0 additions
          (per-service <code>repository</code>, <code>path</code>, and <code>environments</code>)
          are additive and back-compatible — a 0.5.0 manifest is still valid. The{" "}
          <a href="/docs/manifest/schema">Schema Reference</a> renders the live schema.
        </p>

        <h2>Top-level fields</h2>
        <table>
          <thead>
            <tr><th>Field</th><th>Type</th><th>Required</th><th>Description</th></tr>
          </thead>
          <tbody>
            <tr><td><code>$schema</code></td><td>string</td><td>✓</td><td>JSON Schema URI for validation</td></tr>
            <tr><td><code>schemaVersion</code></td><td>string</td><td>✓</td><td>Manifest spec version (semver, e.g. <code>0.7.0</code>)</td></tr>
            <tr><td><code>name</code></td><td>string</td><td>✓</td><td>Human-readable platform name</td></tr>
            <tr><td><code>repository</code></td><td>string</td><td>✓</td><td>Root repository folder name (kebab-case)</td></tr>
            <tr><td><code>ci</code></td><td>object</td><td>✓</td><td>IaC tool + provider + <a href="/docs/manifest/environments">environments</a> (requires <code>iac</code>, <code>provider</code>)</td></tr>
            <tr><td><code>services</code></td><td>object</td><td>✓</td><td><a href="/docs/manifest/services">Service declarations</a> (keyed by name)</td></tr>
            <tr><td><code>prefix</code></td><td>string</td><td></td><td>Short prefix for AWS resource naming + satellite discovery (auto-derived from <code>name</code>)</td></tr>
            <tr><td><code>structure</code></td><td>object</td><td></td><td>Directory overrides (<code>appsDir</code>, <code>ciDir</code>, <code>packagesDir</code>)</td></tr>
            <tr><td><code>github</code></td><td>object</td><td></td><td><a href="/docs/manifest/github">GitHub org + cross-repo</a> config (replaces <code>ecosystem</code>)</td></tr>
            <tr><td><code>foundry</code></td><td>object</td><td></td><td>CLI metadata (minimum version)</td></tr>
            <tr><td><code>template</code></td><td>object</td><td></td><td>Which template generated this manifest (informational)</td></tr>
          </tbody>
        </table>

        <h2>Deprecated blocks</h2>
        <ul>
          <li><code>ecosystem</code> — replaced by <code>github</code> in v0.4.0. See <a href="/docs/manifest/github">GitHub &amp; Cross-Repo</a>.</li>
          <li><code>databases</code> (top-level) — declare a service{"'"}s database inline under the service instead.</li>
        </ul>

        <h2>Name → repository → prefix</h2>
        <p>The platform name drives two derived values (both overridable):</p>
        <pre><code>{`name: "An Average Platform"
  → repository: "an-average-platform"   (slugified)
  → prefix:     "aap"                   (first letter of each word, min 2 chars)`}</code></pre>
        <p>
          The prefix is used for AWS resource naming and for discovering satellite repos by the{" "}
          <code>&#123;prefix&#125;-*</code> pattern.
        </p>
      </div>
    </WikiLayout>
  );
}
