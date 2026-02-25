import { WikiLayout } from "@/components/WikiLayout";

export default function LocalConfigPage(): React.ReactElement {
  return (
    <WikiLayout title="config.yml" description="Personal local configuration.">
      <div className="prose-wiki max-w-3xl">
        <h1>config.yml — Personal Local Config</h1>

        <p>
          <code>.foundry/config.yml</code> is <strong>gitignored</strong> — it holds
          personal preferences, credential pointers, and local overrides that differ
          between developers.
        </p>

        <blockquote>
          This file is <strong>never</strong> created automatically by Foundry.
          Create it yourself when you need it.
        </blockquote>

        <h2>Example</h2>
        <pre><code>{`# .foundry/config.yml — GITIGNORED
# Personal settings, credential pointers, dev overrides.
# Do NOT commit this file.
---
github:
  token: ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Future: personal overrides
# editor: code
# defaultProfile: local`}</code></pre>

        <h2>GitHub Token</h2>
        <p>
          The simplest way to persist a GitHub token for Foundry is:
        </p>
        <pre><code>foundry github auth --token ghp_... --save</code></pre>
        <p>
          This writes the token into <code>.foundry/config.yml</code>.
          Alternatively, use the <code>GITHUB_TOKEN</code> environment variable
          or the GitHub CLI (<code>gh auth login</code>).
        </p>

        <h2>Security</h2>
        <p>
          The nested <code>.foundry/.gitignore</code> excludes <code>config.yml</code>
          by name. It will never be tracked by Git, even if you <code>git add .</code>.
        </p>
      </div>
    </WikiLayout>
  );
}
