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
    title: "CLI Reference",
    items: [
      { label: "foundry init", href: "/docs/cli/init" },
      { label: "foundry run", href: "/docs/cli/run" },
      { label: "foundry github", href: "/docs/cli/github" },
    ],
  },
  {
    title: "Manifest",
    items: [
      { label: "foundry.json", href: "/docs/manifest/overview" },
      { label: "Schema Reference", href: "/docs/manifest/schema" },
      { label: "Services", href: "/docs/manifest/services" },
      { label: "Ecosystem", href: "/docs/manifest/ecosystem" },
    ],
  },
  {
    title: "Configuration",
    items: [
      { label: ".foundry/ Directory", href: "/docs/config/dotfoundry" },
      { label: "runtime.yml", href: "/docs/config/runtime" },
      { label: "config.yml", href: "/docs/config/local" },
    ],
  },
  {
    title: "Templates",
    items: [
      { label: "Overview", href: "/docs/templates/overview" },
    ],
  },
];
