import { WikiLayout } from "@/components/WikiLayout";

export default function TfvarsPage(): React.ReactElement {
  return (
    <WikiLayout title="tfvars Generation" description="How foundry generate tfvars builds OpenTofu inputs.">
      <div className="prose-wiki max-w-3xl">
        <h1>tfvars Generation</h1>
        <p>
          In the monorepo model, <a href="/docs/cli/generate"><code>foundry generate tfvars</code></a>{" "}
          produces an OpenTofu variable file per enabled environment at{" "}
          <code>ci/iac/&#123;env&#125;/&#123;env&#125;.auto.tfvars</code>. It combines the manifest
          with infrastructure config from AWS so the IaC stack has everything it needs.
        </p>

        <h2>Data sources</h2>
        <table>
          <thead>
            <tr><th>Source</th><th>Provides</th></tr>
          </thead>
          <tbody>
            <tr><td><code>foundry.json</code> (committed)</td><td>Service names, stacks, strategies, deploy config</td></tr>
            <tr><td>Secrets Manager <code>&#123;prefix&#125;-&#123;env&#125;/iac/config</code></td><td>The full infrastructure config (services, lambdas, domain, bastion, …)</td></tr>
            <tr><td>AWS CLI at runtime</td><td>Account ID (STS) and hosted zone id (Route 53)</td></tr>
          </tbody>
        </table>

        <h2>Template variables</h2>
        <p>Values in the IaC config can reference these, resolved at generation time:</p>
        <pre><code>{`{prefix}        e.g. aap
{env}           e.g. prod
{name_prefix}   {prefix}-{env}
{account_id}    from STS
{region}        AWS region
{iac_name}      IaC service key (e.g. platform-microlith-service)
{manifest_name} manifest service key (e.g. platform-microlith)`}</code></pre>

        <h2>Output</h2>
        <p>
          The generated tfvars carries the platform block, the services map (ECS services keyed by
          IaC name), static sites, lambdas, EventBridge rules, bastion, and domain configuration —
          the inputs the monorepo IaC stack consumes.
        </p>

        <blockquote>
          Renaming a service changes its IaC key. Before applying, migrate the OpenTofu state — the
          command prints the exact <code>tofu state mv</code> to run. This tfvars path is the
          monorepo model; multi-repo services use their own per-repo{" "}
          <a href="/docs/iac/layout">app-edge stacks</a> instead.
        </blockquote>
      </div>
    </WikiLayout>
  );
}
