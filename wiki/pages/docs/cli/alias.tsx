import { WikiLayout } from "@/components/WikiLayout";

export default function AliasCommandPage(): React.ReactElement {
  return (
    <WikiLayout title="foundry alias" description="Manage Foundry command aliases.">
      <div className="prose-wiki max-w-3xl">
        <h1>foundry alias</h1>
        <p>
          Create short aliases for Foundry commands. Each alias writes a shim binary so you can
          invoke it directly from your shell.
        </p>

        <h2>Subcommands</h2>
        <table>
          <thead>
            <tr><th>Subcommand</th><th>Description</th></tr>
          </thead>
          <tbody>
            <tr><td><code>list</code></td><td>List configured aliases</td></tr>
            <tr><td><code>set &lt;name&gt; &lt;command…&gt;</code></td><td>Create or update an alias and write its shim</td></tr>
            <tr><td><code>remove &lt;name&gt;</code></td><td>Remove an alias and its shim</td></tr>
          </tbody>
        </table>

        <h2>Options</h2>
        <table>
          <thead>
            <tr><th>Flag</th><th>Description</th></tr>
          </thead>
          <tbody>
            <tr><td><code>--bin-dir</code></td><td>Where to write (or find) the shim. Defaults to the packaged dir, the env Scripts dir, or <code>LOCALAPPDATA</code>.</td></tr>
          </tbody>
        </table>

        <h2>Examples</h2>
        <pre><code>{`foundry alias set fr run          # 'fr' → 'foundry run'
foundry alias set fd run dev      # 'fd' → 'foundry run dev'
foundry alias list
foundry alias remove fd`}</code></pre>
      </div>
    </WikiLayout>
  );
}
