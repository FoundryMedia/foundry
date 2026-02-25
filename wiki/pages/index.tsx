import Link from "next/link";
import { WikiLayout } from "@/components/WikiLayout";

interface FeatureCardProps {
  icon: string;
  title: string;
  description: string;
  href: string;
}

function FeatureCard({ icon, title, description, href }: FeatureCardProps): React.ReactElement {
  return (
    <Link href={href} className="card block no-underline group">
      <div className="text-2xl mb-3">{icon}</div>
      <h3 className="text-lg font-semibold text-white group-hover:text-foundry-400 transition-colors mb-2">
        {title}
      </h3>
      <p className="text-sm text-slate-400 leading-relaxed">{description}</p>
    </Link>
  );
}

export default function HomePage(): React.ReactElement {
  return (
    <WikiLayout title="Foundry Wiki" description="Documentation for the Foundry platform orchestration toolkit.">
      {/* Hero */}
      <div className="mb-12">
        <h1 className="text-4xl font-bold tracking-tight mb-4">
          <span className="text-foundry-400">⚒</span> Foundry Wiki
        </h1>
        <p className="text-lg text-slate-400 max-w-2xl leading-relaxed">
          Foundry is a platform orchestration toolkit. It manages multi-repo platforms
          with a single declarative manifest — defining topology, services, databases,
          and infrastructure from one source of truth.
        </p>
      </div>

      {/* Quick links grid */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 mb-12">
        <FeatureCard
          icon="🚀"
          title="Quick Start"
          description="Get a platform running in 5 minutes. Install the CLI, init a project, and launch services."
          href="/docs/quick-start"
        />
        <FeatureCard
          icon="📋"
          title="Manifest Reference"
          description="The foundry.json schema — services, ecosystem, databases, and structure configuration."
          href="/docs/manifest/overview"
        />
        <FeatureCard
          icon="⚙️"
          title="CLI Commands"
          description="foundry init, run, github — command reference with examples and flags."
          href="/docs/cli/init"
        />
        <FeatureCard
          icon="🔗"
          title="Ecosystem & Discovery"
          description="Cross-repo discovery via GitHub API. Naming conventions, prefixes, and org topology."
          href="/docs/manifest/ecosystem"
        />
        <FeatureCard
          icon="📁"
          title=".foundry/ Directory"
          description="Runtime config, local state, gitignore strategy — the split between committed and local files."
          href="/docs/config/dotfoundry"
        />
        <FeatureCard
          icon="📦"
          title="Templates"
          description="Scaffold new platforms from templates. Structure enforcement and init wizards."
          href="/docs/templates/overview"
        />
      </div>

      {/* Schema version banner */}
      <div className="card flex items-center gap-4">
        <div className="badge-green">v0.3.0</div>
        <p className="text-sm text-slate-400">
          Current manifest schema version. Services are lean — operational config lives in{" "}
          <code>.foundry/runtime.yml</code>.
        </p>
      </div>
    </WikiLayout>
  );
}
