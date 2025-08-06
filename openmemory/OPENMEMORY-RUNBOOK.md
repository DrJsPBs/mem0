# OpenMemory Deployment Guide – Redis Vector DB, PostgreSQL (pgvector), and Neo4j Graph

This guide replaces prior runbooks and is the single source of truth for deploying OpenMemory with:
- Redis (RediSearch) as the vector database
- PostgreSQL with pgvector for structured storage (and optional vector columns)
- Neo4j for the graph store

It explicitly documents differences vs upstream defaults (commonly Qdrant/SQLite) and this repository’s forked defaults. It aligns with the corrective analysis in [markdown](openmemory/Codebase&#32;review&#32;task.md:1) and the architectural findings in [markdown](openmemory/ARCHITECTURE-REVIEW.md:1), and reflects how the code reads configuration and exposes health/readiness behavior.

Cross-references to code:
- Default memory config: [python.get_default_memory_config()](openmemory/api/app/utils/memory.py:139)
- Environment resolver: [python._parse_environment_variables()](openmemory/api/app/utils/memory.py:162)
- Config handlers: [python.get_configuration](openmemory/api/app/routers/config.py:124), [python.update_configuration](openmemory/api/app/routers/config.py:124), [python.reset_configuration](openmemory/api/app/routers/config.py:124)
- Health and readiness router: [python](openmemory/api/app/routers/health.py:1); deep readiness: [python.readiness()](openmemory/api/app/routers/health.py:59)
- MCP SSE mounting: [python.setup_mcp_server(app)](openmemory/api/main.py:79); handler: [python.handle_sse](openmemory/api/app/mcp_server.py:377)
- Create-all guard: [python.FastAPI()](openmemory/api/main.py:14)

---

## Why this guide

OpenMemory upstream examples often assume Qdrant for vectors and SQLite for structured data. This guide standardizes instead on:
- Redis Stack (RediSearch) for vector similarity (HNSW or FLAT)
- PostgreSQL with pgvector for relational + optional vector columns
- Neo4j for graph relationships

All examples, environment variables, and API payloads herein are aligned to these providers and to the current code behavior and handlers.

---

## Prerequisites

Recommended versions and tooling for Development vs Production:

- Python: 3.10+
- OpenMemory API: installable with mem0 and graph extras
- Required Python packages (for local API runs):
  - redis
  - redisvl
  - psycopg2-binary (or psycopg2 in production environments)
  - neo4j
- Docker and Docker Compose
- Network ports:
  - API: 8765 (assumed throughout this guide)
  - Redis: 6379 (plus 8001 for RedisInsight if desired)
  - PostgreSQL: 5432
  - Neo4j: 7474 (HTTP), 7687 (Bolt)

Install required packages locally:
```bash
pip install -U "mem0[graph]" redis redisvl psycopg2-binary neo4j
```

Note: In production, prefer `psycopg2` (source build) if required by your environment. `psycopg2-binary` is convenient for development.

---

## Service Architecture

Components and roles:
- API: OpenMemory backend service exposing REST and SSE endpoints for configuration, memory operations, health/readiness, and MCP.
- UI: OpenMemory web UI consuming the API for configuration and memory management.
- Redis (Redis Stack with RediSearch): vector similarity index (HNSW or FLAT). Stores embeddings keyed by collection.
- PostgreSQL (with pgvector): primary relational store (entities, memories, metadata). pgvector enables vector columns where applicable.
- Neo4j: graph store for relationships between entities and memories.

---

## Preparing the databases

### Redis (RediSearch) – create FT index

Use Redis Stack (includes RediSearch). The vector field dimension DIM must match your embedder’s output dimension.

Common OpenAI models and dims:
- text-embedding-3-small: 1536
- text-embedding-3-large: 3072

Example FT.CREATE with HNSW on vector field `embedding` (assumes DIM=1536):

```bash
# Example schema: HASH with fields: id, text, user_id, created_at, and a VECTOR field "embedding"
# Adjust PREFIX, ON, and SCHEMA to your data model.
# Ensure your REDIS_URL points to a Redis Stack instance.
FT.CREATE idx:openmemory:memories ON HASH PREFIX 1 "openmemory:memories:" SCHEMA \
  id TAG \
  user_id TAG \
  text TEXT \
  created_at NUMERIC SORTABLE \
  embedding VECTOR HNSW 12 TYPE FLOAT32 DIM 1536 DISTANCE_METRIC COSINE INITIAL_CAP 10000 M 16 EF_CONSTRUCTION 200
```

Notes:
- DIM must match your embedder model dimension.
- If using `redisvl`, you can define schema via redisvl; ensure index parameters match your model dims and chosen distance metric (COSINE recommended for OpenAI embeddings).

### PostgreSQL – enable pgvector and run migrations

Create database, user, and enable pgvector:

```sql
-- As a superuser (e.g., postgres):
CREATE DATABASE openmemory;
CREATE USER openmemory_user WITH PASSWORD 'changeme';
GRANT ALL PRIVILEGES ON DATABASE openmemory TO openmemory_user;

-- Connect to the DB:
\c openmemory

-- Enable pgvector (requires extension installed on the cluster):
CREATE EXTENSION IF NOT EXISTS vector;
```

Run Alembic migrations from repo root (explicit config path):
```bash
alembic -c openmemory/api/alembic.ini upgrade head
```

### Neo4j – constraints and APOC

Ensure Neo4j has APOC available if your flows require it.

Example constraint for unique memory id (adjust label/property to your schema):
```cypher
CREATE CONSTRAINT memory_id_unique IF NOT EXISTS
FOR (m:Memory) REQUIRE m.id IS UNIQUE;
```

Example docker run with APOC:
```bash
docker run -it --rm \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/changeme \
  -e NEO4JLABS_PLUGINS='["apoc"]' \
  -e NEO4J_apoc_export_file_enabled=true \
  -e NEO4J_apoc_import_file_enabled=true \
  -e NEO4J_apoc_import_file_use__neo4j__config=true \
  neo4j:5.20
```

---

## Environment variables

Canonical set (aligned with code usage):
- `DATABASE_URL` (PostgreSQL), e.g. `postgresql+psycopg2://openmemory_user:changeme@localhost:5432/openmemory`
- `REDIS_URL` e.g. `redis://localhost:6379/0`
- `REDIS_COLLECTION_NAME` e.g. `openmemory:memories`
- `NEO4J_URI` e.g. `bolt://localhost:7687`
- `NEO4J_USERNAME` e.g. `neo4j`
- `NEO4J_PASSWORD` e.g. `changeme`
- `OPENAI_API_KEY` your OpenAI key
- `EMBEDDING_MODEL` e.g. `text-embedding-3-small`
- `LLM_MODEL` e.g. `gpt-4o-mini`

Where read in code:
- Default memory config: [python.get_default_memory_config()](openmemory/api/app/utils/memory.py:139)
- Env substitution resolver (applies to all sections): [python._parse_environment_variables()](openmemory/api/app/utils/memory.py:162)

---

## API configuration

### Ports and base URL
The API commonly runs on port `8765`. Base URL examples assume `http://localhost:8765`.

### Endpoints
- `GET /api/v1/config/`
- `PUT /api/v1/config/`
- `POST /api/v1/config/reset`

Handlers in code: [python.get_configuration](openmemory/api/app/routers/config.py:124), [python.update_configuration](openmemory/api/app/routers/config.py:124), [python.reset_configuration](openmemory/api/app/routers/config.py:124)

### Example configuration payload

The server supports env substitution for secrets via `${env:VAR}`. Ensure your payload aligns with the default memory config structure:

```json
{
  "mem0": {
    "llm": {
      "provider": "openai",
      "config": {
        "api_key": "${env:OPENAI_API_KEY}",
        "model": "${env:LLM_MODEL}"
      }
    },
    "embedder": {
      "provider": "openai",
      "config": {
        "api_key": "${env:OPENAI_API_KEY}",
        "model": "${env:EMBEDDING_MODEL}"
      }
    }
  },
  "openmemory": {
    "database": {
      "url": "${env:DATABASE_URL}"
    },
    "vector_store": {
      "provider": "redis",
      "config": {
        "redis_url": "${env:REDIS_URL}",
        "collection_name": "${env:REDIS_COLLECTION_NAME}",
        "embedding_model_dims": 1536
      }
    },
    "graph": {
      "provider": "neo4j",
      "config": {
        "url": "${env:NEO4J_URI}",
        "username": "${env:NEO4J_USERNAME}",
        "password": "${env:NEO4J_PASSWORD}"
      }
    }
  }
}
```

Example calls:
```bash
# Read current config
curl -s http://localhost:8765/api/v1/config/ | jq

# Update config
curl -s -X PUT http://localhost:8765/api/v1/config/ \
  -H "Content-Type: application/json" \
  -d @config.json | jq

# Reset config to default
curl -s -X POST http://localhost:8765/api/v1/config/reset | jq
```

---

## Health and readiness

- Health router source: [python](openmemory/api/app/routers/health.py:1)
- Deep readiness check function: [python.readiness()](openmemory/api/app/routers/health.py:59)
- Deep readiness can be gated by `ENABLE_DEEP_READINESS`. When enabled, the API will actively check connectivity to Redis, PostgreSQL, and Neo4j before reporting ready.

Docker/Kubernetes health checks:
```dockerfile
HEALTHCHECK --interval=10s --timeout=3s --start-period=30s \
  CMD curl -fsS http://localhost:8765/health/ready || exit 1
```

Add a startup probe or initial delay to allow Redis/Postgres/Neo4j initialization and index/constraint creation.

---

## Code-level alignment

Configuration shape:
- The default memory config includes:
  - `openmemory.database.url`
  - `openmemory.vector_store` (provider + config)
  - `openmemory.graph` (provider + config)
  - `mem0.llm` and `mem0.embedder`
- The UI surfaces corresponding fields. The server supports env substitution in all sections via resolver [python._parse_environment_variables](openmemory/api/app/utils/memory.py:162).

Create-all guard:
- `ENABLE_CREATE_ALL` protection is configured around app instantiation; see [python.FastAPI()](openmemory/api/main.py:14).

---

## Docker Compose (minimal example)

Notes:
- This is a development-grade example intended for local runs. Redis is unauthenticated and Neo4j uses default initial auth. Secure credentials and enable TLS for production.
- You still need to (a) create the Redis FT index and (b) enable pgvector + apply Alembic migrations.

Save as `docker-compose.yml` at the repo root if desired for local setup:

```yaml
version: "3.9"
services:
  redis:
    image: redis/redis-stack:7.2.0-v13
    ports:
      - "6379:6379"
      - "8001:8001" # optional RedisInsight
    volumes:
      - redis-data:/data

  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: openmemory
      POSTGRES_USER: openmemory_user
      POSTGRES_PASSWORD: changeme
    ports:
      - "5432:5432"
    volumes:
      - pg-data:/var/lib/postgresql/data
    # Ensure pgvector is available; use a pgvector-enabled image or install extension via init scripts.

  neo4j:
    image: neo4j:5.20
    environment:
      NEO4J_AUTH: neo4j/changeme
      NEO4JLABS_PLUGINS: '["apoc"]'
      NEO4J_apoc_export_file_enabled: "true"
      NEO4J_apoc_import_file_enabled: "true"
      NEO4J_apoc_import_file_use__neo4j__config: "true"
    ports:
      - "7474:7474"
      - "7687:7687"
    volumes:
      - neo4j-data:/data

  # API and UI can run locally on host using your Python environment and Next.js,
  # or be containerized separately. When running API locally, export localhost-based envs.

volumes:
  redis-data:
  pg-data:
  neo4j-data:
```

Environment for local API when using the above compose:
```bash
export DATABASE_URL="postgresql+psycopg2://openmemory_user:changeme@localhost:5432/openmemory"
export REDIS_URL="redis://localhost:6379/0"
export REDIS_COLLECTION_NAME="openmemory:memories"
export NEO4J_URI="bolt://localhost:7687"
export NEO4J_USERNAME="neo4j"
export NEO4J_PASSWORD="changeme"
export OPENAI_API_KEY="YOUR_KEY"
export EMBEDDING_MODEL="text-embedding-3-small"
export LLM_MODEL="gpt-4o-mini"
export ENABLE_DEEP_READINESS="true"
```

Then:
- Create Redis FT index (see Redis section).
- Enable pgvector and run migrations:
  ```bash
  alembic -c openmemory/api/alembic.ini upgrade head
  ```

---

## End-to-end validation

Health and readiness:
```bash
curl -s http://localhost:8765/health/live | jq
curl -s http://localhost:8765/health/ready | jq
```

Configuration flow:
```bash
# Check defaults
curl -s http://localhost:8765/api/v1/config/ | jq

# Apply configuration (assumes config.json with env placeholders as above)
curl -s -X PUT http://localhost:8765/api/v1/config/ \
  -H "Content-Type: application/json" \
  -d @config.json | jq

# Reset if needed
curl -s -X POST http://localhost:8765/api/v1/config/reset | jq
```

Memory operations (server routes: [python](openmemory/api/app/routers/memories.py:1)):

```bash
# Create memory
curl -s -X POST http://localhost:8765/api/v1/memories \
  -H "Content-Type: application/json" \
  -d '{
        "text": "Alice likes hiking on weekends.",
        "user_id": "user_123",
        "metadata": {"source": "test"}
      }' | jq

# List memories
curl -s "http://localhost:8765/api/v1/memories?user_id=user_123&limit=10" | jq

# Vector search
curl -s -X POST http://localhost:8765/api/v1/memories/search \
  -H "Content-Type: application/json" \
  -d '{
        "query": "What does Alice enjoy?",
        "user_id": "user_123",
        "top_k": 5
      }' | jq
```

MCP SSE smoke check:
- Router mounted via [python.setup_mcp_server(app)](openmemory/api/main.py:79)
- SSE handler: [python.handle_sse](openmemory/api/app/mcp_server.py:377)

```bash
# Replace "client" and "user" with valid values recognized by your setup
curl -N http://localhost:8765/mcp/testclient/sse/user_123
```

---

## Troubleshooting

- Redis DIM mismatch  
  Symptom: search/indexing errors or zero results.  
  Action: Confirm FT index DIM equals the embedding model dimension. Recreate FT index with correct DIM and distance metric. Ensure `embedding_model_dims` in configuration matches.

- Redis RediSearch module or permissions  
  Symptom: `FT.CREATE`/`FT.INFO` errors.  
  Action: Use Redis Stack image. Verify RediSearch is loaded. Ensure your client has permissions. Re-run `FT.CREATE` with correct schema.

- PostgreSQL pgvector  
  Symptom: migration or query errors on vector columns.  
  Action: Ensure `CREATE EXTENSION vector` executed in the database. Re-run migrations:  
  ```bash
  alembic -c openmemory/api/alembic.ini upgrade head
  ```

- Neo4j auth/APOC  
  Symptom: connection failures or APOC procedure errors.  
  Action: Verify `NEO4J_URI`/username/password. Ensure APOC enabled via env vars or config. Check initial password and change in production.

- Alembic config path  
  Use:  
  ```bash
  alembic -c openmemory/api/alembic.ini upgrade head
  ```

---

## Appendix

References to code and docs:
- Default config loader: [python.get_default_memory_config()](openmemory/api/app/utils/memory.py:139)
- Env resolver: [python._parse_environment_variables()](openmemory/api/app/utils/memory.py:162)
- Config endpoints: [python.get_configuration](openmemory/api/app/routers/config.py:124), [python.update_configuration](openmemory/api/app/routers/config.py:124), [python.reset_configuration](openmemory/api/app/routers/config.py:124)
- Health router and readiness: [python](openmemory/api/app/routers/health.py:1), [python.readiness()](openmemory/api/app/routers/health.py:59)
- MCP SSE mount/handler: [python.setup_mcp_server(app)](openmemory/api/main.py:79), [python.handle_sse](openmemory/api/app/mcp_server.py:377)
- Architecture context: [markdown](openmemory/ARCHITECTURE-REVIEW.md:1)
- Corrective analysis: [markdown](openmemory/Codebase&#32;review&#32;task.md:1)

Security notes for production:
- Use strong, rotated credentials for PostgreSQL and Neo4j; enable TLS where supported.
- Configure Redis with ACL/auth and network isolation; consider Redis TLS.
- Store secrets in a secrets manager or orchestrator (K8s secrets, SSM, Vault).
- Restrict API exposure and enforce auth/authorization as appropriate for your deployment environment.