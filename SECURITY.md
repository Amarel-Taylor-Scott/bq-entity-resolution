# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.2.x   | Yes       |
| < 0.2   | No        |

## Reporting a Vulnerability

If you discover a security vulnerability in bq-entity-resolution, please report it responsibly.

**Do NOT open a public GitHub issue for security vulnerabilities.**

### How to Report

1. Email your findings to the maintainers via the contact listed in `pyproject.toml`
2. Include a description of the vulnerability and steps to reproduce
3. If possible, include a proof-of-concept or test case

### What to Expect

- **Acknowledgment**: Within 48 hours of your report
- **Assessment**: Within 7 days we will assess severity and impact
- **Fix timeline**: Critical vulnerabilities will be patched within 14 days; lower severity within 30 days
- **Disclosure**: We will coordinate disclosure timing with you

### Scope

The following are in scope:
- SQL injection via config YAML values that bypass validation
- PII leakage in logs, error messages, or audit trails
- Authentication/authorization bypass in BigQuery operations
- Dependency vulnerabilities in direct dependencies
- Denial of service via resource exhaustion (unbounded loops, memory)

The following are out of scope:
- Vulnerabilities in BigQuery itself or Google Cloud infrastructure
- Issues requiring physical access to the deployment environment
- Social engineering attacks
- Vulnerabilities in optional development dependencies

## Security Architecture

- All user-supplied values are validated through `sql/utils.py` before SQL interpolation
- Config-level validation via Pydantic v2 field validators catches injection at load time
- Builder-level defense-in-depth re-validates at SQL generation time
- PII is redacted from SQL audit logs and exception messages
- Distributed locking uses fencing tokens to prevent stale-writer corruption
- Circuit breaker prevents cascading failures from BigQuery outages
