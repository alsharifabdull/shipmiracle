## Stack rules — API / backend service (TypeScript / Node)
- TypeScript strict, Node LTS, npm with lockfile. Framework chosen in DECISIONS (default: Fastify).
- Every endpoint: input validated with a schema, auth checked server-side, errors mapped to proper
  status codes, never a stack trace to the client. Log without personal data or secrets.
- Config and secrets only from environment (`.env` locally, never committed).
- Tests: `npm test` with unit tests for logic and one integration test per endpoint (supertest or
  fetch against a test server). Database through migrations with rollback.
- Health endpoint `/health`; version in the response. Dockerfile only when deployment needs it.
