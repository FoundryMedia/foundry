import Link from "next/link";

export function Header(): React.ReactElement {
  return (
    <header className="sticky top-0 z-50 border-b border-slate-800 bg-gray-950/80 backdrop-blur-md">
      <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-6">
        {/* Logo */}
        <Link href="/" className="flex items-center gap-2.5 no-underline">
          <span className="text-xl font-bold tracking-tight text-white">
            <span className="text-foundry-400">⚒</span> Foundry
          </span>
          <span className="badge-blue text-[10px]">wiki</span>
        </Link>

        {/* Right nav */}
        <nav className="flex items-center gap-4 text-sm">
          <Link href="/docs/manifest/schema" className="text-slate-400 hover:text-white transition-colors">
            Schema
          </Link>
          <Link href="/docs/templates/overview" className="text-slate-400 hover:text-white transition-colors">
            Templates
          </Link>
          <a
            href="https://github.com/FoundryMedia/foundry"
            target="_blank"
            rel="noopener noreferrer"
            className="text-slate-400 hover:text-white transition-colors"
          >
            GitHub ↗
          </a>
        </nav>
      </div>
    </header>
  );
}
