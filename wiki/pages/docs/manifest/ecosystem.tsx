import { WikiLayout } from "@/components/WikiLayout";

export default function EcosystemPage(): React.ReactElement {
  return (
    <WikiLayout title="Ecosystem" description="Cross-repo discovery and naming conventions.">
      <div className="prose-wiki max-w-3xl">
        <h1>Ecosystem & Cross-Repo Discovery</h1>

        <h2>One Manifest — One Source of Truth</h2>
        <p>
          Only the <strong>primary platform repository</strong> has a <code>foundry.json</code>.
          Satellite repos (API libraries, extracted services, docs) are referenced
          in the <code>ecosystem</code> block — they never get their own manifest.
        </p>

        <h2>Naming Convention</h2>
        <p>
          Cross-repo discovery is purely convention-based. Given a platform name,
          Foundry derives two values:
        </p>
        <pre><code>{`name: "Acme Cloud Platform"
  → repository: "acme-cloud-platform"  (slug — all lowercase, spaces → hyphens)
  → prefix:     "aap"                  (first letter of each word)`}</code></pre>

        <p>Foundry then discovers repos in the GitHub org:</p>
        <ul>
          <li><strong>Primary repo</strong>: exact match on repository name (<code>acme-cloud-platform</code>)</li>
          <li><strong>Satellite repos</strong>: name starts with <code>{"{prefix}-"}</code> (<code>acp-api-lib</code>, <code>acp-billing-service</code>)</li>
        </ul>

        <h2>Ecosystem Block</h2>
        <pre><code>{`"ecosystem": {
  "organization": "FoundryMedia",
  "prefix": "aap",
  "repositories": {
    "api-lib": {
      "repository": "acp-api-lib",
      "relationship": "contracts"
    }
  },
  "apiLib": {
    "repository": "acp-api-lib",
    "packageRegistry": "github-packages",
    "groupId": "com.aap",
    "modules": { ... }
  }
}`}</code></pre>

        <table>
          <thead>
            <tr><th>Field</th><th>Description</th></tr>
          </thead>
          <tbody>
            <tr><td><code>organization</code></td><td>GitHub org that owns all platform repos</td></tr>
            <tr><td><code>prefix</code></td><td>Short prefix for satellite repo naming (auto-derived if omitted)</td></tr>
            <tr><td><code>repositories</code></td><td>Known satellite repos and their relationships</td></tr>
            <tr><td><code>apiLib</code></td><td>API library config (Maven coordinates, modules, versions)</td></tr>
          </tbody>
        </table>

        <h2>Repository Relationships</h2>
        <table>
          <thead>
            <tr><th>Relationship</th><th>Meaning</th></tr>
          </thead>
          <tbody>
            <tr><td><code>contracts</code></td><td>API specs, generated code, shared models</td></tr>
            <tr><td><code>extracted-service</code></td><td>Service extracted from the primary repo</td></tr>
            <tr><td><code>package</code></td><td>Shared library / utility package</td></tr>
            <tr><td><code>docs</code></td><td>Documentation repository</td></tr>
            <tr><td><code>infra</code></td><td>Infrastructure / Terraform / deployment</td></tr>
            <tr><td><code>other</code></td><td>Anything else</td></tr>
          </tbody>
        </table>

        <h2>GitHub Integration</h2>
        <p>
          Use <code>foundry github discover</code> to test discovery. Foundry calls
          the GitHub REST API to list repos in the org and filter by the naming convention.
        </p>
        <p>
          Tokens are resolved from environment variables, the GitHub CLI, or{" "}
          <code>.foundry/config.yml</code> — never committed. See{" "}
          <a href="/docs/cli/github">foundry github</a> for details.
        </p>
      </div>
    </WikiLayout>
  );
}
