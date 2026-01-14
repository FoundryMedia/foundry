# [Foundry](https://foundry-dev.com) · [![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](#) [![npm version](https://img.shields.io/npm/v/foundry.svg)](#) [![PRs](https://img.shields.io/badge/PRs-encouraged-purple.svg)](#)

---

## Overview

Foundry is a modern, declarative framework for building web2 platforms, full-stack applications, and more — using a single manifest (`foundry.json`) to describe the structure of your entire platform. It automates project scaffolding, configuration, and orchestration so you can spend your time building features instead of setup.

It’s designed for solo developers or small teams who want to move fast now — but still build something that can scale later. You start simple (monorepo + unified structure), and as your project grows, Foundry supports evolving into a modular, microservices-ready architecture.

---

## Philosophy & Goals

- **Declarative first** — Define services, modules, dependencies, and configurations via `foundry.json`. No more hand-crafting boilerplate or build scripts from scratch.  
- **Simple start, scalable growth** — Begin with a monorepo to share code easily; when the time comes, break out parts into separate services or modules without rewriting everything.  
- **Developer experience (DevX)–centric** — Reduce friction in project setup, onboarding, and structural changes. Let developers focus on business logic, not plumbing.  
- **Flexible but structured defaults** — Provide convention-driven defaults so you don’t waste time deciding how to organize code — but stay flexible enough to evolve as your needs change.  

---

## What Foundry Provides / Plans to Provide

- A **manifest-driven project model** via `foundry.json` — define modules, services, dependencies, and project structure in one place.  
- **Automatic scaffolding & project generation** — boilerplate, directory structure, configuration files, templates — all generated based on your manifest.  
- **Orchestration support** — manage inter-service dependencies, builds, and project structure as your platform grows.  
- **Scalable defaults** — starting simple but designed for growth into microservices or modular architecture.  
- (Future) **CLI tooling to aid transitions** — especially useful when migrating from monorepo to microservices, or adjusting service boundaries.  

---

## When to Use Foundry

Use Foundry if you’re building a full-stack web application (frontend + backend, possibly more), and you:  
- Want to start quickly and move fast.  
- Are a solo developer or small team, but expect growth in features, complexity, or contributors.  
- Prefer sane defaults and structure over reinventing folder layouts, build configs, or module boundaries.  
- Value developer ergonomics, fast iteration, and scalability over time.
---

## Installation

### Option 1: Windows Installer (Recommended)

Download the latest installer from [GitHub Releases](https://github.com/FoundryMedia/foundry/releases/latest) and run the setup wizard. This will:
- Install the Foundry CLI to `%LOCALAPPDATA%\Foundry`
- Add `foundry` to your PATH automatically

After installation, open a new terminal and verify:
```bash
foundry --version
```

### Option 2: Install from Source (pip)

Requires **Python 3.9+**.

```bash
# Clone the repository
git clone https://github.com/FoundryMedia/foundry.git
cd foundry/cli

# Install in development/editable mode
pip install -e .

# Or install directly (non-editable)
pip install .
```

Verify the installation:
```bash
foundry --version
```

#### Installing from GitHub directly (without cloning)

```bash
pip install git+https://github.com/FoundryMedia/foundry.git#subdirectory=cli
```

### Updating

**Installer users**: Download and run the latest installer from [GitHub Releases](https://github.com/FoundryMedia/foundry/releases/latest).

**pip users**: 
```bash
cd foundry/cli
git pull
pip install -e .
```