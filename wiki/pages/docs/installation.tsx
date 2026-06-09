import { WikiLayout } from "@/components/WikiLayout";

export default function InstallationPage(): React.ReactElement {
  return (
    <WikiLayout title="Installation" description="Install the Foundry CLI.">
      <div className="prose-wiki max-w-3xl">
        <h1>Installation</h1>

        <h2>Windows</h2>
        <p>Download the latest installer from GitHub Releases:</p>
        <pre><code>https://github.com/FoundryMedia/foundry/releases</code></pre>
        <p>
          Run the <code>.exe</code> installer. It adds <code>foundry</code> to your PATH
          automatically.
        </p>

        <h2>Verify</h2>
        <pre><code>foundry --help</code></pre>
        <p>You should see the Foundry banner and a list of available commands.</p>

        <h2>Prerequisites</h2>
        <ul>
          <li><strong>Python 3.9+</strong> — required if building from source</li>
          <li><strong>Git</strong> — for version control and GitHub integration</li>
          <li><strong>GitHub CLI</strong> (optional) — for automatic token resolution via <code>gh auth login</code></li>
        </ul>

        <h2>Building from Source</h2>
        <pre><code>{`cd foundry/cli
pip install -e .
foundry --help`}</code></pre>
      </div>
    </WikiLayout>
  );
}
