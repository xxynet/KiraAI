# Contributing to KiraAI

First off, thank you for considering contributing to **KiraAI**! Every contribution helps make this project better. This document provides guidelines and information to make the contribution process smooth and effective.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [How to Contribute](#how-to-contribute)
  - [Reporting Bugs](#reporting-bugs)
  - [Suggesting Features](#suggesting-features)
  - [Submitting Changes](#submitting-changes)
- [Development Setup](#development-setup)
- [Coding Guidelines](#coding-guidelines)
- [Commit Messages](#commit-messages)
- [Pull Request Process](#pull-request-process)
- [License](#license)

---

## Code of Conduct

By participating in this project, you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md). Please read it before contributing.

---

## Getting Started

1. **Fork** the repository on GitHub.
2. **Clone** your fork locally:
   ```bash
   git clone https://github.com/<your-username>/KiraAI.git
   cd KiraAI
   ```
3. **Create a branch** for your work:
   ```bash
   git checkout -b feature/your-feature-name
   ```
4. **Set up** the development environment (see [Development Setup](#development-setup)).

---

## How to Contribute

### Reporting Bugs

Before opening a new issue, please **[search existing issues](https://github.com/xxynet/KiraAI/issues)** to check if the same bug has already been reported. If you find an existing issue that matches yours, add your information as a comment instead of creating a duplicate.

If no existing issue covers your bug, [open a new issue](https://github.com/xxynet/KiraAI/issues/new) with:

- A **clear and descriptive title**.
- Steps to **reproduce** the problem.
- **Expected** vs. **actual** behavior.
- Your **environment details** (OS, Python version, relevant package versions).
- Any **error logs** or screenshots that help illustrate the issue.

### Suggesting Features

Before suggesting a new feature, please **[search existing issues](https://github.com/xxynet/KiraAI/issues)** to see if the same idea has already been proposed. If so, add your thoughts as a comment to join the discussion.

If your idea hasn't been proposed yet, feel free to open an issue. When proposing a new feature:

- Explain the **problem** it solves or the **use case** it enables.
- Describe the **proposed solution** as concretely as possible.
- Mention any **alternatives** you've considered.

### Submitting Changes

1. Ensure your code follows the [Coding Guidelines](#coding-guidelines).
2. Write or update **tests** as needed.
3. Update **documentation** if your change affects public behavior.
4. Submit a **pull request** (see [Pull Request Process](#pull-request-process)).

---

## Development Setup

### Prerequisites

- **Python 3.10+**
- **Node.js 18+** and **npm** (for the WebUI frontend)
- **Git**

### Backend

```bash
# Create and activate a virtual environment (recommended)
python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Frontend (WebUI)

```bash
cd webui/frontend
npm install
npm run build
```

For frontend development with hot-reload:

```bash
npm run dev
```

The Vite dev server starts on `:3000` and proxies API requests to the Python backend on `:5267`.

### Docker (optional)

```bash
docker compose up --build
```

---

## Coding Guidelines

### Python

- Follow [PEP 8](https://peps.python.org/pep-0008/) style conventions.
- Use **type hints** where practical.
- Write **docstrings** for public classes and functions (Google or NumPy style).
- Keep functions **focused** — each function should do one thing well.
- Avoid circular imports; prefer dependency injection or lazy imports.

### JavaScript / Vue (Frontend)

- Follow the existing ESLint configuration.
- Use **Composition API** (`<script setup>`) for Vue 3 components.
- Keep components **small and reusable**.

### General

- **No hardcoded secrets** — use environment variables or config files.
- Write meaningful **comments** for complex logic, but prefer self-documenting code.
- Remove **debug prints** and **commented-out code** before submitting.

---

## Commit Messages

Write clear, concise commit messages. We recommend the [Conventional Commits](https://www.conventionalcommits.org/) format:

```
<type>(<scope>): <short description>

<optional body>

<optional footer>
```

**Types:**

| Type       | Description                              |
|------------|------------------------------------------|
| `feat`     | A new feature                            |
| `fix`      | A bug fix                                |
| `docs`     | Documentation only                       |
| `style`    | Code style (formatting, no logic change) |
| `refactor` | Code restructuring (no feature or fix)   |
| `test`     | Adding or updating tests                 |
| `chore`    | Build, CI, or tooling changes            |

**Examples:**

```
feat(adapter): add Telegram sticker support
fix(llm-client): handle timeout on streaming responses
docs(readme): update setup instructions for Docker
```

---

## Pull Request Process

> **Important:** All pull requests must be submitted to the **`dev`** branch. PRs targeting `main` will not be accepted.

1. **Update your branch** with the latest `dev` before submitting:
   ```bash
   git fetch upstream
   git rebase upstream/dev
   ```
2. **Fill out the PR description** — explain *what* you changed and *why*.
3. **Link related issues** (e.g., `Closes #123`).
4. Ensure all **checks pass** (linters, tests, etc.).
5. Request a **review** from a maintainer.
6. Be responsive to **feedback** — we may ask for changes.

---

## License

By contributing to KiraAI, you agree that your contributions will be licensed under the [GNU Affero General Public License v3.0](LICENSE).
