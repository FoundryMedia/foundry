import Link from "next/link";
import { WikiLayout } from "@/components/WikiLayout";

export default function Custom404(): React.ReactElement {
  return (
    <WikiLayout title="Page Not Found">
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <h1 className="text-6xl font-bold text-slate-700 mb-4">404</h1>
        <p className="text-lg text-slate-400 mb-8">
          This page doesn&apos;t exist yet.
        </p>
        <Link
          href="/"
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-foundry-600 text-white hover:bg-foundry-500 transition-colors no-underline"
        >
          ← Back to Home
        </Link>
      </div>
    </WikiLayout>
  );
}
