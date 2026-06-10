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
foundry generate tfvars`}</code></pre>

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
          </tbody>
        </table>

        <h2>The generated scripts are self-contained</h2>
        <p>
          <code>ci/scripts/</code> does not depend on the Foundry CLI at runtime — it reads{" "}
          <code>foundry.json</code> directly and embeds the convention engine. This is the
          <strong> monorepo</strong> deploy model: the pipeline and scripts live in the same repo
          as the manifest and run there.
        </p>

        <blockquote>
          <strong>Multi-repo / <code>--target ops</code> is not implemented yet.</strong>{" "}
          <code>generate</code> today emits an in-repo pipeline only. Generating the orchestrated{" "}
          <code>foundry-ops</code> reusable workflow and per-repo thin callers from a central{" "}
          <code>platform.json</code> is planned future work — the orchestrated path in{" "}
          <a href="/docs/deploy/model">Deploy Model</a> is currently hand-maintained in{" "}
          <code>foundry-ops</code>.
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
