import Head from "next/head";
import { Header } from "./Header";
import { Sidebar } from "./Sidebar";

interface WikiLayoutProps {
  title: string;
  description?: string;
  children: React.ReactNode;
}

export function WikiLayout({ title, description, children }: WikiLayoutProps): React.ReactElement {
  const fullTitle = title === "Foundry Wiki" ? title : `${title} — Foundry Wiki`;

  return (
    <>
      <Head>
        <title>{fullTitle}</title>
        {description && <meta name="description" content={description} />}
      </Head>

      <div className="min-h-screen flex flex-col">
        <Header />

        <div className="flex flex-1 mx-auto w-full max-w-7xl">
          {/* Sidebar */}
          <Sidebar className="hidden lg:block w-64 shrink-0 border-r border-slate-800 py-8 px-4 overflow-y-auto sticky top-14 h-[calc(100vh-3.5rem)] scrollbar-subtle" />

          {/* Main content */}
          <main className="flex-1 min-w-0 py-8 px-6 lg:px-12">
            {children}
          </main>
        </div>
      </div>
    </>
  );
}
