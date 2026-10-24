# Security

Tax-Planning-Ops stores client tax figures. Please report vulnerabilities in private, and please do not include a real return.

## Reporting

Do not open a public GitHub issue, pull request, or discussion for a vulnerability.

Use GitHub private vulnerability reporting on this repository:

[https://github.com/Unicorn-Commander/Tax-Planning-Ops/security/advisories/new](https://github.com/Unicorn-Commander/Tax-Planning-Ops/security/advisories/new)

Include the version you ran, the request path, and a way to reproduce the problem on data you are allowed to share. Give the maintainers time to fix it before any public write-up.

## Scope

This policy covers the code in this repository, including the MCP server under `mcp/`. Defects in Python, Node.js, Postgres, Keycloak, or Garage belong with those projects as well when the bug is in the dependency.

## Secrets and client data

- Do not put passwords, tokens, or real taxpayer documents in an issue, pull request, test, or screenshot.
- Keep `.env` out of git. `deploy/.env.example` shows names, not live secrets.
- `STANDALONE_MODE=true` is a development bypass. The process refuses to start when `ENV=prod`.
- Uploads must look like a PDF and are capped at 25 MB. Outside standalone mode, access tokens must carry `aud`, `exp`, `iat`, and `iss`.
- The audit journal is append-only for the runtime database role: the migration grants `SELECT` and `INSERT`, and does not grant `UPDATE` or `DELETE`.
