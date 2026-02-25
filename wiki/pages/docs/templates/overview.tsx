import { WikiLayout } from "@/components/WikiLayout";

export default function TemplatesOverviewPage(): React.ReactElement {
  return (
    <WikiLayout title="Templates" description="Foundry platform templates.">
      <div className="prose-wiki max-w-3xl">
        <h1>Templates</h1>

        <p>
          Templates are scaffolding recipes that <code>foundry init</code> uses to
          generate a new platform. Each template defines a directory layout, a set of
          starter services, and a pre-configured <code>foundry.json</code>.
        </p>

        <h2>Available Templates</h2>
        <table>
          <thead>
            <tr><th>Name</th><th>Stack</th><th>Description</th></tr>
          </thead>
          <tbody>
            <tr>
              <td><code>tfw</code></td>
              <td>Spring Boot + Next.js</td>
              <td>The default Foundry template — Java backend, React frontend, PostgreSQL</td>
            </tr>
          </tbody>
        </table>

        <p className="text-slate-500 italic mt-8">
          More templates coming soon. Template authoring docs will be added
          once the template engine is finalized.
        </p>
      </div>
    </WikiLayout>
  );
}
