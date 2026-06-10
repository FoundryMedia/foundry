import Link from "next/link";

export function Header(): React.ReactElement {
  return (
    <header className="sticky top-0 z-50 border-b border-slate-800 bg-gray-950/80 backdrop-blur-md">
      <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-6">
        {/* Logo */}
        <Link href="/" className="flex items-center gap-2.5 no-underline">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/logo.svg" alt="Foundry" width={28} height={28} className="h-7 w-7" />
          <span className="text-xl font-bold tracking-tight text-white">Foundry</span>
        </Link>

        {/* Right nav */}
        <nav className="flex items-center gap-4 text-sm">
          <Link href="/docs/manifest/schema" className="text-slate-400 hover:text-white transition-colors">
            Schema
          </Link>
          <Link href="/docs/cli/overview" className="text-slate-400 hover:text-white transition-colors">
            CLI
          </Link>
          <a
            href="https://github.com/FoundryMedia/foundry"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-slate-400 hover:text-white transition-colors"
          >
            GitHub
            <span aria-hidden="true">↗</span>
          </a>
        </nav>
      </div>
    </header>
  );
}
