import { GetStaticProps } from "next";
import { WikiLayout } from "@/components/WikiLayout";
import path from "path";
import fs from "fs";

interface SchemaPageProps {
  schemaJson: string;
}

export const getStaticProps: GetStaticProps<SchemaPageProps> = async () => {
  // Read the actual schema from the foundry repo root at build time.
  // The wiki builds from foundry/wiki, so the schema is one level up.
  const candidates = [
    path.join(process.cwd(), "..", "foundry.schema.json"),
    path.join(process.cwd(), "foundry.schema.json"),
  ];
  let schemaJson = JSON.stringify({ error: "Schema not found at build time" }, null, 2);

  for (const candidate of candidates) {
    try {
      schemaJson = fs.readFileSync(candidate, "utf-8");
      break;
    } catch {
      // try the next candidate
    }
  }

  return { props: { schemaJson } };
};

export default function SchemaReferencePage({ schemaJson }: SchemaPageProps): React.ReactElement {
  const schema = JSON.parse(schemaJson);

  return (
    <WikiLayout title="Schema Reference" description="The foundry.json JSON Schema.">
      <div className="prose-wiki max-w-4xl">
        <h1>Schema Reference</h1>

        <div className="flex items-center gap-3 mb-6">
          <span className="badge-green">v{schema.schemaVersion ?? "0.7.0"}</span>
          <span className="text-sm text-slate-400">
            <code>{schema.$id ?? "foundry.schema.json"}</code>
          </span>
        </div>

        <p>{schema.description ?? "Foundry platform manifest schema."}</p>

        <h2>Required Fields</h2>
        <ul>
          {(schema.required ?? []).map((field: string) => (
            <li key={field}><code>{field}</code></li>
          ))}
        </ul>

        {/* Definitions */}
        {schema.definitions && (
          <>
            <h2>Definitions</h2>
            {Object.entries(schema.definitions as Record<string, Record<string, unknown>>).map(([name, def]) => {
              const props = def.properties as Record<string, Record<string, unknown>> | undefined;
              return (
                <div key={name} className="mb-8">
                  <h3><code>{name}</code></h3>
                  {typeof def.description === "string" && (
                    <p className="text-slate-400">{def.description}</p>
                  )}
                  {props && (
                    <table>
                      <thead>
                        <tr><th>Property</th><th>Type</th><th>Description</th></tr>
                      </thead>
                      <tbody>
                        {Object.entries(props).map(
                          ([prop, propDef]) => (
                            <tr key={prop}>
                              <td><code>{prop}</code></td>
                              <td className="text-slate-400">
                                {(propDef.type as string) ?? (propDef.$ref as string) ?? "—"}
                              </td>
                              <td className="text-slate-400">
                                {(propDef.description as string) ?? ""}
                              </td>
                            </tr>
                          ),
                        )}
                      </tbody>
                    </table>
                  )}
                </div>
              );
            })}
          </>
        )}

        {/* Raw JSON */}
        <h2>Raw Schema</h2>
        <details>
          <summary className="cursor-pointer text-foundry-400 hover:text-foundry-300 mb-3">
            View full JSON schema
          </summary>
          <pre><code>{JSON.stringify(schema, null, 2)}</code></pre>
        </details>
      </div>
    </WikiLayout>
  );
}
