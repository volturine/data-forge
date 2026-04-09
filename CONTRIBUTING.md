# Contributing to Data-Forge Analysis Platform

First off, thank you for considering contributing to Data-Forge! It's people like you that make this tool better for everyone.

## Table of Contents

- [Getting Started](#getting-started)
- [Development Environment](#development-environment)
- [How to Contribute](#how-to-contribute)
- [Pull Request Process](#pull-request-process)
- [Coding Standards](#coding-standards)
- [Testing](#testing)
- [Documentation](#documentation)
- [Community](#community)

## Getting Started

### Prerequisites

Before you begin, ensure you have the following installed:

- **Python 3.11+** — Backend runtime
- **Node.js 18+** or **Bun** — Frontend runtime (we recommend Bun)
- **uv** — Python package manager ([install](https://github.com/astral-sh/uv))
- **just** — Command runner ([install](https://github.com/casey/just))
- **Docker** (optional) — For containerized development/deployment

You can run the prerequisites script for Ubuntu/Debian:

```bash
./prerequisites.sh
```

### Quick Setup

```bash
# Clone the repository
git clone https://github.com/your-username/polars-fastapi-svelte.git
cd polars-fastapi-svelte

# Install dependencies
just install

# Copy environment file
cp backend/.env.example backend/.env

# Start development servers
just dev
```

Frontend: http://localhost:3000
Backend API: http://localhost:8000

## Development Environment

### Package Managers

- **Frontend**: `bun` — use `bun add <package>` to install packages
- **Backend**: `uv` — use `uv add <package>` to install packages

⚠️ Never edit `package.json` or `pyproject.toml` directly. Use the package managers.

### Useful Commands

```bash
just dev              # Start both servers with hot-reload
just format           # Format all code (ruff + prettier)
just check            # Run linters and type checks
just test             # Run all tests
just test-e2e         # Run end-to-end tests
just verify           # Full verification gate (required before PR)
```

### IDE Setup

We recommend VS Code with the following extensions:

- **Svelte for VS Code** — Svelte language support
- **ESLint** — JavaScript/TypeScript linting
- **Prettier** — Code formatting
- **Ruff** — Python linting and formatting
- **Pylance** — Python language server

## How to Contribute

### Reporting Bugs

Before creating a bug report, please check existing issues. When creating a bug report, include:

1. **Summary** — A clear and concise description
2. **Steps to reproduce** — Detailed steps to reproduce the behavior
3. **Expected behavior** — What you expected to happen
4. **Actual behavior** — What actually happened
5. **Environment** — OS, browser, Python/Node versions
6. **Screenshots/logs** — If applicable

### Suggesting Features

We welcome feature suggestions! Please:

1. Check if the feature has already been requested
2. Provide a clear use case
3. Explain why this feature would be useful to most users
4. Consider if it fits with the project's local-first, no-code philosophy

### Your First Code Contribution

Looking for a place to start? Check issues labeled:

- `good first issue` — Good for newcomers
- `help wanted` — Extra attention needed
- `documentation` — Documentation improvements

### Working on an Issue

1. Comment on the issue to let others know you're working on it
2. Fork the repository
3. Create a feature branch: `git checkout -b feature/your-feature-name`
4. Make your changes
5. Run `just verify` to ensure all checks pass
6. Submit a pull request

## Pull Request Process

### Before Submitting

1. **Run `just verify`** — This is mandatory and must pass
2. **Write tests** — Add tests for new functionality
3. **Update documentation** — If you changed APIs or behavior
4. **Keep changes focused** — One feature/fix per PR

### PR Guidelines

1. Use a clear, descriptive title
2. Reference any related issues (`Fixes #123`)
3. Describe what changed and why
4. Include screenshots for UI changes
5. Ensure CI passes

### Review Process

1. A maintainer will review your PR
2. Address any requested changes
3. Once approved, a maintainer will merge your PR

## Coding Standards

### General

- Write clear, self-documenting code
- Prefer `const` over `let`
- Use early returns instead of `else`
- Handle errors at boundaries, not everywhere

### Frontend (TypeScript/Svelte)

- All Svelte components must have `lang="ts"` on the `<script>` tag
- Use Svelte 5 runes (`$state`, `$derived`, `$effect`, `$props`)
- Use Panda CSS for styling — no inline styles or raw hex values
- Never use `transition-all` — specify properties explicitly
- Avoid `as any` type assertions

### Backend (Python)

- FastAPI async patterns throughout
- Pydantic V2 models for all schemas
- SQLAlchemy 2.0 async sessions
- Use Polars for data processing (not pandas)
- Follow Google docstring convention

### File Naming

- Python: `snake_case.py`
- TypeScript: `kebab-case.ts`
- Svelte components: `PascalCase.svelte`

See [STYLE_GUIDE.md](STYLE_GUIDE.md) for complete details.

## Testing

### Backend Tests

```bash
cd backend
uv run pytest                    # Run all tests
uv run pytest tests/test_foo.py  # Run specific test file
uv run pytest -k "test_name"     # Run tests matching name
```

### Frontend Tests

```bash
cd frontend
bun run test:unit                # Run unit tests
bun run test:e2e                 # Run e2e tests (requires servers)
```

### Writing Tests

- Backend: Write pytest tests in `backend/tests/`
- Frontend: Write Vitest tests alongside components as `*.test.ts`
- E2E: Write Playwright tests in `frontend/tests/`

## Documentation

Good documentation is crucial. When contributing:

- Update READMEs if behavior changes
- Add docstrings to new functions
- Update `ENV_VARIABLES.md` for new config options
- Update `docs/PRD.md` for architectural changes

## Community

### Getting Help

- **Issues** — For bugs and feature requests
- **Discussions** — For questions and ideas

### Recognition

Contributors are recognized in:

- GitHub contributors page
- Release notes for significant contributions

---

Thank you for contributing! 🎉
