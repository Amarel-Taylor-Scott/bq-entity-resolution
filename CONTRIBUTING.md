# Contributing to bq-entity-resolution

Thank you for your interest in contributing! This guide covers everything you need to get started.

## Development Setup

```bash
# Clone the repository
git clone https://github.com/bq-entity-resolution/bq-entity-resolution.git
cd bq-entity-resolution

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows

# Install with dev and local test dependencies
pip install -e ".[dev,local]"

# Install pre-commit hooks
pip install pre-commit
pre-commit install
```

## Running Tests

```bash
# Run all tests
python -m pytest tests/ -v

# Run with coverage
python -m pytest tests/ --cov=bq_entity_resolution --cov-report=term-missing

# Run specific test file
python -m pytest tests/unit/config/test_schema.py -v

# Run integration tests only
python -m pytest tests/integration/ -v
```

### BigQuery Emulator Tests

Some integration tests require a running BigQuery emulator:

```bash
# Start the emulator
docker compose --profile test up -d bq-emulator

# Run emulator tests
BQEMU_HOST=localhost python -m pytest tests/integration/test_bqemu_backend.py -v

# Stop the emulator
docker compose --profile test down
```

## Code Quality

```bash
# Lint
python -m ruff check src/ tests/

# Auto-fix lint issues
python -m ruff check --fix src/ tests/

# Format
python -m ruff format src/ tests/

# Type check
python -m mypy src/
```

## Making Changes

1. **Fork** the repository and create a feature branch from `main`.
2. **Write tests** for your changes. All new features and bug fixes should include tests.
3. **Run the full test suite** to make sure nothing is broken.
4. **Run linting and type checking** to ensure code quality.
5. **Submit a pull request** with a clear description of your changes.

## Adding Feature Functions

Add a decorated function in `src/bq_entity_resolution/features/registry.py`:

```python
@register("my_feature")
def my_feature(inputs: list[str], **_: Any) -> str:
    """Short description of what the feature does."""
    col = inputs[0]
    return f"UPPER(TRIM({col}))"
```

Then add a test entry in `tests/integration/test_feature_execution.py` to verify it executes in DuckDB.

## Adding Comparison Functions

Add a decorated function in `src/bq_entity_resolution/matching/comparisons.py`:

```python
@register("my_comparison")
def my_comparison(left: str, right: str, threshold: float = 0.8, **_: Any) -> str:
    """Short description of the comparison."""
    return f"(my_func(l.{left}, r.{right}) >= {threshold} AND l.{left} IS NOT NULL)"
```

Then add a test entry in `tests/integration/test_comparison_execution.py`.

## Project Structure

```
src/bq_entity_resolution/
    config/          # YAML schema, loader, presets, validation
    features/        # Feature function registry and engine
    blocking/        # Blocking key engine and metrics
    matching/        # Comparison functions, scoring, Fellegi-Sunter
    reconciliation/  # Clustering, canonical election, gold output
    pipeline/        # DAG, orchestrator, executor, diagnostics
    sql/             # Jinja2 templates, SQL builders, expression helpers
    backends/        # BigQuery, DuckDB, BQ emulator backends
    stages/          # Pipeline stage abstractions
    watermark/       # Incremental processing watermarks
    clients/         # BigQuery client with retry logic
```

## Pull Request Guidelines

- Keep PRs focused on a single concern.
- Update documentation if you change public APIs or add features.
- Add entries to the test maps in `test_comparison_execution.py` / `test_feature_execution.py` for new functions.
- Follow existing code style (enforced by ruff).
- Ensure all tests pass and type checking is clean.

## Reporting Issues

- Use [GitHub Issues](https://github.com/bq-entity-resolution/bq-entity-resolution/issues) for bug reports and feature requests.
- Include your Python version, package version, and a minimal config that reproduces the issue.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
