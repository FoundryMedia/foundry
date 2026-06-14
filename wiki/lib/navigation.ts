interface NavSection {
  title: string;
  items: NavItem[];
}

interface NavItem {
  label: string;
  href: string;
}

export const NAV_SECTIONS: NavSection[] = [
  {
    title: "Getting Started",
    items: [
      { label: "Introduction", href: "/" },
      { label: "Installation", href: "/docs/installation" },
      { label: "Quick Start", href: "/docs/quick-start" },
    ],
  },
  {
    title: "Concepts",
    items: [
      { label: "Platform Philosophy", href: "/docs/concepts/philosophy" },
      { label: "Repo Topology", href: "/docs/concepts/topology" },
    ],
  },
  {
    title: "The Manifest",
    items: [
      { label: "Overview (foundry.json)", href: "/docs/manifest/overview" },
      { label: "Schema Reference", href: "/docs/manifest/schema" },
      { label: "Services", href: "/docs/manifest/services" },
      { label: "Multi-repo: repository & path", href: "/docs/manifest/multi-repo" },
      { label: "Deploy Strategies", href: "/docs/manifest/deploy-strategies" },
      { label: "Environments & Branches", href: "/docs/manifest/environments" },
      { label: "Central Manifest (ops repo)", href: "/docs/manifest/central" },
      { label: "GitHub & Cross-Repo", href: "/docs/manifest/github" },
    ],
  },
  {
    title: "CLI Reference",
    items: [
      { label: "Overview", href: "/docs/cli/overview" },
      { label: "foundry init", href: "/docs/cli/init" },
      { label: "foundry generate", href: "/docs/cli/generate" },
      { label: "foundry sync", href: "/docs/cli/sync" },
      { label: "foundry run", href: "/docs/cli/run" },
      { label: "foundry db", href: "/docs/cli/db" },
      { label: "foundry github", href: "/docs/cli/github" },
      { label: "foundry config", href: "/docs/cli/config" },
      { label: "foundry alias", href: "/docs/cli/alias" },
    ],
  },
  {
    title: "Deploy & CI/CD",
    items: [
      { label: "Deploy Model", href: "/docs/deploy/model" },
      { label: "Orchestrator & Strategies", href: "/docs/deploy/orchestrator" },
      { label: "Thin Caller & Reusable Workflow", href: "/docs/deploy/thin-caller" },
    ],
  },
  {
    title: "Infrastructure",
    items: [
      { label: "IaC Layout", href: "/docs/iac/layout" },
      { label: "tfvars Generation", href: "/docs/iac/tfvars" },
    ],
  },
  {
    title: "Configuration",
    items: [
      { label: ".foundry/ Directory", href: "/docs/config/dotfoundry" },
      { label: "workspace.yml", href: "/docs/config/workspace" },
      { label: "config.yml", href: "/docs/config/local" },
    ],
  },
  {
    title: "Guides",
    items: [
      { label: "Onboard a New Repo/Service", href: "/docs/guides/onboard-service" },
    ],
  },
];
