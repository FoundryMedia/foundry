import { WikiLayout } from "@/components/WikiLayout";

export default function GitHubBlockPage(): React.ReactElement {
  return (
    <WikiLayout title="GitHub & Cross-Repo" description="The github block and cross-repo discovery.">
      <div className="prose-wiki max-w-3xl">
        <h1>GitHub &amp; Cross-Repo</h1>
        <p>
          The <code>github</code> block declares the GitHub organization and the conventions
          Foundry uses to discover the other repositories that make up a platform. It is the
          v0.4.0 replacement for the older <code>ecosystem</code> block.
        </p>

        <h2>The github block</h2>
        <table>
          <thead>
            <tr><th>Field</th><th>Description</th></tr>
          </thead>
          <tbody>
            <tr><td><code>organization</code></td><td>GitHub org login that owns the platform repos</td></tr>
            <tr><td><code>prefix</code></td><td>Repo naming prefix for satellite discovery (falls back to the platform <code>prefix</code>)</td></tr>
            <tr><td><code>apiLib</code></td><td>The API library repo — the contract-first source of API specs / generated code (optional)</td></tr>
          </tbody>
        </table>

        <h2>Discovery by naming convention</h2>
        <p>
          The primary platform repo is matched by its full name (the slugified platform name).
          Satellite repos are matched by the <code>&#123;prefix&#125;-*</code> pattern.
        </p>
        <pre><code>{`Platform name:  "Acme Cloud Platform"
Repository:     acme-cloud-platform      (primary, ★)
Prefix:         aap
Satellites:     acp-api-lib, acp-billing-service, ...`}</code></pre>
        <p>
          Test discovery against the live org with{" "}
          <a href="/docs/cli/github">foundry github discover</a>, which reads{" "}
          <code>github.organization</code> and the prefix from the manifest.
        </p>

        <blockquote>
          Note on the CLI: <code>foundry github discover</code> reads the new <code>github</code>{" "}
          block, while the older <code>foundry config discover</code> still reads the deprecated{" "}
          <code>ecosystem</code> block. Prefer <code>github</code> in new manifests.
        </blockquote>

        <h2>Example</h2>
        <pre><code>{`"github": {
  "organization": "FoundryMedia",
  "prefix": "foundry",
  "apiLib": {
    "repository": "acp-api-lib",
    "groupId": "com.example"
  }
}`}</code></pre>
      </div>
    </WikiLayout>
  );
}
