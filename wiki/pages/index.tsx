import Link from "next/link";
import { Rocket, Network, FileJson, SquareTerminal, Ship, Server, type LucideIcon } from "lucide-react";
import { WikiLayout } from "@/components/WikiLayout";

interface FeatureCardProps {
  icon: LucideIcon;
  title: string;
  description: string;
  href: string;
}

function FeatureCard({ icon: Icon, title, description, href }: FeatureCardProps): React.ReactElement {
  return (
    <Link href={href} className="card block no-underline group">
      <Icon className="h-6 w-6 text-foundry-400 mb-3" strokeWidth={1.75} aria-hidden="true" />
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
        <h1 className="flex items-center gap-3 text-4xl font-bold tracking-tight mb-4">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/logo.svg" alt="" width={40} height={40} className="h-10 w-10" />
          Foundry Wiki
        </h1>
        <p className="text-lg text-slate-400 max-w-2xl leading-relaxed">
          Foundry is a declarative, manifest-driven framework for building and operating
          platforms. One manifest describes the platform — its services, stacks, environments,
          and how each service deploys. The <code>foundry</code> CLI scaffolds it, runs it
          locally, and generates its CI/CD; <code>foundry-ops</code> orchestrates deploys;
          <code>foundry-iac</code> holds the shared infrastructure modules.
        </p>
      </div>

      {/* Quick links grid */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 mb-12">
        <FeatureCard
          icon={Rocket}
          title="Quick Start"
          description="Install the CLI, init a project, and run services locally with foundry run dev."
          href="/docs/quick-start"
        />
        <FeatureCard
          icon={Network}
          title="Repo Topology"
          description="The three-repo model: manifest is the brain, foundry-ops owns CI/CD, foundry-iac holds modules."
          href="/docs/concepts/topology"
        />
        <FeatureCard
          icon={FileJson}
          title="The Manifest"
          description="foundry.json / platform.json — services, stacks, deploy strategies, environments, multi-repo."
          href="/docs/manifest/overview"
        />
        <FeatureCard
          icon={SquareTerminal}
          title="CLI Reference"
          description="init, generate, run, sync, db, github, config, alias — what each command actually does."
          href="/docs/cli/overview"
        />
        <FeatureCard
          icon={Ship}
          title="Deploy Model"
          description="Thin caller → foundry-ops reusable workflow → orchestrator → smart IaC (plan, apply on change)."
          href="/docs/deploy/model"
        />
        <FeatureCard
          icon={Server}
          title="Infrastructure"
          description="Shared foundry-iac modules + control-plane stack, plus per-repo ci/iac app-edge stacks."
          href="/docs/iac/layout"
        />
      </div>

      {/* Schema version banner */}
      <div className="card flex items-center gap-4">
        <div className="badge-green">Manifest spec v0.7.0</div>
        <p className="text-sm text-slate-400">
          The manifest schema is at v0.7.0 (multi-repo: per-service <code>repository</code>,{" "}
          <code>path</code>, and <code>environments</code>; a unified <code>deploy.strategy</code>).
          <code>foundry init</code> currently scaffolds a single-repo v0.5.0 manifest — the
          multi-repo fields are additive and used by the central{" "}
          <Link href="/docs/manifest/central">foundry-ops/platform.json</Link>.
        </p>
      </div>
    </WikiLayout>
  );
}
