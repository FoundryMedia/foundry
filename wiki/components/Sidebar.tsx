import Link from "next/link";
import { useRouter } from "next/router";
import { NAV_SECTIONS } from "@/lib/navigation";

interface SidebarProps {
  className?: string;
}

export function Sidebar({ className }: SidebarProps): React.ReactElement {
  const router = useRouter();

  return (
    <aside className={className}>
      <nav className="space-y-6">
        {NAV_SECTIONS.map((section) => (
          <div key={section.title}>
            <h4 className="px-3 text-xs font-semibold uppercase tracking-wider text-slate-500 mb-2">
              {section.title}
            </h4>
            <ul className="space-y-0.5">
              {section.items.map((item) => {
                const isActive = router.pathname === item.href;
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      className={isActive ? "sidebar-link-active" : "sidebar-link"}
                    >
                      {item.label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>
    </aside>
  );
}
