import { WikiLayout } from "@/components/WikiLayout";

export default function InitCommandPage(): React.ReactElement {
  return (
    <WikiLayout title="foundry init" description="Initialize or refresh a Foundry platform.">
      <div className="prose-wiki max-w-3xl">
        <h1>foundry init</h1>
        <p>Initialize or refresh a Foundry platform in the current directory.</p>

        <h2>Usage</h2>
        <pre><code>foundry init [OPTIONS]</code></pre>

        <h2>Options</h2>
        <table>
          <thead>
            <tr><th>Flag</th><th>Description</th></tr>
          </thead>
          <tbody>
            <tr><td><code>--name, -n</code></td><td>Platform name (kebab-case). Defaults to the current directory name.</td></tr>
            <tr><td><code>--template, -t</code></td><td>Template to scaffold from. <code>ue5-game</code> turns the Unreal C++ project in the current folder into a Foundry game project (below). Any other value falls back to the default platform scaffold.</td></tr>
            <tr><td><code>--dry-run</code></td><td>Show what would be created without writing any files.</td></tr>
            <tr><td><code>--force, -f</code></td><td>Force regeneration of <code>.foundry/workspace.yml</code> even if it already exists.</td></tr>
            <tr><td><code>--publisher</code></td><td><em>(ue5-game)</em> Your publisher handle, written to <code>.foundry/config.yml</code>.</td></tr>
            <tr><td><code>--game</code></td><td><em>(ue5-game)</em> Game slug. Default: derived from the project name (<code>GooCrew</code> → <code>goo-crew</code>).</td></tr>
            <tr><td><code>--ue-root</code></td><td><em>(ue5-game)</em> Path to your UE 5.7 <strong>source</strong> build. Default: resolved from the <code>.uproject</code>&apos;s <code>EngineAssociation</code> (Windows registry).</td></tr>
            <tr><td><code>--plugin-version</code></td><td><em>(ue5-game)</em> FoundryFSDK release to install. Default: latest.</td></tr>
            <tr><td><code>--no-plugin</code></td><td><em>(ue5-game)</em> Skip the plugin download (offline). <code>FOUNDRY_FSDK_ZIP=&lt;path&gt;</code> installs from a local zip instead.</td></tr>
          </tbody>
        </table>

        <h2>The <code>ue5-game</code> template</h2>
        <p>
          Run it once from the folder that holds your <code>.uproject</code>, right after the
          editor&apos;s New Project wizard (Games → Blank → <strong>C++</strong>, on an engine built
          from source — a dedicated-server target needs one):
        </p>
        <pre><code>foundry init --template ue5-game --publisher my-handle</code></pre>
        <p>It performs the install steps of the FoundryFSDK README:</p>
        <ol>
          <li>Downloads the latest <a href="https://github.com/FoundryMedia/fsdk-unreal/releases">FoundryFSDK release</a> into <code>Plugins/FoundryFSDK/</code>.</li>
          <li>Adds the plugin entry to the <code>.uproject</code>.</li>
          <li>Writes <code>Source/&lt;Game&gt;Server.Target.cs</code> (the dedicated-server target).</li>
          <li>Adds <code>&quot;FoundryFSDK&quot;</code> to the game module&apos;s <code>PrivateDependencyModuleNames</code>.</li>
          <li>Pins the network protocol version in the primary game module (<code>FNetworkVersion::GetLocalNetworkVersionOverride</code>) — without it, clients and servers from different releases refuse each other.</li>
          <li>Writes <code>.foundry/config.yml</code> (<code>kind: game-publisher</code>, with the <code>build</code> and <code>server</code> blocks <code>foundry package</code> reads) and a self-contained <code>Docker/Dockerfile</code>.</li>
        </ol>
        <p>
          Every step is idempotent and nothing you already have is overwritten. The edits to
          wizard-generated files are anchored on the exact lines the UE 5.7 Blank template writes;
          a customized <code>Build.cs</code> or module <code>.cpp</code> is left alone and the step
          is printed under <em>By hand</em>. After it runs: regenerate project files, build
          <code>&lt;Game&gt;Editor</code>, <code>foundry login</code>, and register the game with{" "}
          <code>foundry games create --name &quot;…&quot;</code>.
        </p>

        <h2>Behavior</h2>
        <p><code>foundry init</code> detects the project state and acts accordingly:</p>

        <h3>Fresh directory (no foundry.json)</h3>
        <p>
          Runs the interactive wizard: scans the filesystem for components, lists what it found
          (with detected runtime), and offers to add them to the manifest. Discovered services are
          written with a <code>stack</code> block, an inferred <code>scope</code>, and a{" "}
          <code>deploy.strategy</code> (<code>service</code> for backends, <code>static</code> for
          frontends; packages get no <code>deploy</code> block). It then prompts for the cloud
          provider and IaC tool and writes <code>foundry.json</code> (<code>schemaVersion 0.5.0</code>),{" "}
          <code>.foundry/</code>, and updates <code>.gitignore</code>.
        </p>

        <h3>Existing manifest, no .foundry/ (upgrade)</h3>
        <p>
          Creates the <code>.foundry/</code> directory, generates <code>workspace.yml</code>, and
          updates the <code>.gitignore</code> — bringing a manifest-only project up to date.
        </p>

        <h3>Already initialized</h3>
        <p>
          Prints a project summary (name, schema version, services) and regenerates{" "}
          <code>.foundry/workspace.yml</code>. If it already exists, use <code>--force</code> (or
          run <a href="/docs/cli/sync"><code>foundry sync</code></a>) to rewrite it. Drift between
          the manifest and the filesystem is reported.
        </p>

        <h2>What it writes</h2>
        <pre><code>{`foundry.json            # the manifest (schemaVersion 0.5.0)
.foundry/
  workspace.yml         # committed — service path map + drift
  config.yml            # gitignored — personal config (only when created)
  .gitignore            # managed — ignores config.yml
.gitignore              # legacy blanket .foundry/ ignore is removed`}</code></pre>

        <h2>Prefix derivation</h2>
        <p>The platform prefix is derived from the first letter of each word in the name:</p>
        <pre><code>{`"My Platform"      → prefix "mp"
"My Cool Service"  → prefix "mcs"`}</code></pre>
        <p>Override it with a top-level <code>prefix</code> (minimum 2 characters).</p>

        <h2>Structure</h2>
        <p>
          A monorepo service lives at <code>apps/&#123;type&#125;/&#123;name&#125;</code> (or{" "}
          <code>packages/&#123;name&#125;</code>). The top-level <code>structure</code> block can
          rename the top directories (<code>appsDir</code>, <code>ciDir</code>,{" "}
          <code>packagesDir</code>). Services in other repos use{" "}
          <a href="/docs/manifest/multi-repo"><code>repository</code> / <code>path</code></a>{" "}
          instead.
        </p>
      </div>
    </WikiLayout>
  );
}
