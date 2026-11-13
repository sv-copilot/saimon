# Security policy

## Reporting a vulnerability

Open a private security advisory on this repository (Security → Report a
vulnerability). Please do not open a public issue for anything that would put running
deployments at risk.

Include the affected service and version, a reproduction, and the impact you believe it
has. Expect an acknowledgement within a few days; this is a small project and there is
no paid bounty.

## Supported versions

The project is pre-1.0. Security fixes land on `main` and are tagged; only the latest
tag is supported.

## Design notes relevant to security

- **Every service authenticates independently.** There is no shared gateway in front of
  the MCP services: each validates `X-Saimon-API-Key` itself, and the value may be a
  comma-separated list so that several callers can be distinguished in the audit log
  by key hash.
- **Universe scoping is enforced server-side.** Content belongs to a universe
  (`reality`, `fiction`, `personal`). A private universe requires an owner; without one
  the service returns an empty scope rather than falling back to public content.
- **Degraded means empty.** When a datastore is unreachable the API returns
  `status: degraded` with no rows. It never synthesises placeholder data — a fabricated
  row is indistinguishable from a real one downstream.
- **No shadow libraries.** The project does not ship adapters for Sci-Hub, LibGen or
  Anna's Archive. Ingest is limited to URLs the caller is entitled to read, and there
  is an SSRF guard on the ingest path.
- **Secrets are environment-only.** No credential is committed; `.env` is ignored and
  `.env.example` carries placeholders.
