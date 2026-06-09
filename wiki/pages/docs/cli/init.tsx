import { WikiLayout } from "@/components/WikiLayout";

export default function InitCommandPage(): React.ReactElement {
  return (
    <WikiLayout title="foundry init" description="Initialize or refresh a Foundry platform.">
      <div className="prose-wiki max-w-3xl">
        <h1>foundry init</h1>
        <p>Initialize or refresh a Foundry platform project.</p>

        <h2>Usage</h2>
        <pre><code>foundry init [OPTIONS]</code></pre>

        <h2>Options</h2>
        <table>
          <thead>
            <tr><th>Flag</th><th>Description</th></tr>
          </thead>
          <tbody>
            <tr><td><code>--regenerate-runtime</code></td><td>Force-regenerate <code>.foundry/runtime.yml</code> from the manifest</td></tr>
            <tr><td><code>--help</code></td><td>Show help message</td></tr>
          </tbody>
        </table>

        <h2>Behaviour</h2>
        <p>
          <code>foundry init</code> detects the current project state and takes the
          appropriate action:
        </p>

        <h3>Fresh Directory (no foundry.json)</h3>
        <p>
          Launches the interactive init wizard — name your platform, choose a template,
          define services. Generates <code>foundry.json</code> and <code>.foundry/</code>.
        </p>

        <h3>Existing Manifest (foundry.json exists)</h3>
        <p>
          If <code>.foundry/</code> already exists, reports the current state. Use{" "}
          <code>--regenerate-runtime</code> to rebuild <code>runtime.yml</code> from
          the manifest.
        </p>
        <p>
          If <code>.foundry/</code> is missing (legacy project), creates it and generates
          the runtime and state files.
        </p>

        <h2>Structure Enforcement</h2>
        <p>
          Init validates the directory layout matches the <code>structure</code> block
          in the manifest:
        </p>
        <pre><code>{`"structure": {
  "appsDir": "apps",
  "ciDir": "ci",
  "packagesDir": "packages"
}`}</code></pre>
        <p>
          Services must live under <code>apps/backend/</code> or <code>apps/frontend/</code>
          as declared by their <code>kind</code>.
        </p>

        <h2>Prefix Derivation</h2>
        <p>
          The platform prefix is derived from the first letter of each word in the name:
        </p>
        <pre><code>{`"An Average Platform" → prefix "aap"
"My Cool Service"     → prefix "mcs"`}</code></pre>
        <p>
          Users can override this in <code>ecosystem.prefix</code>, but it must be at
          least 2 characters.
        </p>
      </div>
    </WikiLayout>
  );
}
