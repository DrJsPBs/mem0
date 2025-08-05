# OpenMemory (mem0) – Production Setup

Redis Vector Store · Postgres Relational · Neo4j Graph
(updated 27 Jul 2025)

---

## 1 Directory / file map

| Path | Purpose | Notes |
|------|---------|-------|
| `.env.production` | global environment (no secrets committed) | sourced by Compose |
| `api/.env` / `ui/.env` | service‑local env (import values from parent) | |
| `docker-compose.yml` | single‑node stack (Redis, Postgres, Neo4j, API, UI) | localhost‑only ports |
| `api/app/utils/memory.py` | default memory config → Redis + Neo4j | one function patch |
| `scripts/init‑redis.sh` | create RediSearch HNSW index | run once |
| `scripts/init‑neo4j.cypher` | unique constraints | run once |
| `scripts/health‑check.sh` | basic liveness | optional cron |
| `scripts/backup.sh` | RDB + Neo4j dump | rotates 30 days |

---

## 2 Environment files

### 2.1 .env.production

```bash
# -------- Core --------
OPENAI_API_KEY=
USER=drj

# UI ↔ API
NEXT_PUBLIC_API_URL=http://localhost:8765
NEXT_PUBLIC_USER_ID=${USER}

# ------ Redis Vector ------
REDIS_URL=redis://:changeme@redis:6379
REDIS_PASSWORD=changeme                 # reuse inside container
REDIS_COLLECTION_NAME=openmemory_vectors

# ------ PostgreSQL --------
DATABASE_URL=postgresql://mem0:mem0@postgres:5432/mem0

# ------ Neo4j -------------
NEO4J_URI=bolt://neo4j:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=mem0graph

LOG_LEVEL=INFO
```

### 2.2 api/.env

```bash
# imported from parent
OPENAI_API_KEY=${OPENAI_API_KEY}
USER=${USER}

REDIS_URL=${REDIS_URL}
REDIS_PASSWORD=${REDIS_PASSWORD}
REDIS_COLLECTION_NAME=${REDIS_COLLECTION_NAME}

NEO4J_URI=${NEO4J_URI}
NEO4J_USERNAME=${NEO4J_USERNAME}
NEO4J_PASSWORD=${NEO4J_PASSWORD}

DATABASE_URL=${DATABASE_URL}
```

### 2.3 ui/.env

```bash
NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
NEXT_PUBLIC_USER_ID=${NEXT_PUBLIC_USER_ID}
NEXT_PUBLIC_APP_NAME=OpenMemory
```

---

## 3 docker-compose.yml

```yaml
version: "3.8"

services:
  redis:
    image: redis/redis-stack:latest
    command: ["redis-server",
              "--requirepass", "${REDIS_PASSWORD}",
              "--maxmemory", "16gb",
              "--maxmemory-policy", "allkeys-lru"]
    volumes: [redis_data:/data]
    healthcheck:
      test: ["CMD", "redis-cli", "-a", "${REDIS_PASSWORD}", "ping"]
      interval: 30s
      retries: 3
    networks: [memnet]

  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: mem0
      POSTGRES_PASSWORD: mem0
      POSTGRES_DB: mem0
    volumes: [pg_data:/var/lib/postgresql/data]
    networks: [memnet]

  neo4j:
    image: neo4j:5.26.4
    environment:
      NEO4J_AUTH: "${NEO4J_USERNAME}/${NEO4J_PASSWORD}"
      NEO4J_PLUGINS: '["apoc"]'
    volumes: [neo4j_data:/data]
    healthcheck:
      test: ["CMD", "wget", "--spider", "http://localhost:7474"]
      interval: 30s
      retries: 3
    networks: [memnet]

  openmemory-api:
    build: ./api
    env_file: [.env.production]
    ports: ["127.0.0.1:8765:8765"]
    depends_on:
      redis:  {condition: service_healthy}
      postgres:
        condition: service_started
      neo4j:  {condition: service_healthy}
    networks: [memnet]

  openmemory-ui:
    build: ./ui
    env_file: [.env.production]
    ports: ["127.0.0.1:3000:3000"]
    depends_on: [openmemory-api]
    networks: [memnet]

volumes:
  redis_data:
  pg_data:
  neo4j_data:

networks:
  memnet:
    driver: bridge
```

---

## 4 Patch api/app/utils/memory.py

```python
from functools import lru_cache
import os

@lru_cache
def get_default_memory_config():
    return {
        "vector_store": {
            "provider": "redis",
            "config": {
                "redis_url": os.getenv("REDIS_URL"),
                "collection_name": os.getenv("REDIS_COLLECTION_NAME", "openmemory_vectors"),
                "embedding_model_dims": 1536,
                "distance_metric": "COSINE"
            }
        },
        "graph_store": {
            "provider": "neo4j",
            "config": {
                "url": os.getenv("NEO4J_URI"),
                "username": os.getenv("NEO4J_USERNAME"),
                "password": os.getenv("NEO4J_PASSWORD")
            }
        }
    }
```

---

## 5 One‑time init scripts

### scripts/init‑redis.sh

```bash
#!/usr/bin/env bash
redis-cli -a "$REDIS_PASSWORD" FT.CREATE "${REDIS_COLLECTION_NAME}" \
  ON HASH PREFIX 1 memory: \
  SCHEMA vector VECTOR HNSW 6 TYPE FLOAT32 DIM 1536 DISTANCE_METRIC COSINE \
         text TEXT metadata TEXT user_id TAG created_at NUMERIC
```

### scripts/init‑neo4j.cypher

```cypher
CREATE CONSTRAINT user_id  IF NOT EXISTS FOR (u:User)   REQUIRE u.user_id   IS UNIQUE;
CREATE CONSTRAINT memory_id IF NOT EXISTS FOR (m:Memory) REQUIRE m.memory_id IS UNIQUE;
```

---

## 6 Ops helpers

### scripts/health‑check.sh

```bash
#!/usr/bin/env bash
curl -fs http://localhost:8765/health && echo "API OK"
docker exec $(docker compose ps -q redis) redis-cli -a "$REDIS_PASSWORD" ping
curl -fs http://localhost:7474 && echo "Neo4j OK"
```

### scripts/backup.sh

```bash
#!/usr/bin/env bash
DATE=$(date +%Y%m%d_%H%M%S)
mkdir -p backups/$DATE
docker exec $(docker compose ps -q redis) redis-cli -a "$REDIS_PASSWORD" SAVE
cp redis_data/dump.rdb backups/$DATE/redis.rdb
docker exec $(docker compose ps -q neo4j) neo4j-admin database dump neo4j --to-path /data/dumps
cp -r neo4j_data/dumps backups/$DATE/
tar -czf backups/$DATE.tar.gz -C backups $DATE
rm -rf backups/$DATE
```

---

## 7 Bring‑up

```bash
docker compose pull     # if images not built
docker compose build    # if you modified Dockerfiles
docker compose up -d

# one‑time index + constraints
bash scripts/init-redis.sh
docker exec -i $(docker compose ps -q neo4j) cypher-shell -u "$NEO4J_USERNAME" -p "$NEO4J_PASSWORD" < scripts/init-neo4j.cypher
```

---

## References

This guide replaces the Qdrant/SQLite draft with Redis + Neo4j while following mem0 docs and README structure 