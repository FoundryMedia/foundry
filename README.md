# [Foundry](https://foundry-dev.com) · [![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](#) [![Wiki](https://img.shields.io/badge/Wiki-foundry--dev.com-blue.svg)](https://foundry-dev.com) [![PRs](https://img.shields.io/badge/PRs-encouraged-purple.svg)](#)

---

## Overview

Foundry is a modern, declarative framework for building web2 platforms, full-stack applications, and more — using a single manifest (`foundry.json`) to describe the structure of your entire platform. It automates project scaffolding, configuration, and orchestration so you can spend your time building features instead of setup.

It’s designed for solo developers or small teams who want to move fast now — but still build something that can scale later. You start simple (monorepo + unified structure), and as your project grows, Foundry supports evolving into a modular, microservices-ready architecture.

---

## Philosophy & Goals

Foundry is opinionated about *how platforms should grow* — not just how they start.

The core belief is simple:

> **Build lean early without painting yourself into a corner later.**

Foundry exists to help solo developers and small teams move fast **without gambling on their future**.

### Lean by Default (Without Cutting Corners)

Early-stage platforms should minimize **operational cost and cognitive overhead**:
- Fewer services
- Fewer repositories
- Fewer moving parts

Foundry encourages:
- A **monorepo-first approach**
- Shared libraries and unified tooling
- Infrastructure choices that are cost-efficient at low usage

Lean does *not* mean fragile.  
Every architectural decision should assume success.

### Always Plan for Success

Foundry assumes that usage *can* and *will* spike.

Because of that, platforms built with Foundry are designed with:
- **Auto-scaling infrastructure** in mind from day one
- Clear service boundaries, even when everything lives in one repo
- Deployment and orchestration patterns that don’t require emergency re-architecture

You should never have to pause feature development just to survive growth.

### Monorepo Now, Microservices Later — On Your Terms

Foundry’s default posture is:
- **One repo**
- **One platform**
- **Many clearly defined modules**

As long as the team is small, this keeps velocity high and coordination cheap.

When growth demands it — more contributors, more load, more isolation — Foundry is designed so you can:
- Split services out **intentionally and all at once**
- Preserve interfaces, contracts, and structure
- Avoid death-by-a-thousand incremental migrations

The goal is a clean inflection point, not perpetual churn.

### Change Architecture Once — Then Move Forward

Foundry exists to make structural change:
- **Predictable**
- **Automatable**
- **Fast**

So that when the time comes to expand your team or service footprint:
- The transition is planned, not reactive
- The company can immediately refocus on **product, retention, and user needs**
- Core infrastructure and operations remain boring — by design

### Developer Experience as a Force Multiplier

Good developer experience is not a luxury.

Foundry treats DevX as a scaling strategy:
- Faster onboarding
- Fewer footguns
- Clear project shape
- Shared mental models

This is how small teams build systems that don’t collapse under their own weight.

---

## Non-Goals

Foundry is intentionally *not* trying to solve everything.

### Foundry Is Not a Framework Lock-In

- Foundry does not dictate languages, runtimes, or cloud providers
- You can replace pieces over time
- You can outgrow Foundry entirely

Foundry should never trap you.

### Foundry Is Not Microservices-First

- Foundry does **not** encourage premature microservices
- Complexity is treated as a cost, not a badge of maturity
- Microservices are a scaling tool — not a starting point

If your team is small, Foundry assumes your architecture should be too.

### Foundry Is Not a Magic Scalability Button

- Foundry cannot fix poor product decisions
- Foundry cannot guarantee adoption
- Foundry cannot eliminate tradeoffs

It exists to make *good decisions easier*, not automatic.

### Foundry Is Not a Hosted Platform (By Default)

- Foundry is tooling, methodology, and structure
- It may power hosted services
- It does not require one

You own your infrastructure, your data, and your destiny.

### Foundry Is Not Finished

- The philosophy is evolving
- The tooling is evolving
- The documentation is evolving

This is intentional.

Foundry reflects real systems, built in the open, and refined through use — not theory.

---

## Manifest Schema (v0.3.0)

The `foundry.json` manifest is the single source of truth for a platform's shape. As of
schema v0.3.0, services are **lean** — operational config (ports, commands, env vars) lives
in `.foundry/runtime.yml`, not the manifest.

| Section | Purpose |
|---------|--------|
| `name`, `repository` | Platform identity (name → slug → prefix auto-derivation) |
| `ecosystem` | GitHub org, prefix, cross-repo discovery, api-lib coordinates |
| `databases` | Liquibase-managed database schemas per service |
| `services` | Lean: `kind`, `type`, `role`, `database`, `apiLibModule` |
| `ci` | IaC tool (OpenTofu), provider, pipeline path |

The schema lives at [`foundry.schema.json`](./foundry.schema.json).

Full documentation: **[foundry-dev.com](https://foundry-dev.com)**

## Installation

### Option 1: Windows Installer (Recommended)

Download the latest installer from [GitHub Releases](https://github.com/FoundryMedia/foundry/releases/latest) and run the setup wizard. This will:
- Install the Foundry CLI to `Program Files\Foundry CLI`
- Add `foundry` to your system PATH automatically

After installation, open a **new** terminal and verify:
```bash
foundry --version
```

### Option 2: Manual Install (Portable)

1. Download `foundrycli-{version}-windows-amd64.zip` from [GitHub Releases](https://github.com/FoundryMedia/foundry/releases/latest)
2. Extract to your preferred location (e.g., `C:\Tools\Foundry`)
3. Add that location to your system PATH

Verify the installation:
```bash
foundry --version
```

### Option 3: Install from Source (Development)

> **Note:** Only recommended if you're contributing to Foundry development.

Requires **Python 3.9+**.

```bash
# Clone the repository
git clone https://github.com/FoundryMedia/foundry.git
cd foundry/cli

# Install in development/editable mode
pip install -e .
```

Verify the installation:
```bash
foundry --version
```

### Updating

The Foundry CLI will notify you when updates are available.

**Installer/Manual users**: Download the latest release from [GitHub Releases](https://github.com/FoundryMedia/foundry/releases/latest).

**Source users**: 
```bash
cd foundry/cli
git pull
pip install -e .
```

## Contributions
Foundry is in its earliest stages of development. It's nothing more than a DevX CLI. Little to no developers are finding it to see its value. If we receive enough feedback, we'll formalize a process.
For now, anyone wanting to fix issues or add features should reach out on [discord](https://discord.gg/k7aEcGUCUM) to discuss changes.
