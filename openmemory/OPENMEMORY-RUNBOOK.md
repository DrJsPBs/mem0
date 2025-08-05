# OpenMemory API runbook: Redis vector store + Postgres DB + Neo4j graph

## Purpose and Scope
- Durable, repo-committed runbook to wire OpenMemory with:
  - Redis (vector store)
  - Postgres (primary DB)
  - Neo4j (graph)
- Audience: operators and developers bringing up OpenMemory in dev/staging/prod.
- Style: concise checklists, copy-pasteable commands, and clickable references to code and docs using the format [`filename OR language.declaration()`](relative/file/path.ext:line).

Anchors:
- [Checklist A — Environment and versions](#checklist-a--environment-and-versions)
- [Checklist B — Database initialization](#checklist-b--database-initialization)
- [Checklist C — Redis FT index & Neo4j constraints](#checklist-c--redis-ft-index--neo4j-constraints)
- [Checklist D — Start API and probes](#checklist-d--start-api-and-probes)
- [Checklist E — Configure LLM/Embedder/OpenMemory](#checklist-e--configure-llmembedderopenmemory)
- [Checklist F — Create and query memories](#checklist-f--create-and-query-memories)
- [Checklist G — Operational notes and guardrails](#checklist-g--operational-notes-and-guardrails)
- [Cutover plan and Acceptance criteria](#cutover-plan-and-acceptance-criteria)

---

## Checklist A — Environment and versions

### Version requirements
- Python 3.10+
- Postgres 14+ with pgvector extension if used elsewhere; not required for Redis flow
- Redis 7.2+ with RediSearch module (for FT index)
- Neo4j 5.x or AuraDB equivalent
- uvicorn/fastapi dependencies resolved via your environment

### Environment variables (examples)
- Core DB/Redis/Neo4j:
```
export DATABASE_URL="postgresql+psycopg2://openmemory:openmemory@localhost:5432/openmemory"
export REDIS_URL="redis://localhost:6379/0"
export NEO4J_URI="bolt://localhost:7687"
export NEO4J_USER="neo4j"
export NEO4J_PASSWORD="password"
```
- LLM/Embedding placeholders (override as needed):
```
export OPENAI_API_KEY="sk-..."
export EMBEDDING_MODEL="text-embedding-3-small"
export LLM_MODEL="gpt-4o-mini"
```

References for env parsing and defaults:
- [`python.DATABASE_URL`](openmemory/api/app/database.py:10)
- [`python.get_default_memory_config`](openmemory/api/app/utils/memory.py:139)
- [`python.get_default_memory_config`](openmemory/api/app/utils/memory.py:151)
- [`python._parse_environment_variables`](openmemory/api/app/utils/memory.py:162)

---

## Checklist B — Database initialization

- Alembic migration directory:
  - [`dir`](openmemory/api/alembic/versions/:1)

- Initialize/upgrade schema (from repo root or appropriate cwd):
```
alembic -c openmemory/api/alembic.ini upgrade head
```

- Development shortcut (avoid in production):
  - Note on dev create_all: [`python.Base.metadata.create_all(bind=engine)`](openmemory/api/main.py:25)
  - For local development, export the env flag to auto-create tables from models:
    ```
    export ENABLE_CREATE_ALL=true
    ```
    This gates the create_all call in [`python.FastAPI()`](openmemory/api/main.py:14). In production, do not set this flag and rely on Alembic migrations only.

---

## Checklist C — Redis FT index & Neo4j constraints

- Redis: create or verify RediSearch vector index (see production setup snippets):
  - [`markdown`](openmemory-production-setup.md:271)

- Neo4j: create constraints/indexes as required by graph features:
  - [`markdown`](openmemory-production-setup.md:287)

Example Redis CLI (adjust index/schema to your deployment):
```
redis-cli FT.CREATE memories_idx ON HASH PREFIX 1 "mem:" SCHEMA
  text TEXT
  user_id TAG
  app_id TAG
  vector VECTOR HNSW 6 TYPE FLOAT32 DIM 1536 DISTANCE_METRIC COSINE INITIAL_CAP 10000 M 16 EF_CONSTRUCTION 200
```

Example Neo4j constraints (adjust labels/props as used by OpenMemory graph):
```
cypher-shell -u "$NEO4J_USER" -p "$NEO4J_PASSWORD" -a "$NEO4J_URI" \
  'CREATE CONSTRAINT memory_id IF NOT EXISTS FOR (m:Memory) REQUIRE m.id IS UNIQUE;'
```

---

## Checklist D — Start API and probes

### Deep Readiness Checks

The API exposes minimal health endpoints by default:
- [`python`](openmemory/api/app/routers/health.py:1) mounted in [`python.FastAPI()`](openmemory/api/main.py:8)

By default, `/health/readiness` returns a minimal ready status without touching external systems. You can enable optional deeper connectivity checks using an environment flag.

Enable deep readiness:
```bash
export ENABLE_DEEP_READINESS=true
```

When enabled, the readiness endpoint will attempt:
- Redis
  - Connect using REDIS_URL and ping the server via [`python.aioredis.from_url().ping()`](openmemory/api/app/routers/health.py:33)
  - Optionally query RediSearch index info via [`python.Redis.execute_command("FT.INFO", collection)`](openmemory/api/app/routers/health.py:41)
    - If FT.INFO is unavailable or lacks permissions, ping success still counts as connectivity OK and `has_index` will be reported as false.
- Neo4j
  - Connect using NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD
  - Run a trivial query [`python.session.run("RETURN 1 AS ok")`](openmemory/api/app/routers/health.py:63)

Soft-dependency behavior:
- The checks use optional imports. If `redis` or `neo4j` Python packages are not installed and `ENABLE_DEEP_READINESS=true`, `/health/readiness` returns HTTP 503 with details indicating a missing dependency.
- If `ENABLE_DEEP_READINESS` is not set (or falsey), the endpoint does not perform these checks and continues to return a minimal ready response.

Safe by default:
- With the flag off, `/health/readiness` behaves minimally and will not fail due to Redis/Neo4j unavailability.

Sample usage:
```bash
export ENABLE_DEEP_READINESS=true
curl -i http://localhost:8000/health/readiness
```

- Start API (from repo root):
```
uvicorn openmemory.api.main:app --host 0.0.0.0 --port 8000 --reload
```

- Readiness probes:
  - Configuration endpoint implementation: [`python.get_configuration`](openmemory/api/app/routers/config.py:124)
  - Memories listing implementation: [`python.list_memories`](openmemory/api/app/routers/memories.py:101)

Quick checks:
```
curl -sS http://localhost:8000/api/v1/config/ | jq .
curl -sS 'http://localhost:8000/api/v1/memories/?limit=1' | jq .
```

- MCP SSE presence check:
  - Server setup: [`python.setup_mcp_server(app)`](openmemory/api/main.py:79)
  - SSE handler: [`python.handle_sse`](openmemory/api/app/mcp_server.py:377)
  - Post message handler: [`python.sse.handle_post_message`](openmemory/api/app/mcp_server.py:404)

Example SSE route probe (adjust path if required):
```
curl -i http://localhost:8000/api/v1/mcp/sse
```

---

## Checklist E — Configure LLM/Embedder/OpenMemory

Defaults and merge behavior references:
- Default config loader: [`python.get_default_memory_config`](openmemory/api/app/utils/memory.py:139)
- Default JSON: [`json`](openmemory/api/default_config.json:1)
- Override JSON: [`json`](openmemory/api/config.json:1)
- Client builder: [`python.get_memory_client`](openmemory/api/app/utils/memory.py:187)
- Reset hook: [`python.reset_memory_client()`](openmemory/api/app/routers/config.py:149)

Base URL:
```
BASE=http://localhost:8000
```

Config APIs:

- GET current config:
```
curl -sS "$BASE/api/v1/config/" | jq .
```

- PUT merge config (example: set models/keys):
```
curl -sS -X PUT "$BASE/api/v1/config/" \
  -H 'Content-Type: application/json' \
  -d '{
        "mem0": {
          "llm": { "provider": "openai", "model": "gpt-4o-mini" },
          "embedder": { "provider": "openai", "model": "text-embedding-3-small" }
        },
        "openmemory": {
          "vector_store": { "provider": "redis", "url": "'"$REDIS_URL"'" },
          "database": { "url": "'"$DATABASE_URL"'" },
          "graph": { "provider": "neo4j", "uri": "'"$NEO4J_URI"'", "user": "'"$NEO4J_USER"'", "password": "'"$NEO4J_PASSWORD"'" }
        }
      }' | jq .
```

- POST reset (reloads/clears cached client):
```
curl -sS -X POST "$BASE/api/v1/config/reset" | jq .
```

LLM sub-config:
- GET:
```
curl -sS "$BASE/api/v1/config/mem0/llm" | jq .
```
- PUT:
```
curl -sS -X PUT "$BASE/api/v1/config/mem0/llm" \
  -H 'Content-Type: application/json' \
  -d '{
        "provider": "openai",
        "model": "gpt-4o-mini"
      }' | jq .
```

Embedder sub-config:
- GET:
```
curl -sS "$BASE/api/v1/config/mem0/embedder" | jq .
```
- PUT:
```
curl -sS -X PUT "$BASE/api/v1/config/mem0/embedder" \
  -H 'Content-Type: application/json' \
  -d '{
        "provider": "openai",
        "model": "text-embedding-3-small"
      }' | jq .
```

OpenMemory sub-config:
- GET:
```
curl -sS "$BASE/api/v1/config/openmemory" | jq .
```
- PUT:
```
curl -sS -X PUT "$BASE/api/v1/config/openmemory" \
  -H 'Content-Type: application/json' \
  -d '{
        "vector_store": { "provider": "redis", "url": "'"$REDIS_URL"'" },
        "database": { "url": "'"$DATABASE_URL"'" },
        "graph": { "provider": "neo4j", "uri": "'"$NEO4J_URI"'", "user": "'"$NEO4J_USER"'", "password": "'"$NEO4J_PASSWORD"'" }
      }' | jq .
```

---

## Checklist F — Create and query memories

Routes and handlers:
- Create: [`python.create_memory`](openmemory/api/app/routers/memories.py:211)
- List: [`python.list_memories`](openmemory/api/app/routers/memories.py:101)
- Get by ID: [`python.get_memory`](openmemory/api/app/routers/memories.py:311)
- Filter: [`python.filter_memories`](openmemory/api/app/routers/memories.py:500)
- Related: [`python.get_related_memories`](openmemory/api/app/routers/memories.py:594)

Examples:

- Create a memory:
```
curl -sS -X POST "$BASE/api/v1/memories/" \
  -H 'Content-Type: application/json' \
  -d '{
        "text": "Alice prefers decaf coffee in the afternoon.",
        "user_id": "user_123",
        "app_id": "app_abc",
        "metadata": {"source":"runbook-test"}
      }' | jq .
```

- List memories:
```
curl -sS "$BASE/api/v1/memories/?limit=10&offset=0" | jq .
```

- Get by ID (replace {id}):
```
ID="&lt;copy-from-create-response&gt;"
curl -sS "$BASE/api/v1/memories/$ID" | jq .
```

- Filter by criteria (example):
```
curl -sS -X POST "$BASE/api/v1/memories/filter" \
  -H 'Content-Type: application/json' \
  -d '{
        "query": "decaf coffee",
        "user_id": "user_123",
        "limit": 5
      }' | jq .
```

- Related memories for an ID:
```
curl -sS "$BASE/api/v1/memories/$ID/related?limit=5" | jq .
```

---

## Checklist G — Operational notes and guardrails

- Health endpoints: status (not implemented). Reference discussion:
  - [`markdown`](openmemory/ARCHITECTURE-REVIEW.md:124)

- Production DB lifecycle:
  - Use Alembic migrations only; avoid `create_all` in production.
  - Backups: enable scheduled Postgres backups. Test restore drills.
  - Apply schema changes via CI/CD with migration gating.

- Redis/Neo4j provisioning responsibilities:
  - Redis: ensure RediSearch module and persistence strategy (RDB/AOF) per SLOs.
  - Neo4j: ensure appropriate role/permissions, memory, and constraint migrations.
  - For exact setup snippets, see:
    - Redis index: [`markdown`](openmemory-production-setup.md:271)
    - Neo4j constraints: [`markdown`](openmemory-production-setup.md:287)

- MCP SSE routes summary:
  - SSE initialization: [`python.setup_mcp_server(app)`](openmemory/api/main.py:79)
  - SSE handler entrypoints:
    - [`python.handle_sse`](openmemory/api/app/mcp_server.py:377)
    - [`python.sse.handle_post_message`](openmemory/api/app/mcp_server.py:404)

- Env placeholder strategy and cache/reset behavior:
  - Env parsing/merge: [`python._parse_environment_variables`](openmemory/api/app/utils/memory.py:162)
  - Client caching and rebuild: [`python.get_memory_client`](openmemory/api/app/utils/memory.py:261)
  - Reset endpoint: [`python.reset_memory_client()`](openmemory/api/app/routers/config.py:149)

---

## Cutover plan and Acceptance criteria

Cutover plan (timestamps are operator-provided):
- T-60m: Provision/validate Redis with FT index and Neo4j with constraints.
- T-45m: Run Alembic to latest on Postgres.
- T-30m: Configure API config via PUT /api/v1/config/ with Redis/DB/Neo4j params.
- T-20m: Restart API, then POST /api/v1/config/reset to rebuild cached clients.
- T-15m: Readiness probes (GET /api/v1/config/, GET /api/v1/memories/?limit=1).
- T-10m: Functional verify: create memory, list, filter, related.
- T-5m: Enable traffic/consumers.

Acceptance criteria:
- Config readiness:
  - GET /api/v1/config/ returns merged values reflecting Redis URL, Postgres URL, and Neo4j credentials.
  - Handlers present: [`python.get_configuration`](openmemory/api/app/routers/config.py:124), [`python.get_memory_client`](openmemory/api/app/utils/memory.py:187), [`python.get_default_memory_config`](openmemory/api/app/utils/memory.py:139), [`json`](openmemory/api/config.json:1).
- Memories readiness:
  - POST /api/v1/memories/ succeeds and returns an ID using [`python.create_memory`](openmemory/api/app/routers/memories.py:211).
  - GET /api/v1/memories/ reflects inserted memory via [`python.list_memories`](openmemory/api/app/routers/memories.py:101).
  - GET /api/v1/memories/{id} works via [`python.get_memory`](openmemory/api/app/routers/memories.py:311).
  - POST /api/v1/memories/filter returns relevant results via [`python.filter_memories`](openmemory/api/app/routers/memories.py:500).
  - GET /api/v1/memories/{id}/related returns related items via [`python.get_related_memories`](openmemory/api/app/routers/memories.py:594).
- SSE presence:
  - SSE endpoints reachable; handlers present at [`python.setup_mcp_server(app)`](openmemory/api/main.py:79), [`python.handle_sse`](openmemory/api/app/mcp_server.py:377), [`python.sse.handle_post_message`](openmemory/api/app/mcp_server.py:404).
