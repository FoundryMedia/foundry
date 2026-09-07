import { WikiLayout } from "@/components/WikiLayout";

export default function LocalConfigPage(): React.ReactElement {
  return (
    <WikiLayout title="config.yml" description="Personal local configuration.">
      <div className="prose-wiki max-w-3xl">
        <h1>config.yml — Personal Local Config</h1>
        <p>
          <code>.foundry/config.yml</code> is <strong>gitignored</strong> — it holds personal
          preferences, credential pointers, and per-developer overrides. The nested{" "}
          <code>.foundry/.gitignore</code> excludes it by name, so it is never tracked even with{" "}
          <code>git add .</code>.
        </p>

        <blockquote>
          Foundry only creates this file when you ask it to (for example,{" "}
          <code>foundry github auth --save</code>). Otherwise create it yourself when you need it.
        </blockquote>

        <h2>What goes here</h2>
        <ul>
          <li>A GitHub token (<code>github.token</code>) for cross-repo discovery</li>
          <li>Per-service SSH tunnel settings used by <a href="/docs/cli/db"><code>foundry db</code></a></li>
          <li>Personal overrides you don{"'"}t want to share with the team</li>
        </ul>

        <h2>Example</h2>
        <pre><code>{`# .foundry/config.yml — GITIGNORED
github:
  token: ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

services:
  api:
    sshTunnel:
      host: bastion.example.com
      user: ec2-user
      password: ci/keys/bastion.pem   # path to the SSH key
      remoteHost: db.internal
      remotePort: 5432
      localPort: 5432`}</code></pre>

        <h2>Defaults vs local</h2>
        <p>
          A committed <code>config.defaults.yml</code> can hold team-shared defaults (for example,
          a shared bastion host). The CLI deep-merges <code>config.yml</code> <em>over</em>{" "}
          <code>config.defaults.yml</code>, so your personal file only needs the values that differ.
        </p>

        <h2>Dev-run env files and targets</h2>
        <p>
          <code>foundry run dev</code> resolves each service{"'"}s environment before starting it:
          manifest <code>run.env</code>, then the committed <code>.foundry/dev.env</code>, then the
          gitignored <code>.foundry/dev.local.env</code>. From that stack it picks a target per
          service: <code>FOUNDRY_DEV_TARGET=prod</code> starts the manifest{"'"}s SSH tunnel and
          injects database credentials pointed at it; <code>local</code> (or nothing configured)
          skips the tunnel entirely and the service{"'"}s own local defaults apply.
        </p>
        <pre><code>{`# .foundry/dev.env — COMMITTED team default
FOUNDRY_DEV_TARGET=prod

# .foundry/dev.local.env — GITIGNORED personal override
FOUNDRY_DEV_TARGET=local`}</code></pre>
        <p>
          The tunnel itself can autowire from AWS when the manifest opts in — all fields optional:
          <code>bastionTag</code> resolves the host by EC2 Name tag when the host variable is unset,
          <code>keySecret</code> fetches the pem from Secrets Manager when the key file is missing,
          and <code>credentialsSecret</code>/<code>injectEnv</code> inject database credentials into
          the service process (never written to disk).
        </p>

        <h2>Multiple tunnels per service</h2>
        <p>
          A service that needs several tunnels at once (an auth service plus two databases, say)
          declares a named <code>sshTunnels</code> map instead of the singular{" "}
          <code>sshTunnel</code>. All tunnels open in parallel before the service starts —
          all-or-nothing: if any fails, the rest are closed and the service does not start.
          Map entries inject <strong>only what they declare</strong>: an <code>env</code> block
          (with <code>{"${localPort}"}</code>/<code>{"${localHost}"}</code> expansion) plus{" "}
          <code>injectEnv</code> fields read from <code>credentialsSecret</code>. The legacy
          singular form keeps its implicit <code>DB_HOST</code>/<code>DB_PORT</code> and default
          credential injection; declaring both forms is an error.
        </p>
        <pre><code>{`services:
  api:
    sshTunnels:
      authService:
        localPort: 18080
        remoteHost: auth.internal
        remotePort: 443
        host: \${BASTION_HOST}
        env:
          AUTH_BASE_URL: http://localhost:\${localPort}
      db:                        # the entry named "db" is what
        localPort: 15432         # \`foundry db\` migrations tunnel through
        remoteHost: \${DB1_HOST}
        remotePort: 5432
        host: \${BASTION_HOST}
        credentialsSecret: acme-prod/api/db1
        env: { DB1_HOST: localhost, DB1_PORT: "\${localPort}" }
        injectEnv: { DB1_USER: username, DB1_PASSWORD: password }
      replicaDb:
        localPort: 15433
        remoteHost: \${DB2_HOST}
        remotePort: 5432
        host: \${BASTION_HOST}
        credentialsSecret: acme-prod/api/db2
        env: { DB2_PORT: "\${localPort}" }
        injectEnv: { DB2_USER: username, DB2_PASSWORD: password }`}</code></pre>
        <p>
          Every tunnel needs its own <code>localPort</code>, and two tunnels may not inject the
          same env var — both are hard errors before anything connects. In{" "}
          <code>config.yml</code>, <code>sshTunnels</code> overrides merge <em>by name</em>: a
          name mapped to an object replaces that tunnel, a name mapped to <code>null</code>{" "}
          removes it, and <code>sshTunnels: false</code> disables them all.
        </p>

        <h2>Bind address — loopback by default</h2>
        <p>
          Tunnels listen on <strong>loopback only</strong>: <code>127.0.0.1</code> plus{" "}
          <code>::1</code> (so <code>-h localhost</code> works on dual-stack machines where{" "}
          <code>localhost</code> resolves to <code>::1</code> first, e.g. macOS). Nothing else on
          your network can reach the tunnelled service — the same default as{" "}
          <code>ssh -L</code>. If something <em>off-host</em> must connect (a Docker container
          reaching the tunnel via <code>host.docker.internal</code>), opt in per tunnel with{" "}
          <code>bindAddress</code>:
        </p>
        <pre><code>{`sshTunnels:
  db:
    localPort: 15432
    remoteHost: \${DB_HOST}
    remotePort: 5432
    host: \${BASTION_HOST}
    bindAddress: 0.0.0.0   # EXPOSES the port to your LAN — containers only`}</code></pre>
        <p>
          A non-loopback <code>bindAddress</code> logs a warning at startup — the tunnelled
          database becomes reachable by every machine on the local network (coffee-shop wifi
          included). <code>bindAddress</code> is IPv4-only; the <code>::1</code> listener exists
          only on the default loopback bind.
        </p>
        <p>
          A <code>localPort</code> already held by another process is a <strong>hard error</strong>{" "}
          (the tunnel fails, and with it the service — all-or-nothing). Foundry never assumes an
          existing listener is its own tunnel: stop the other process or pick a different port.
        </p>

        <h2>SSH authentication — key file or agent</h2>
        <p>
          The <code>password</code> field (a path to an SSH private key file) is{" "}
          <strong>optional</strong>. When omitted, authentication falls back to your{" "}
          <strong>SSH agent</strong> (and keys in <code>~/.ssh</code>) — the right choice when
          your key is passphrase-encrypted: encrypted key <em>files</em> are not supported
          (there is no passphrase field), but an agent-loaded key works regardless.{" "}
          <code>keySecret</code> can still fetch an unencrypted pem from AWS Secrets Manager
          into the <code>password</code> path when the file is missing.
        </p>

        <h2>Named environments — run several side by side</h2>
        <p>
          A service can declare per-environment dev overlays inside its existing{" "}
          <code>environments</code> block. <code>foundry run dev --env staging</code> (or{" "}
          <code>FOUNDRY_DEV_ENV=staging</code>; the flag wins) applies each service{"'"}s{" "}
          <code>environments.staging</code> overlay: <code>run</code> shallow-merges (port,
          args, script replace; <code>run.env</code> layers in), <code>env</code> layers in, and{" "}
          <code>sshTunnels</code> merges <em>by tunnel name</em> — an existing tunnel changes
          only the fields you give, a new name is a full tunnel, <code>null</code> removes one.
          An environment used only for dev needs no <code>branch</code>; branchless environments
          are invisible to the CI generators.
        </p>
        <pre><code>{`services:
  api:
    run: { port: 8091 }
    sshTunnels:
      db: { localPort: 15432, remoteHost: \${DB_HOST}, remotePort: 5432,
            host: \${BASTION_HOST}, credentialsSecret: acme-prod/api/db }
    environments:
      staging:                       # dev-only: no branch
        run: { port: 9091 }
        sshTunnels:
          db: { localPort: 25432, credentialsSecret: acme-staging/api/db }`}</code></pre>
        <p>
          Env files gain a per-environment pair layered between the base ones:{" "}
          <code>dev.env</code> → <code>dev.staging.env</code> → <code>dev.local.env</code> →{" "}
          <code>dev.staging.local.env</code> (the <code>*.local.env</code> pattern stays
          gitignored). Give each environment <strong>distinct ports</strong> (service port and
          tunnel <code>localPort</code>s) and two terminals can run{" "}
          <code>foundry run dev</code> and <code>foundry run dev --env staging</code>{" "}
          simultaneously — a port collision fails loudly at bind, and the fix is one overlay
          line.
        </p>

        <h2>Multi-repo workspaces and profiles</h2>
        <p>
          A platform{"'"}s ops repo can carry a master <code>foundry.workspace.json</code> at its
          root naming the member repos (sibling clones) and named run profiles. Its schema is
          published at{" "}
          <code>https://raw.githubusercontent.com/FoundryMedia/foundry/release/foundry.workspace.schema.json</code>{" "}
          — reference it from <code>$schema</code> for editor validation:
        </p>
        <pre><code>{`{
  "$schema": "https://raw.githubusercontent.com/FoundryMedia/foundry/release/foundry.workspace.schema.json",
  "repos": ["fid", "foundry-auth-efga", "foundry-app"],
  "profiles": {
    "core": ["fid", "auth-efga"],
    "web": ["fid", "auth-efga", "web"]
  }
}`}</code></pre>
        <p>
          <code>repos</code> are member repository <em>directory</em> names, each with its own{" "}
          <code>.foundry/foundry.json</code>; <code>profiles</code> map a name to manifest{" "}
          <em>service</em> names (the keys under <code>services</code>, not repo names).{" "}
          <code>foundry run dev:core</code> (shorthand for <code>dev --profile core</code>) boots
          that profile{"'"}s services from every member repo in one session — each service keeps its
          own repo{"'"}s env files, tunnels, and credentials. Running <code>foundry run dev</code>{" "}
          from a directory with no manifest falls back to the full workspace (everything
          discoverable). Repos not cloned locally are skipped with a notice.{" "}
          <code>FOUNDRY_WORKSPACE</code> points at a specific workspace file when discovery
          shouldn{"'"}t walk the filesystem. <code>--filter a,b,c</code> remains the ad-hoc
          alternative for a one-off subset; profiles are the shareable, committed form.
        </p>

        <h2>GitHub token shortcut</h2>
        <pre><code>foundry github auth --token ghp_... --save</code></pre>
        <p>
          This writes the token into <code>config.yml</code> for you. Alternatively use the{" "}
          <code>GITHUB_TOKEN</code> environment variable or the GitHub CLI (<code>gh auth login</code>).
        </p>
      </div>
    </WikiLayout>
  );
}
