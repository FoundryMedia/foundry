import { WikiLayout } from "@/components/WikiLayout";

export default function GitHubCommandPage(): React.ReactElement {
  return (
    <WikiLayout title="foundry github" description="GitHub integration commands.">
      <div className="prose-wiki max-w-3xl">
        <h1>foundry github</h1>
        <p>Manage GitHub integration for cross-repository discovery.</p>

        <h2>Subcommands</h2>

        <h3>foundry github auth</h3>
        <pre><code>{`foundry github auth [--token TOKEN] [--save/--no-save]`}</code></pre>
        <p>Configure or verify a GitHub personal access token.</p>

        <p><strong>Token resolution order:</strong></p>
        <ol>
          <li><code>--token</code> flag</li>
          <li><code>FOUNDRY_GITHUB_TOKEN</code> environment variable</li>
          <li><code>GITHUB_TOKEN</code> environment variable</li>
          <li><code>gh auth token</code> (GitHub CLI)</li>
          <li><code>.foundry/config.yml</code> → <code>github.token</code></li>
        </ol>

        <table>
          <thead>
            <tr><th>Flag</th><th>Description</th></tr>
          </thead>
          <tbody>
            <tr><td><code>--token, -t</code></td><td>GitHub personal access token</td></tr>
            <tr><td><code>--save</code></td><td>Save the token to <code>.foundry/config.yml</code> (gitignored)</td></tr>
          </tbody>
        </table>

        <h3>foundry github discover</h3>
        <pre><code>{`foundry github discover [--org ORG] [--prefix PREFIX]`}</code></pre>
        <p>Discover platform repositories in a GitHub organization.</p>
        <p>
          When run inside a project with <code>foundry.json</code>, reads the
          organization (from the <a href="/docs/manifest/github"><code>github</code> block</a>),
          prefix, and repository name from the manifest automatically.
        </p>
        <p>
          The primary platform repo is matched by its full name (derived from
          the platform name as a slug). Satellite repos are matched by{" "}
          <code>{"{prefix}-*"}</code>.
        </p>

        <h2>Naming Convention</h2>
        <pre><code>{`Platform name:  "Acme Cloud Platform"
Repository:     acme-cloud-platform      (primary, ★)
Prefix:         aap
Satellites:     acp-api-lib, acp-billing-service, ...`}</code></pre>

        <h2>Token Security</h2>
        <p>
          Tokens are <strong>never</strong> stored in committed files. The{" "}
          <code>.foundry/config.yml</code> file is excluded by the nested{" "}
          <code>.foundry/.gitignore</code>.
        </p>
      </div>
    </WikiLayout>
  );
}
