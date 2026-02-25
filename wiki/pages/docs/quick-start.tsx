import { WikiLayout } from "@/components/WikiLayout";

export default function QuickStartPage(): React.ReactElement {
  return (
    <WikiLayout title="Quick Start" description="Get a Foundry platform running in 5 minutes.">
      <div className="prose-wiki max-w-3xl">
        <h1>Quick Start</h1>

        <h2>1. Install Foundry</h2>
        <p>See the <a href="/docs/installation">Installation</a> page.</p>

        <h2>2. Initialize a Platform</h2>
        <pre><code>{`mkdir my-platform && cd my-platform
foundry init`}</code></pre>
        <p>
          The init wizard walks you through naming your platform, choosing a template,
          and defining your initial services. It generates:
        </p>
        <ul>
          <li><code>foundry.json</code> — the platform manifest (committed)</li>
          <li><code>.foundry/runtime.yml</code> — launch config (committed, team-shared)</li>
          <li><code>.foundry/.gitignore</code> — keeps local state out of VCS</li>
        </ul>

        <h2>3. Review the Manifest</h2>
        <p>
          Open <code>foundry.json</code>. The <code>services</code> block declares
          your platform topology — each service has a <code>kind</code>, <code>type</code>,
          and <code>role</code>:
        </p>
        <pre><code>{`{
  "services": {
    "platform-microlith": {
      "kind": "backend",
      "type": "spring-boot",
      "role": "microlith"
    },
    "hub-frontend": {
      "kind": "frontend",
      "type": "nextjs",
      "role": "hub"
    }
  }
}`}</code></pre>

        <h2>4. Configure GitHub Integration</h2>
        <pre><code>{`foundry github auth
foundry github discover`}</code></pre>
        <p>
          Foundry discovers platform repositories by naming convention:
          the primary repo matches the platform name, satellites match <code>{"{prefix}-*"}</code>.
        </p>

        <h2>5. Run Your Platform</h2>
        <pre><code>foundry run</code></pre>
        <p>
          Launches all enabled services using the ports and commands from{" "}
          <code>.foundry/runtime.yml</code>.
        </p>
      </div>
    </WikiLayout>
  );
}
