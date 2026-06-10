import { WikiLayout } from "@/components/WikiLayout";

export default function DbCommandPage(): React.ReactElement {
  return (
    <WikiLayout title="foundry db" description="Database management with Liquibase.">
      <div className="prose-wiki max-w-3xl">
        <h1>foundry db</h1>
        <p>
          Standalone Liquibase operations with automatic SSH tunnels and credential resolution —
          no service startup required. Each subcommand runs against every database in{" "}
          <code>foundry.json</code> (or a filtered subset).
        </p>

        <h2>Subcommands</h2>
        <table>
          <thead>
            <tr><th>Subcommand</th><th>Liquibase op</th><th>Description</th></tr>
          </thead>
          <tbody>
            <tr><td><code>migrate</code></td><td><code>update</code></td><td>Run pending migrations</td></tr>
            <tr><td><code>status</code></td><td><code>status</code></td><td>Show the pending changeset count</td></tr>
            <tr><td><code>changelog-sync</code></td><td><code>changelog-sync</code></td><td>Mark all pending changesets as executed (prompts first)</td></tr>
            <tr><td><code>changelog-sync-sql</code></td><td><code>changelog-sync-sql</code></td><td>Preview the changelog-sync SQL without executing</td></tr>
            <tr><td><code>execute-sql</code></td><td><code>execute-sql</code></td><td>Run arbitrary SQL (requires <code>--filter</code> + a SQL argument)</td></tr>
          </tbody>
        </table>

        <h2>Options</h2>
        <table>
          <thead>
            <tr><th>Flag</th><th>Description</th></tr>
          </thead>
          <tbody>
            <tr><td><code>--filter</code></td><td>Comma-separated database names to target. Required (single db) for <code>execute-sql</code>.</td></tr>
          </tbody>
        </table>

        <h2>Credentials &amp; tunnels</h2>
        <p>
          Credentials are resolved from AWS Secrets Manager via the database{"'"}s{" "}
          <code>credentials.secretId</code>, then passed to Liquibase through environment variables
          (avoiding shell-escaping issues). If the secret lookup fails, it falls back to the
          database{"'"}s <code>liquibase.properties</code>. If an <code>sshTunnel</code> is
          configured for the database (in <code>.foundry/config.yml</code> or the manifest service
          entry), the tunnel is opened automatically and the JDBC URL is rewritten to localhost.
        </p>

        <blockquote>
          Requires the Liquibase CLI on <code>PATH</code>. Supported engines: MariaDB, MySQL,
          PostgreSQL.
        </blockquote>

        <h2>Examples</h2>
        <pre><code>{`foundry db migrate                      # update all databases
foundry db migrate --filter api         # one database
foundry db status                       # pending changeset count
foundry db execute-sql --filter api "SELECT COUNT(*) FROM DATABASECHANGELOG"`}</code></pre>
      </div>
    </WikiLayout>
  );
}
