import { WikiLayout } from "@/components/WikiLayout";

export default function MultiRepoPage(): React.ReactElement {
  return (
    <WikiLayout title="Multi-repo: repository & path" description="How services in separate repositories are described.">
      <div className="prose-wiki max-w-3xl">
        <h1>Multi-repo: repository &amp; path</h1>
        <p>
          Schema v0.7.0 lets one manifest describe services that live in different repositories.
          Two per-service fields control this — <code>repository</code> and <code>path</code> — and
          the CLI{"'"}s convention engine resolves paths differently depending on them.
        </p>

        <h2>The two fields</h2>
        <table>
          <thead>
            <tr><th>Field</th><th>Meaning</th></tr>
          </thead>
          <tbody>
            <tr><td><code>repository</code></td><td>The GitHub <code>owner/repo</code> the service lives in. <strong>Omit</strong> for a service in the same repo as the manifest (monorepo).</td></tr>
            <tr><td><code>path</code></td><td>The service{"'"}s path within its repository. <code>.</code> or omitted = repo root; a subdir (e.g. <code>app</code>) = service lives in a subdirectory.</td></tr>
          </tbody>
        </table>

        <h2>Resolution matrix</h2>
        <table>
          <thead>
            <tr><th><code>repository</code></th><th><code>path</code></th><th>Result</th></tr>
          </thead>
          <tbody>
            <tr><td>omitted</td><td>omitted</td><td><strong>Monorepo</strong> — service at the convention path <code>apps/&#123;type&#125;/&#123;name&#125;</code> (or <code>packages/&#123;name&#125;</code>)</td></tr>
            <tr><td>omitted</td><td>subdir</td><td>Monorepo with an explicit subdirectory layout</td></tr>
            <tr><td><code>owner/repo</code></td><td><code>.</code> / omitted</td><td><strong>Multi-repo</strong> — service is the whole repo (paths are repo-root-relative)</td></tr>
            <tr><td><code>owner/repo</code></td><td>subdir</td><td>Multi-repo — service is a subdirectory of that repo</td></tr>
          </tbody>
        </table>

        <h2>How paths are resolved</h2>
        <p>
          When a service is multi-repo (has a <code>repository</code>) or declares a{" "}
          <code>path</code>, the convention engine switches to <strong>repo-relative</strong> mode:
          the Dockerfile, build context, and CI change-detection watch paths are computed relative
          to the service{"'"}s location in its own repo, rather than the monorepo{"'"}s{" "}
          <code>apps/&#123;type&#125;/&#123;name&#125;</code> convention. A service at the repo root
          (<code>path: "."</code>) watches the whole repo; a subdir service watches just that
          subdir.
        </p>

        <h2>Per-service environment overrides</h2>
        <p>
          Repos can use different branch models. A multi-repo service may override the
          platform-wide <code>ci.environments</code> with its own per-environment branch mapping
          via a service-level <code>environments</code> block; omitted environments fall back to{" "}
          <code>ci.environments</code>. See <a href="/docs/manifest/environments">Environments &amp; Branches</a>.
        </p>

        <h2>Example</h2>
        <pre><code>{`"services": {
  "web": {
    "repository": "your-org/web-app",
    "path": "app",
    "environments": { "prod": { "branch": "main" } },
    "stack": { "type": "frontend", "framework": "vite" },
    "deploy": { "strategy": "static" }
  },
  "launcher": {
    "repository": "your-org/web-app",
    "stack": { "type": "frontend", "framework": "vite" },
    "deploy": { "strategy": "desktop" }
  }
}`}</code></pre>
        <p>
          Here <code>web</code> lives in the <code>app/</code> subdir of <code>your-org/web-app</code>{" "}
          and deploys from <code>main</code>; <code>launcher</code> is the root of the same repo. A
          full worked example is the central{" "}
          <a href="/docs/manifest/central">ops-repo <code>platform.json</code></a>.
        </p>
      </div>
    </WikiLayout>
  );
}
