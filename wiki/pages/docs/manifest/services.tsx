import { WikiLayout } from "@/components/WikiLayout";

export default function ServicesPage(): React.ReactElement {
  return (
    <WikiLayout title="Services" description="Service definitions in the Foundry manifest.">
      <div className="prose-wiki max-w-3xl">
        <h1>Services</h1>
        <p>
          Each key in <code>services</code> is a service name (kebab-case). The value
          declares what the service IS — not how to run it.
        </p>

        <h2>Service Fields</h2>
        <table>
          <thead>
            <tr><th>Field</th><th>Type</th><th>Description</th></tr>
          </thead>
          <tbody>
            <tr><td><code>kind</code></td><td>string</td><td><code>backend</code>, <code>frontend</code>, or <code>package</code></td></tr>
            <tr><td><code>type</code></td><td>string</td><td>Runtime type — see table below</td></tr>
            <tr><td><code>role</code></td><td>string</td><td>Platform role — see table below</td></tr>
            <tr><td><code>database</code></td><td>string</td><td>Logical database name (key in <code>databases</code>)</td></tr>
            <tr><td><code>apiLibModule</code></td><td>string</td><td>API lib module this service consumes</td></tr>
          </tbody>
        </table>

        <h2>Kind</h2>
        <table>
          <thead>
            <tr><th>Value</th><th>Meaning</th><th>Location</th></tr>
          </thead>
          <tbody>
            <tr><td><code>backend</code></td><td>Server-side service</td><td><code>apps/backend/</code></td></tr>
            <tr><td><code>frontend</code></td><td>Client-side application</td><td><code>apps/frontend/</code></td></tr>
            <tr><td><code>package</code></td><td>Shared library / config package</td><td><code>packages/</code></td></tr>
          </tbody>
        </table>

        <h2>Type</h2>
        <table>
          <thead>
            <tr><th>Value</th><th>Stack</th></tr>
          </thead>
          <tbody>
            <tr><td><code>spring-boot</code></td><td>Java Spring Boot</td></tr>
            <tr><td><code>uvicorn</code></td><td>Python ASGI (FastAPI, Starlette)</td></tr>
            <tr><td><code>gunicorn</code></td><td>Python WSGI (Flask, Django)</td></tr>
            <tr><td><code>nextjs</code></td><td>Next.js (React)</td></tr>
            <tr><td><code>vite</code></td><td>Vite (React, Vue, Svelte)</td></tr>
            <tr><td><code>express</code></td><td>Node.js Express</td></tr>
            <tr><td><code>django</code></td><td>Django</td></tr>
            <tr><td><code>flask</code></td><td>Flask</td></tr>
            <tr><td><code>other</code></td><td>Custom</td></tr>
          </tbody>
        </table>

        <h2>Role</h2>
        <table>
          <thead>
            <tr><th>Value</th><th>Meaning</th></tr>
          </thead>
          <tbody>
            <tr><td><code>microlith</code></td><td>Core platform API (monolith or microlith)</td></tr>
            <tr><td><code>auth</code></td><td>Authentication / authorization service</td></tr>
            <tr><td><code>hub</code></td><td>Internal dashboard / admin UI</td></tr>
            <tr><td><code>public</code></td><td>Public-facing site</td></tr>
            <tr><td><code>status</code></td><td>Status / monitoring dashboard</td></tr>
            <tr><td><code>worker</code></td><td>Background job processor</td></tr>
            <tr><td><code>internal</code></td><td>Internal utility service (NLP, profanity, etc.)</td></tr>
            <tr><td><code>gateway</code></td><td>API gateway / reverse proxy</td></tr>
            <tr><td><code>other</code></td><td>Anything else</td></tr>
          </tbody>
        </table>

        <h2>Example</h2>
        <pre><code>{`"services": {
  "platform-microlith": {
    "kind": "backend",
    "type": "spring-boot",
    "role": "microlith",
    "database": "platform",
    "apiLibModule": "platform-microlith"
  },
  "auth-efga": {
    "kind": "backend",
    "type": "spring-boot",
    "role": "auth",
    "database": "auth"
  },
  "nlp-profanity": {
    "kind": "backend",
    "type": "uvicorn",
    "role": "internal"
  },
  "hub-frontend": {
    "kind": "frontend",
    "type": "nextjs",
    "role": "hub"
  },
  "shared": {
    "kind": "package"
  }
}`}</code></pre>
      </div>
    </WikiLayout>
  );
}
