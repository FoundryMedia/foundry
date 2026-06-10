import { WikiLayout } from "@/components/WikiLayout";

export default function TopologyPage(): React.ReactElement {
  return (
    <WikiLayout title="Repo Topology" description="The three-repo model and how monorepo vs multi-repo works.">
      <div className="prose-wiki max-w-3xl">
        <h1>Repo Topology</h1>
        <p>
          Foundry separates three concerns across three repositories. Understanding this split is
          the key to everything else in the wiki.
        </p>

        <h2>The three repos</h2>
        <table>
          <thead>
            <tr><th>Repo</th><th>Role</th><th>Owns</th></tr>
          </thead>
          <tbody>
            <tr>
              <td><code>foundry</code> (+ the manifest)</td>
              <td>The brain</td>
              <td>The CLI, the manifest schema, and — in a monorepo — the platform{"'"}s own <code>foundry.json</code>.</td>
            </tr>
            <tr>
              <td><code>foundry-ops</code></td>
              <td>CI/CD owner &amp; library</td>
              <td>The central multi-repo manifest (<code>platform.json</code>), the orchestrator, and the reusable deploy workflow that service repos call.</td>
            </tr>
            <tr>
              <td><code>foundry-iac</code></td>
              <td>Infrastructure modules</td>
              <td>Shared OpenTofu modules and the control-plane stack. Per-service app-edge infra lives in each repo{"'"}s <code>ci/iac/</code>.</td>
            </tr>
          </tbody>
        </table>

        <h2>Manifest is the brain</h2>
        <p>
          Everything flows from a manifest. It declares WHAT the platform is — services, stacks,
          environments, and how each service deploys. In a monorepo that manifest is the repo{"'"}s
          <code>foundry.json</code>. In a multi-repo platform the authoritative manifest is{" "}
          <a href="/docs/manifest/central">foundry-ops/platform.json</a>, and individual service
          repos carry no manifest of their own — only a thin caller workflow.
        </p>

        <h2>foundry-ops is the CI/CD owner</h2>
        <p>
          Deploy logic lives in one place. A service repo{"'"}s deploy workflow is a{" "}
          <a href="/docs/deploy/thin-caller">thin caller</a> that invokes{" "}
          <code>foundry-ops</code>{"'"}s reusable <code>workflow_call</code> workflow. That workflow
          checks out the caller repo, reads <code>platform.json</code>, and runs the{" "}
          <a href="/docs/deploy/orchestrator">orchestrator</a>. No deploy logic is duplicated
          across service repos.
        </p>

        <h2>foundry-iac holds the modules</h2>
        <p>
          Shared infrastructure — VPC, ECS, RDS, ALB, CloudFront, WAF, and more — lives as
          reusable OpenTofu modules in <code>foundry-iac</code>, alongside the control-plane stack
          that provisions the always-on platform. Each app{"'"}s edge infrastructure (its S3 bucket
          and CloudFront distribution for a static site, for example) lives in that repo{"'"}s own{" "}
          <code>ci/iac/</code> stack. See <a href="/docs/iac/layout">IaC Layout</a>.
        </p>

        <h2>Monorepo vs multi-repo</h2>
        <p>
          The same manifest model covers both. The difference is two per-service fields:
        </p>
        <ul>
          <li>
            <strong>Monorepo</strong> — omit <code>repository</code> and <code>path</code>. The
            service lives at the convention path <code>apps/&#123;type&#125;/&#123;name&#125;</code>{" "}
            (or <code>packages/&#123;name&#125;</code>).
          </li>
          <li>
            <strong>Multi-repo</strong> — set <code>repository</code> to{" "}
            <code>owner/repo</code> and optionally <code>path</code> (<code>.</code> = repo root, or
            a subdirectory). The service lives in its own repository.
          </li>
        </ul>
        <p>
          Multi-repo is additive — a platform can mix both. Details in{" "}
          <a href="/docs/manifest/multi-repo">Multi-repo: repository &amp; path</a>.
        </p>

        <blockquote>
          GitHub-only: Foundry{"'"}s cross-repo discovery and the orchestrated deploy path are built
          on GitHub (Actions, the GitHub API, and a GitHub App for cross-repo checkout).
        </blockquote>
      </div>
    </WikiLayout>
  );
}
