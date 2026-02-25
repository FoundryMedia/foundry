import { WikiLayout } from "@/components/WikiLayout";

export default function RunCommandPage(): React.ReactElement {
  return (
    <WikiLayout title="foundry run" description="Launch platform services.">
      <div className="prose-wiki max-w-3xl">
        <h1>foundry run</h1>
        <p>Launch all enabled services defined in the platform manifest.</p>

        <h2>Usage</h2>
        <pre><code>{`foundry run [OPTIONS] [SERVICES...]`}</code></pre>

        <h2>Options</h2>
        <table>
          <thead>
            <tr><th>Flag</th><th>Description</th></tr>
          </thead>
          <tbody>
            <tr><td><code>SERVICES</code></td><td>Optional list of specific service names to run</td></tr>
            <tr><td><code>--help</code></td><td>Show help message</td></tr>
          </tbody>
        </table>

        <h2>Behaviour</h2>
        <p>
          Reads <code>.foundry/runtime.yml</code> for ports, commands, and environment
          variables. Launches each service in a managed subprocess with colour-coded
          log output.
        </p>
        <p>
          Services are started in dependency order where possible. Backends launch before
          frontends. Health check endpoints are polled to confirm readiness.
        </p>

        <h2>Runtime Configuration</h2>
        <p>
          Port assignments, start commands, and environment variables come from{" "}
          <code>.foundry/runtime.yml</code>, not from <code>foundry.json</code>.
          The manifest declares <em>what</em> services exist; the runtime config
          declares <em>how</em> to run them.
        </p>
      </div>
    </WikiLayout>
  );
}
