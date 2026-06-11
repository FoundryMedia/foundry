import { WikiLayout } from "@/components/WikiLayout";

export default function GenerateCommandPage(): React.ReactElement {
  return (
    <WikiLayout title="foundry generate" description="Generate pipeline, deploy scripts, and tfvars.">
      <div className="prose-wiki max-w-3xl">
        <h1>foundry generate</h1>
        <p>
          Read <code>foundry.json</code>, resolve each service{"'"}s deployment profile via the
          convention engine, and emit the in-repo CI/CD artifacts. Run with no subcommand to
          generate all three.
        </p>

        <h2>Usage</h2>
        <pre><code>{`foundry generate [OPTIONS]            # runs pipeline + scripts + tfvars
foundry generate pipeline
foundry generate scripts
foundry generate tfvars
foundry generate callers                # multi-repo: thin callers from platform.json`}</code></pre>

        <h2>Options</h2>
        <table>
          <thead>
            <tr><th>Flag</th><th>Description</th></tr>
          </thead>
          <tbody>
            <tr><td><code>--dir, -d</code></td><td>Project root containing <code>foundry.json</code> (default: cwd)</td></tr>
            <tr><td><code>--clean</code></td><td>Wipe the target directory before generating (fresh install)</td></tr>
          </tbody>
        </table>

        <h2>Subcommands</h2>
        <table>
          <thead>
            <tr><th>Subcommand</th><th>Generates</th></tr>
          </thead>
          <tbody>
            <tr><td><code>pipeline</code></td><td><code>.github/workflows/deploy.yml</code> — a GitHub Actions workflow</td></tr>
            <tr><td><code>scripts</code></td><td><code>ci/scripts/</code> — a self-contained Python deploy engine suite (change detection, IaC, ECS, S3-static, database engines)</td></tr>
            <tr><td><code>tfvars</code></td><td><code>ci/iac/&#123;env&#125;/&#123;env&#125;.auto.tfvars</code> — one per enabled environment</td></tr>
            <tr><td><code>callers</code></td><td>Multi-repo: per-service thin-caller workflows from <code>platform.json</code> (printed, or written with <code>--out</code>)</td></tr>
          </tbody>
        </table>

        <h2>The generated scripts are self-contained</h2>
        <p>
          <code>ci/scripts/</code> does not depend on the Foundry CLI at runtime — it reads{" "}
          <code>foundry.json</code> directly and embeds the convention engine. This is the
          <strong> monorepo</strong> deploy model: the pipeline and scripts live in the same repo
          as the manifest and run there.
        </p>

        <h2>Multi-repo: generate callers</h2>
        <p>
          <code>foundry generate callers</code> reads the central{" "}
          <a href="/docs/manifest/central"><code>platform.json</code></a> and emits each
          orchestrated service{"'"}s <a href="/docs/deploy/thin-caller">thin-caller</a> workflow —
          the small file a service repo carries that names the service and delegates to the ops
          repo{"'"}s reusable <code>deploy.yml</code>. Only <code>static</code> and{" "}
          <code>service</code> strategies get a caller; <code>desktop</code> /{" "}
          <code>game-publisher</code> ship via their own release flows.
        </p>
        <table>
          <thead><tr><th>Flag</th><th>Description</th></tr></thead>
          <tbody>
            <tr><td><code>--manifest</code></td><td>Central manifest (default: <code>platform.json</code>, else <code>foundry.json</code>)</td></tr>
            <tr><td><code>--out</code></td><td>Write to <code>&lt;out&gt;/&lt;repo&gt;/.github/workflows/</code>; default prints to stdout</td></tr>
            <tr><td><code>--env</code></td><td>Target environment (default <code>prod</code>) — selects the per-service branch</td></tr>
            <tr><td><code>--ref</code></td><td>The ops repo ref the callers pin (default <code>main</code>)</td></tr>
          </tbody>
        </table>
        <p>
          A repo with one orchestrated service gets <code>deploy.yml</code>; a repo with several
          gets <code>deploy-&lt;service&gt;.yml</code>. The reusable workflow reference is{" "}
          <strong>derived from the manifest</strong>{" "}
          (<code>&lt;org&gt;/&lt;ops-repo&gt;/.github/workflows/deploy.yml@&lt;ref&gt;</code> — from{" "}
          <code>github.organization</code> plus the manifest{"'"}s own <code>repository</code>), so
          nothing is hard-coded to a single org. The bare <code>foundry generate</code> still runs
          only the three monorepo generators; <code>callers</code> is invoked explicitly.
        </p>
        <blockquote>
          Generated vs hand-maintained: <code>generate callers</code> produces the per-repo thin
          callers. The ops repo{"'"}s reusable <code>deploy.yml</code> and the orchestrator engine
          are hand-maintained in the ops repo — see{" "}
          <a href="/docs/deploy/orchestrator">Orchestrator &amp; Strategies</a>.
        </blockquote>

        <h2>Note on tfvars + renames</h2>
        <p>
          After generating tfvars, renaming a service requires an OpenTofu state migration before
          applying — the command prints the exact <code>tofu state mv</code> command to run.
        </p>
      </div>
    </WikiLayout>
  );
}
