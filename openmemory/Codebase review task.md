# OpenMemory Deployment Guide – Redis Vector DB, PostgreSQL (pgvector), and Neo4j Graph

This document replaces and expands on the existing OPENMEMORY‑RUNBOOK.md and ARCHITECTURE‑REVIEW.md files. It is designed as a single source of truth for operators and developers who want to run the OpenMemory API on top of the Mem0 memory engine using Redis for vector search, PostgreSQL (with the pgvector extension) for persistent storage, and Neo4j for graph memory.

The guide assumes the repository is currently at the state of the forgetful branch and calls out modifications relative to the upstream main branch where necessary.

## 1. Why this guide?

The upstream Mem0 project defaults to Qdrant as its vector database and does not wire in a graph store out‑of‑the‑box. The forgetful branch of this repository already modifies the default config to point at Redis and Neo4j, but the surrounding docs and scripts still assume Qdrant/SQLite in some places.

To bridge that gap, this guide:
- Summarizes the official Mem0 documentation for Redis, pgvector, and graph memory.
- Provides a complete setup checklist for a local or production deployment using Docker Compose.
- Details environment variables, database initialization commands, and health checks.
- Explains how to configure the OpenMemory API using its /api/v1/config endpoints or environment variables.
- Suggests code‑level alterations to align the repository with upstream best practices.

Where commands differ for development vs. production, they are explicitly separated. All shell snippets are ready to copy and run on Linux; adjust paths for your environment if necessary.

## 2. Prerequisites

Item | Development | Production
-- | -- | --
Python | 3.10 or later | Same as dev
Mem0 library | Install with graph support: `pip install "mem0ai[graph]"`. Pin versions via requirements.txt and use a virtual environment. | Same, with proper pinning and reproducible builds
Redis | Use Redis Stack (bundles RediSearch): `docker run -d --name redis-stack -p 6379:6379 redis/redis-stack:latest` | Managed Redis (e.g., Redis Cloud) or self‑hosted cluster. Ensure RediSearch enabled; configure persistence (AOF/RDB) per SLOs.
PostgreSQL | ≥14 with pgvector. Create DB (e.g., openmemory) and run `CREATE EXTENSION IF NOT EXISTS vector;` | Managed or HA cluster. Enable pgvector on the target DB.
Neo4j | Neo4j 5.x or AuraDB. If local, enable APOC plugin. | Same; enable backups and set appropriate memory/heap sizes.
Docker | Docker and Docker Compose for local orchestration. | Mirror prod as closely as possible.
OpenAI API Key | Required for LLM and embedding operations. | Use secrets management (Docker secrets or Vault).
Additional Python packages | Install alongside mem0ai: `pip install redis redisvl psycopg2-binary neo4j` | Same

Notes:
- redis and redisvl provide the client and higher‑level abstractions for vector operations in Redis.
- psycopg2-binary is required for SQLAlchemy to communicate with PostgreSQL.
- neo4j supplies the Bolt driver used by Mem0’s graph memory.

## 3. Service Architecture

Target architecture consists of three data stores and two application components:

- OpenMemory API (FastAPI, Mem0, port 8765)
- OpenMemory UI (Next.js, port 3000)
- Redis 7.2+ with RediSearch HNSW (vector DB)
- PostgreSQL 14+ with pgvector (structured and optional vectors)
- Neo4j 5.x with APOC (graph memory)

Roles:
- Redis acts as the vector database. Vectors are stored in a RediSearch index created via FT.CREATE.
- PostgreSQL holds structured data (e.g., configuration) and can optionally act as a vector store via the pgvector provider. Even if Redis is used for vectors, Postgres is needed for config persistence.
- Neo4j stores graph memory: relationships between memories for richer retrieval.

## 4. Preparing the Databases

### 4.1 Redis: Vector Index Setup

Launch Redis (local dev):
```
docker run -d --name redis-stack -p 6379:6379 redis/redis-stack:latest
```
Redis Stack bundles RediSearch; no extra installation is needed.

Create a RediSearch index (explicit control; adjust DIM to your embedding model):
For OpenAI text-embedding-3-* (1536 dims):
```
redis-cli -a &lt;your_password&gt; \
  FT.CREATE openmemory_vectors_idx ON HASH PREFIX 1 "mem:" \
  SCHEMA text TEXT user_id TAG app_id TAG \
  vector VECTOR HNSW 6 TYPE FLOAT32 DIM 1536 DISTANCE_METRIC COSINE INITIAL_CAP 100000 M 16 EF_CONSTRUCTION 200
```

Key parameters:
- VECTOR: treat field as high‑dimensional vector.
- HNSW: approximate nearest neighbors algorithm.
- DIM: embedding dimension (e.g., 1536 for many OpenAI models).

Persistence:
- Configure AOF/RDB to meet recovery objectives and set a suitable maxmemory-policy (e.g., allkeys-lru).

### 4.2 PostgreSQL: Database and pgvector extension

Install PostgreSQL and pgvector (Ubuntu example):
```
sudo apt-get install postgresql postgresql-contrib
sudo -u postgres psql -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

Create database and user:
```
sudo -u postgres psql <<'SQL'
CREATE DATABASE openmemory;
CREATE USER openmemory WITH PASSWORD 'openmemory';
GRANT ALL PRIVILEGES ON DATABASE openmemory TO openmemory;
SQL
```

Run Alembic migrations (from repo root):
```
alembic -c openmemory/api/alembic.ini upgrade head
```

Optional: Use Postgres as the vector store by configuring Mem0 with the pgvector provider. Provide user, password, host, port and optional dbname, collection_name, embedding_model_dims. Defaults commonly used:
- dbname=postgres
- collection_name=mem0
- embedding_model_dims=1536
- diskann=True
- hnsw=False

### 4.3 Neo4j: Graph Constraints

Run/provision Neo4j (local dev example):
```
docker run -d --name neo4j -p 7687:7687 -p 7474:7474 \
  -e NEO4J_AUTH=neo4j/&lt;password&gt; \
  -e NEO4J_PLUGINS='["apoc"]' \
  neo4j:5.26.4
```

Create constraints (ensure uniqueness/perf):
```
cypher-shell -u "$NEO4J_USERNAME" -p "$NEO4J_PASSWORD" -a "$NEO4J_URI" \
'CREATE CONSTRAINT memory_id IF NOT EXISTS FOR (m:Memory) REQUIRE m.id IS UNIQUE;'
```

Verify connectivity via neo4j-client or the API readiness checks.

## 5. Environment Variables

Set these before running the API. The forgetful branch references them in openmemory/api/app/utils/memory.py—ensure they exist in your environment:

```
export DATABASE_URL="postgresql+psycopg2://openmemory:openmemory@localhost:5432/openmemory"
export REDIS_URL="redis://:your_redis_password@localhost:6379"
export REDIS_COLLECTION_NAME="openmemory_vectors"
export NEO4J_URI="bolt://localhost:7687"
export NEO4J_USERNAME="neo4j"
export NEO4J_PASSWORD="password"
export OPENAI_API_KEY="sk-..."
export EMBEDDING_MODEL="text-embedding-3-small"
export LLM_MODEL="gpt-4o-mini"
```

Tip: Use env: placeholders in config.json or API payloads to resolve secrets from environment variables at startup (e.g., `"api_key": "env:OPENAI_API_KEY"`). This avoids persisting secrets.

## 6. Configuring the OpenMemory API

The FastAPI server exposes /api/v1/config endpoints to manage runtime configuration. The forgetful branch already overrides defaults to use Redis and Neo4j; verify and customize using these APIs.

Check current configuration:
```
BASE=http://localhost:8765
curl -sS "$BASE/api/v1/config/" | jq .
```

Update configuration (Redis vectors, Postgres DB, Neo4j graph):
```
curl -sS -X PUT "$BASE/api/v1/config/" \
  -H 'Content-Type: application/json' \
  -d '{
    "mem0": {
      "llm": {
        "provider": "openai",
        "config": {"model": "gpt-4o-mini", "api_key": "env:OPENAI_API_KEY"}
      },
      "embedder": {
        "provider": "openai",
        "config": {"model": "text-embedding-3-small", "api_key": "env:OPENAI_API_KEY"}
      }
    },
    "openmemory": {
      "vector_store": {
        "provider": "redis",
        "config": {
          "redis_url": "env:REDIS_URL",
          "collection_name": "env:REDIS_COLLECTION_NAME",
          "embedding_model_dims": 1536
        }
      },
      "database": {"url": "env:DATABASE_URL"},
      "graph": {
        "provider": "neo4j",
        "config": {
          "url": "env:NEO4J_URI",
          "username": "env:NEO4J_USERNAME",
          "password": "env:NEO4J_PASSWORD"
        }
      }
    }
  }' | jq .
```

Reset the memory client to reinitialize:
```
curl -sS -X POST "$BASE/api/v1/config/reset" | jq .
```

Test memory operations:
```
# Create
curl -sS -X POST "$BASE/api/v1/memories/" \
  -H 'Content-Type: application/json' \
  -d '{"text": "Alice likes decaf coffee.", "user_id": "user_123", "metadata": {"source": "guide"}}' | jq .

# List
curl -sS "$BASE/api/v1/memories/?limit=5" | jq .

# Search
curl -sS "$BASE/api/v1/memories/search?query=coffee&user_id=user_123&limit=3" | jq .
```

## 7. Health Checks and Readiness

Upstream exposes /health and /health/readiness endpoints (missing in forgetful branch). To align:
- Add a health router returning basic status.
- Readiness can optionally perform deep checks: Redis ping (aioredis.from_url().ping()), a trivial Neo4j query, and Postgres session check.
- Gate deep checks by `ENABLE_DEEP_READINESS=true`. When false, respond quickly without external calls.
- Point Docker/Kubernetes health checks to /health/readiness and allow a startup grace period for Redis index creation and Neo4j startup.

## 8. Code‑level alterations relative to main

- Add Postgres support to get_default_memory_config.
  - Include a database section with `"url": os.getenv("DATABASE_URL")` so the API persists configuration and can use Postgres as fallback vector store if desired.

- Expose env placeholders across all sections.
  - Ensure env:VAR resolution runs for database and graph_store entries, not just vector_store.

- Include Redis parameters: collection_name, embedding_model_dims.
  - Match Mem0 docs to avoid provider falling back to defaults; update get_default_memory_config and UI forms.

- PostgreSQL (pgvector) provider options:
  - When using pgvector, set provider to pgvector with user, password, host, port, and optional dbname. Respect advanced options such as diskann and hnsw.

- Graph memory support:
  - Ensure graph_store section is passed to Memory.from_config and exposed in UI for editing.

- Documentation alignment:
  - Update README and production guides to reference health endpoints and clarify SSE routes’ optionality.
  - Provide explicit instructions for creating the Redis index and running pgvector migrations.

## 9. Putting it all together: Docker Compose Example

A simplified docker-compose.yml standing up Redis, Postgres, Neo4j, OpenMemory API, and UI:

```
version: '3.8'
services:
  redis:
    image: redis/redis-stack:latest
    ports:
      - "6379:6379"
    environment:
      - REDIS_ARGS=--requirepass your_redis_password

  postgres:
    image: postgres:15
    environment:
      - POSTGRES_DB=openmemory
      - POSTGRES_USER=openmemory
      - POSTGRES_PASSWORD=openmemory
    ports:
      - "5432:5432"

  neo4j:
    image: neo4j:5.26.4
    ports:
      - "7474:7474"
      - "7687:7687"
    environment:
      - NEO4J_AUTH=neo4j/mem0graph
      - NEO4J_PLUGINS=["apoc"]

  openmemory-api:
    build:
      context: ./openmemory/api
      dockerfile: Dockerfile
    ports:
      - "8765:8765"
    environment:
      - DATABASE_URL=postgresql+psycopg2://openmemory:openmemory@postgres:5432/openmemory
      - REDIS_URL=redis://:your_redis_password@redis:6379
      - REDIS_COLLECTION_NAME=openmemory_vectors
      - NEO4J_URI=bolt://neo4j:7687
      - NEO4J_USERNAME=neo4j
      - NEO4J_PASSWORD=mem0graph
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - LLM_MODEL=gpt-4o-mini
      - EMBEDDING_MODEL=text-embedding-3-small
    depends_on:
      - redis
      - postgres
      - neo4j

  openmemory-ui:
    build:
      context: ./openmemory/ui
      dockerfile: Dockerfile
    ports:
      - "3000:3000"
    environment:
      - NEXT_PUBLIC_API_URL=http://openmemory-api:8765
      - NEXT_PUBLIC_USER_ID=drj
    depends_on:
      - openmemory-api
```

After `docker compose up -d`, follow sections 5 and 6:
- Create the Redis index (if not auto‑created with desired params).
- Run Alembic migrations.
- Set configuration via the API and reset the memory client.

## 10. Conclusion and Next Steps

By following this guide you will have a fully functioning OpenMemory deployment backed by Redis for vector search, PostgreSQL for structured storage, and Neo4j for graph memory. The steps incorporate official Mem0 recommendations for:
- Installing Redis clients (`redis`, `redisvl`) and using Redis Stack
- Enabling pgvector in Postgres
- Initializing graph memory with Neo4j

Future enhancements:
- Autoscaling groups for Redis and Neo4j
- Observability (Prometheus/Grafana)
- Rate‑limiting or caching middleware
- Keep docs aligned with code changes; consider contributing improvements upstream.

References:
- Overview – Mem0: https://docs.mem0.ai/open-source/graph_memory/overview
- Redis – Mem0: https://docs.mem0.ai/components/vectordbs/dbs/redis
- Pgvector – Mem0: https://docs.mem0.ai/components/vectordbs/dbs/pgvector
- Configurations – Mem0: https://docs.mem0.ai/components/vectordbs/config