# Contributing to Coralogix OTel Logger

First off, thank you for considering contributing! This project is maintained by and for engineers who want reliable, production-grade telemetry.

Whether it's a bug fix, a new feature, or a documentation update, your help is welcome.

## How to Contribute

### 1. Reporting Bugs
If you find a bug, please open an issue on GitHub. Include:
* Your operating system and Python version.
* A minimal, reproducible code example.
* The expected behavior vs. the actual behavior.

### 2. Suggesting Enhancements
Want to add a feature? Open an issue first to discuss it.

This ensures nobody duplicates work and that the feature aligns with the core goal of the project (stable, enterprise-ready logging).

### 3. Submitting Pull Requests
1. Fork the repository and create your branch from `main`.
2. Clone your fork locally.
3. Build and verify your development environment:

  On Linux or macOS, use the provided automated build wrapper script which sets up your virtual environment, updates dependencies, and compiles the codebase cleanly:
   ```bash
   chmod +x build.sh
   ./build.sh
	 ```

  On Windows (Command Prompt/PowerShell), execute the lifecycle steps manually:
	 ```py
	 python -m venv venv
   venv\Scripts\activate
   pip install --upgrade pip
   pip install build twine
   python -m build
	 ```

4. Write your code.

5. Ensure your code follows PEP 8 standards. If you are adding a new feature, please include comments explaining the "why" behind the logic.

6. Commit your changes with clear, descriptive commit messages.

7. Push to your fork and submit a Pull Request to the main branch.

## Development Guidelines
- Do not break the OTel Singleton: If you are modifying the constructor or connection logic, ensure _provider_initialized logic remains intact.

- Schema Strictness: Any modifications to the payload parsers (lib/utils.py equivalents) must maintain a flat/predictable dictionary structure to avoid Elasticsearch mapping conflicts.

- Keep it Lightweight: Avoid adding heavy third-party dependencies unless absolutely necessary.

Thank you for helping make open-source observability better!
