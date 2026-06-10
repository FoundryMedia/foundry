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
