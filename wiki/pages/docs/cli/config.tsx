import { WikiLayout } from "@/components/WikiLayout";

export default function ConfigCommandPage(): React.ReactElement {
  return (
    <WikiLayout title="foundry config" description="Show toolchain and project status.">
      <div className="prose-wiki max-w-3xl">
        <h1>foundry config</h1>
        <p>
          Display the status of the external tools Foundry orchestrates and the current project.
          Foundry never stores credentials — it reads whatever you have configured locally
          (<code>aws configure</code>, <code>gh auth login</code>, env vars).
        </p>

        <h2>Usage</h2>
        <pre><code>{`foundry config [--show]      # toolchain + project status (default)
foundry config discover      # discover platform repos in a GitHub org`}</code></pre>

        <h2>What --show reports</h2>
        <table>
          <thead>
            <tr><th>Section</th><th>Shows</th></tr>
          </thead>
          <tbody>
            <tr><td><strong>AWS CLI</strong></td><td>Whether authenticated, account ID, caller identity</td></tr>
            <tr><td><strong>GitHub CLI</strong></td><td>Whether authenticated, the source, and user</td></tr>
            <tr><td><strong>OpenTofu</strong></td><td>Installed version (optional tool)</td></tr>
            <tr><td><strong>Project</strong></td><td>Manifest name, prefix, and enabled environments (if a <code>foundry.json</code> is present)</td></tr>
          </tbody>
        </table>

        <h2>config discover</h2>
        <p>
          Lists platform repos in a GitHub org, matching the primary repo by name and satellites
          by <code>&#123;prefix&#125;-*</code>. Pass <code>--org</code> and <code>--prefix</code>,
          or run inside a project to read them from the manifest.
        </p>
        <blockquote>
          <code>config discover</code> reads the deprecated <code>ecosystem</code> block, whereas{" "}
          <a href="/docs/cli/github"><code>foundry github discover</code></a> reads the current{" "}
          <code>github</code> block. Prefer the latter.
        </blockquote>
      </div>
    </WikiLayout>
  );
}
