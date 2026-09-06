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

        <h2>Multi-repo workspaces and profiles</h2>
        <p>
          A platform{"'"}s ops repo can carry a master <code>foundry.workspace.json</code> at its
          root naming the member repos (sibling clones) and named run profiles:
        </p>
        <pre><code>{`{
  "repos": ["fid", "foundry-auth-efga", "foundry-app"],
  "profiles": {
    "core": ["fid", "auth-efga"],
    "web": ["fid", "auth-efga", "web"]
  }
}`}</code></pre>
        <p>
          <code>foundry run dev:core</code> (shorthand for <code>dev --profile core</code>) boots
          that profile{"'"}s services from every member repo in one TUI — each service keeps its own
          repo{"'"}s env files, tunnel, and credentials. Running <code>foundry run dev</code> from a
          directory with no manifest falls back to the full workspace (everything discoverable).
          Repos not cloned locally are skipped with a notice. <code>FOUNDRY_WORKSPACE</code> points
          at a specific workspace file when discovery shouldn{"'"}t walk the filesystem.
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
