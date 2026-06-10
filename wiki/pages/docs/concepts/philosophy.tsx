import { WikiLayout } from "@/components/WikiLayout";

export default function PhilosophyPage(): React.ReactElement {
  return (
    <WikiLayout title="Platform Philosophy" description="Why Foundry is shaped the way it is.">
      <div className="prose-wiki max-w-3xl">
        <h1>Platform Philosophy</h1>
        <p>
          Foundry exists to let a small team build lean early without painting itself into a
          corner later. It is a declarative framework: one manifest describes the platform, and
          the tooling scaffolds, runs, and ships it. The principles below explain why the pieces
          are arranged the way they are.
        </p>

        <h2>Lean by default, without cutting corners</h2>
        <p>
          Fewer services, fewer repos, fewer moving parts. The default shape is a monorepo with
          shared libraries and unified tooling, sized for low operational cost and low cognitive
          overhead — but with clear service boundaries so growth doesn{"'"}t require an emergency
          re-architecture.
        </p>

        <h2>Monorepo now, microservices later — on your terms</h2>
        <p>
          Start as one repo, one platform, many clearly-defined modules. When the team grows,
          split services out intentionally and deliberately, preserving interfaces rather than
          dying by a thousand migrations. Multi-repo support is additive: the same manifest model
          describes a service whether it lives in the monorepo or its own repository.
        </p>

        <h2>Change architecture once, then move forward</h2>
        <p>
          Structural change should be predictable, automatable, and fast — a planned transition,
          not a reactive pivot. Foundry treats the platform{"'"}s shape as data (the manifest) so
          that reshaping it is an edit, not a rewrite.
        </p>

        <h2>Developer experience as a force multiplier</h2>
        <p>
          A shared mental model — one manifest, one CLI, one deploy path — is how a small team
          avoids collapsing under its own weight. Faster onboarding and fewer footguns are a
          scaling strategy, not a luxury.
        </p>

        <h2>Non-goals</h2>
        <ul>
          <li>Not a framework lock-in — languages, runtimes, and providers are pluggable.</li>
          <li>Not microservices-first — distributed complexity is treated as a cost.</li>
          <li>Not a magic scalability button — it can{"'"}t fix product decisions.</li>
          <li>Not a hosted SaaS — Foundry is tooling and methodology you run yourself.</li>
        </ul>

        <p>
          Next: see how this maps to repositories in{" "}
          <a href="/docs/concepts/topology">Repo Topology</a>.
        </p>
      </div>
    </WikiLayout>
  );
}
