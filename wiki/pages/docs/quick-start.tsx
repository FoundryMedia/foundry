import { WikiLayout } from "@/components/WikiLayout";

export default function QuickStartPage(): React.ReactElement {
  return (
    <WikiLayout title="Quick Start" description="Install Foundry, initialize a platform, and run it locally.">
      <div className="prose-wiki max-w-3xl">
        <h1>Quick Start</h1>
        <p>
          This walks through a first run end-to-end: install the CLI, initialize a platform,
          inspect what was generated, and start services locally. Every step reflects what the
          CLI actually does today.
        </p>

        <h2>1. Install</h2>
        <p>
          Install the Foundry CLI (see <a href="/docs/installation">Installation</a>) and verify:
        </p>
        <pre><code>foundry --help</code></pre>

        <h2>2. Initialize a platform</h2>
        <pre><code>foundry init</code></pre>
        <p>
          <code>foundry init</code> detects the directory state. In a fresh directory it launches
          an interactive wizard: it scans the filesystem for existing components, offers to add
          them to the manifest, and prompts for the cloud provider and IaC tool. It then writes:
        </p>
        <ul>
          <li><code>foundry.json</code> — the platform manifest (<code>schemaVersion 0.5.0</code>)</li>
          <li><code>.foundry/</code> — workspace config, including <code>workspace.yml</code></li>
          <li><code>.gitignore</code> — legacy blanket <code>.foundry/</code> ignores are removed (only <code>config.yml</code> is gitignored, via a nested <code>.foundry/.gitignore</code>)</li>
        </ul>
        <blockquote>
          Discovered backends are scaffolded with <code>deploy.strategy: "service"</code>,
          frontends with <code>"static"</code>, and packages get no <code>deploy</code> block.
          Adjust any of this in <code>foundry.json</code> afterward.
        </blockquote>

        <h2>3. Review the manifest</h2>
        <p>
          A v0.5.0+ service groups its concerns into structured blocks — <code>scope</code>,{" "}
          <code>stack</code>, and <code>deploy</code>:
        </p>
        <pre><code>{`{
  "$schema": "https://raw.githubusercontent.com/FoundryMedia/foundry/release/foundry.schema.json",
  "schemaVersion": "0.5.0",
  "name": "my-platform",
  "repository": "my-platform",
  "ci": { "iac": "opentofu", "iacDir": "ci/iac", "provider": "aws" },
  "services": {
    "api": {
      "scope": "internal",
      "stack": { "type": "backend", "framework": "spring-boot" },
      "deploy": { "strategy": "service" }
    },
    "web": {
      "scope": "public",
      "stack": { "type": "frontend", "framework": "nextjs" },
      "deploy": { "strategy": "static" }
    }
  }
}`}</code></pre>
        <p>
          See <a href="/docs/manifest/services">Services</a> for every field and{" "}
          <a href="/docs/manifest/deploy-strategies">Deploy Strategies</a> for the{" "}
          <code>strategy</code> enum.
        </p>

        <h2>4. Sync the workspace</h2>
        <p>
          After editing the manifest or moving directories, reconcile intent (manifest) against
          reality (filesystem):
        </p>
        <pre><code>foundry sync</code></pre>
        <p>
          This rewrites <code>.foundry/workspace.yml</code> — a path map of where each service
          actually lives — and reports drift (undeclared directories, missing services,
          framework mismatches). See <a href="/docs/cli/sync">foundry sync</a>.
        </p>

        <h2>5. Run locally</h2>
        <pre><code>foundry run dev</code></pre>
        <p>
          <code>run dev</code> launches every enabled service (and its sidecars) in a unified
          Services UI. Filter to a subset with <code>--filter</code>, and run database migrations
          first with <code>--migrate-db</code>:
        </p>
        <pre><code>{`foundry run dev --filter api,web
foundry run dev --migrate-db`}</code></pre>

        <h2>Multi-repo note</h2>
        <p>
          A service that lives in a different repository declares <code>repository</code>{" "}
          (<code>owner/repo</code>) and an optional <code>path</code>. Omit both and the service is
          treated as monorepo (<code>apps/&#123;type&#125;/&#123;name&#125;</code>). In practice the
          central multi-repo manifest lives in{" "}
          <a href="/docs/manifest/central">foundry-ops/platform.json</a>. See{" "}
          <a href="/docs/manifest/multi-repo">Multi-repo: repository &amp; path</a>.
        </p>
      </div>
    </WikiLayout>
  );
}
