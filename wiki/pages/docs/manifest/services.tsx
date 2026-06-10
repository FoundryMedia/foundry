import { WikiLayout } from "@/components/WikiLayout";
import { CodeList } from "@/components/CodeList";

export default function ServicesPage(): React.ReactElement {
  return (
    <WikiLayout title="Services" description="Service definitions in the Foundry manifest.">
      <div className="prose-wiki max-w-3xl">
        <h1>Services</h1>
        <p>
          Each key in <code>services</code> is a service name. The value declares what the service
          IS, grouped into structured blocks: <code>scope</code> (visibility),{" "}
          <code>stack</code> (technology), <code>deploy</code> (how it ships), and{" "}
          <code>run</code> (local dev). Multi-repo services add <code>repository</code> and{" "}
          <code>path</code>.
        </p>

        <h2>Service fields</h2>
        <table>
          <thead>
            <tr><th>Field</th><th>Type</th><th>Description</th></tr>
          </thead>
          <tbody>
            <tr><td><code>scope</code></td><td>string</td><td><code>public</code> or <code>internal</code> — visibility of the service</td></tr>
            <tr><td><code>stack</code></td><td>object</td><td><code>type</code>, <code>framework</code>, <code>language</code> — see below</td></tr>
            <tr><td><code>deploy</code></td><td>object</td><td>How it ships. Requires <code>strategy</code>. See <a href="/docs/manifest/deploy-strategies">Deploy Strategies</a></td></tr>
            <tr><td><code>run</code></td><td>object</td><td>Local dev runtime — ports, args, env, health checks</td></tr>
            <tr><td><code>database</code></td><td>string / object</td><td>Inline database config (engine, changelog, schema)</td></tr>
            <tr><td><code>repository</code></td><td>string</td><td>Multi-repo: the <code>owner/repo</code> this service lives in. See <a href="/docs/manifest/multi-repo">Multi-repo</a></td></tr>
            <tr><td><code>path</code></td><td>string</td><td>Multi-repo: the service{"'"}s path within its repository (<code>.</code> = root)</td></tr>
            <tr><td><code>environments</code></td><td>object</td><td>Multi-repo: per-service env→branch override. See <a href="/docs/manifest/environments">Environments</a></td></tr>
          </tbody>
        </table>

        <h2>stack</h2>
        <table>
          <thead>
            <tr><th>Field</th><th>Values</th><th>Meaning</th></tr>
          </thead>
          <tbody>
            <tr><td><code>type</code></td><td><CodeList items={["backend", "frontend", "package"]} /></td><td>Architecture category. In a monorepo it also fixes the location: <span className="whitespace-nowrap"><code>backend</code> → <code>apps/backend/&#123;name&#125;</code></span>, <span className="whitespace-nowrap"><code>frontend</code> → <code>apps/frontend/&#123;name&#125;</code></span>, <span className="whitespace-nowrap"><code>package</code> → <code>packages/&#123;name&#125;</code></span></td></tr>
            <tr><td><code>framework</code></td><td><CodeList items={["spring-boot", "uvicorn", "nextjs", "vite"]} trailing="…" /></td><td>The concrete runtime/framework. Drives convention defaults (Dockerfile, build context, secrets)</td></tr>
            <tr><td><code>language</code></td><td><CodeList items={["java", "python", "typescript"]} trailing="…" /></td><td>Primary language (optional)</td></tr>
          </tbody>
        </table>

        <blockquote>
          <code>stack.type</code> (what it is / where it lives) is orthogonal to{" "}
          <code>deploy.strategy</code> (how it ships). A <code>frontend</code> can deploy as{" "}
          <code>static</code> (S3/CDN) or <code>service</code> (SSR on ECS); a <code>package</code>{" "}
          deploys as <code>none</code>.
        </blockquote>

        <h2>Deprecated fields (v0.5.0)</h2>
        <p>The flat v0.4.0 fields were grouped into blocks. The CLI still reads the old names as aliases, but new manifests should use the blocks:</p>
        <table>
          <thead>
            <tr><th>Old (deprecated)</th><th>New</th></tr>
          </thead>
          <tbody>
            <tr><td><code>kind</code></td><td><code>stack.type</code></td></tr>
            <tr><td><code>type</code></td><td><code>stack.framework</code></td></tr>
            <tr><td><code>role</code></td><td><code>scope</code></td></tr>
            <tr><td><code>strategy</code></td><td><code>deploy.strategy</code></td></tr>
          </tbody>
        </table>

        <h2>Example</h2>
        <pre><code>{`"services": {
  "api": {
    "scope": "internal",
    "stack": { "type": "backend", "framework": "spring-boot", "language": "java" },
    "deploy": { "strategy": "service" },
    "database": { "engine": "postgresql", "changelog": "ci/db/api/changelog-master.xml" }
  },
  "web": {
    "scope": "public",
    "stack": { "type": "frontend", "framework": "nextjs", "language": "typescript" },
    "deploy": { "strategy": "static", "cdn": true }
  },
  "shared": {
    "stack": { "type": "package" }
  }
}`}</code></pre>
      </div>
    </WikiLayout>
  );
}
