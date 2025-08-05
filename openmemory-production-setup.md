# OpenMemory Production Setup Guide

## Overview

This guide provides a streamlined setup for OpenMemory in production with Qdrant vector store and SQLite database, optimized for performance and security. This is a custom production configuration that differs from the default OpenMemory setup.

## Prerequisites

- Docker and Docker Compose
- OpenAI API Key
- At least 8GB RAM available (4GB minimum, 8GB recommended)
- 20GB+ disk space for Redis and Neo4j data

## Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   OpenMemory    │    │     Redis       │    │     Neo4j       │
│   API Server    │◄──►│  Vector Store   │    │  Graph Store    │
│   (Port 8765)   │    │   (Port 6379)   │    │  (Port 7687)    │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │
         ▼
┌─────────────────┐
│   OpenMemory    │
│   Web UI        │
│  (Port 3000)    │
└─────────────────┘
```

## Step 1: Environment Configuration

### 1.1 Create Environment Files
```bash
# Create production environment file
cat > .env.production << 'EOF'
# OpenAI Configuration
OPENAI_API_KEY=sk-your-openai-api-key-here

# User Configuration
USER=drj

# UI Configuration
NEXT_PUBLIC_API_URL=http://localhost:8765
NEXT_PUBLIC_USER_ID=drj

# Redis Vector Store Configuration
REDIS_URL=redis://:your_redis_password@redis:6379
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_PASSWORD=your_redis_password
REDIS_COLLECTION_NAME=openmemory_vectors

# Neo4j Configuration
NEO4J_URI=bolt://neo4j:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=mem0graph

# Production Settings
LOG_LEVEL=INFO
ENABLE_HEALTH_CHECKS=true
REQUEST_TIMEOUT=600
MAX_CONCURRENT_REQUESTS=100
RATE_LIMIT_REQUESTS_PER_MINUTE=1000
EOF

# Create API environment
cat > api/.env << 'EOF'
# OpenAI API Key
OPENAI_API_KEY=sk-your-openai-api-key-here

# Default user ID
USER=drj

# Redis Vector Store Configuration
REDIS_URL=redis://:your_redis_password@redis:6379
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_PASSWORD=your_redis_password
REDIS_COLLECTION_NAME=openmemory_vectors

# Neo4j Configuration
NEO4J_URI=bolt://neo4j:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=mem0graph

# Production Settings
LOG_LEVEL=INFO
EOF

# Create UI environment
cat > ui/.env << 'EOF'
# API URL
NEXT_PUBLIC_API_URL=http://localhost:8765

# Default user ID
NEXT_PUBLIC_USER_ID=drj

# App branding
NEXT_PUBLIC_APP_NAME=OpenMemory Production
EOF
```

## Step 2: Docker Compose Configuration

### 2.1 Create docker-compose.yml
```bash
cat > docker-compose.yml << 'EOF'
version: '3.8'

services:
  # Redis Vector Store with RediSearch
  redis:
    image: redis/redis-stack:latest
    container_name: openmemory-redis
    restart: unless-stopped
    ports:
      - "127.0.0.1:6379:6379"
    volumes:
      - redis_data:/data
    environment:
      - REDIS_ARGS=--requirepass your_redis_password --maxmemory 4gb --maxmemory-policy allkeys-lru
    networks:
      - openmemory-network
    healthcheck:
      test: ["CMD", "redis-cli", "-a", "your_redis_password", "ping"]
      interval: 30s
      timeout: 10s
      retries: 3
    deploy:
      resources:
        limits:
          memory: 6G
        reservations:
          memory: 4G

  # Neo4j Graph Database
  neo4j:
    image: neo4j:5.26.4
    container_name: openmemory-neo4j
    restart: unless-stopped
    ports:
      - "127.0.0.1:7474:7474"  # HTTP (localhost only)
      - "127.0.0.1:7687:7687"  # Bolt (localhost only)
    volumes:
      - neo4j_data:/data
      - neo4j_logs:/logs
      - neo4j_import:/var/lib/neo4j/import
      - neo4j_plugins:/plugins
    environment:
      - NEO4J_AUTH=neo4j/mem0graph
      - NEO4J_PLUGINS=["apoc"]
      - NEO4J_apoc_export_file_enabled=true
      - NEO4J_apoc_import_file_enabled=true
      - NEO4J_apoc_import_file_use__neo4j__config=true
      - NEO4J_dbms_memory_heap_initial__size=512m
      - NEO4J_dbms_memory_heap_max__size=1G
      - NEO4J_dbms_memory_pagecache_size=512m
    networks:
      - openmemory-network
    healthcheck:
      test: ["CMD", "wget", "--no-verbose", "--tries=1", "--spider", "http://localhost:7474"]
      interval: 30s
      timeout: 10s
      retries: 3
    deploy:
      resources:
        limits:
          memory: 4G
        reservations:
          memory: 2G

  # OpenMemory API Server
  openmemory-api:
    build:
      context: ./api
      dockerfile: Dockerfile
    container_name: openmemory-api
    restart: unless-stopped
    ports:
      - "127.0.0.1:8765:8765"
    volumes:
      - ./api:/usr/src/openmemory
      - openmemory_data:/app/data
    environment:
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - USER=${USER}
      - REDIS_URL=redis://:your_redis_password@redis:6379
      - REDIS_HOST=redis
      - REDIS_PORT=6379
      - REDIS_PASSWORD=your_redis_password
      - REDIS_COLLECTION_NAME=openmemory_vectors
      - NEO4J_URI=bolt://neo4j:7687
      - NEO4J_USERNAME=neo4j
      - NEO4J_PASSWORD=mem0graph
      - LOG_LEVEL=INFO
      - PYTHONUNBUFFERED=1
      - PYTHONDONTWRITEBYTECODE=1
    depends_on:
      redis:
        condition: service_healthy
      neo4j:
        condition: service_healthy
    networks:
      - openmemory-network
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8765/health"]
      interval: 30s
      timeout: 10s
      retries: 3
    deploy:
      resources:
        limits:
          memory: 2G
          cpus: '2.0'
        reservations:
          memory: 1G
          cpus: '1.0'

  # OpenMemory Web UI
  openmemory-ui:
    build:
      context: ./ui
      dockerfile: Dockerfile
    container_name: openmemory-ui
    restart: unless-stopped
    ports:
      - "127.0.0.1:3000:3000"
    environment:
      - NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
      - NEXT_PUBLIC_USER_ID=${NEXT_PUBLIC_USER_ID}
    depends_on:
      openmemory-api:
        condition: service_healthy
    networks:
      - openmemory-network
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3000"]
      interval: 30s
      timeout: 10s
      retries: 3

volumes:
  redis_data:
    driver: local
  neo4j_data:
    driver: local
  neo4j_logs:
    driver: local
  neo4j_import:
    driver: local
  neo4j_plugins:
    driver: local
  openmemory_data:
    driver: local

networks:
  openmemory-network:
    driver: bridge
EOF
```

## Step 3: Redis Vector Store Configuration

### 3.1 Redis Vector Store Setup
```bash
# Initialize Redis with RediSearch module for vector operations
docker-compose exec redis redis-cli -a your_redis_password ping

# Create vector search index for OpenMemory
docker-compose exec redis redis-cli -a your_redis_password --eval /dev/stdin << 'EOF'
-- Create vector search index for OpenMemory
FT.CREATE openmemory_vectors 
  ON HASH 
  PREFIX 1 memory: 
  SCHEMA 
    vector VECTOR HNSW 6 TYPE FLOAT32 DIM 1536 DISTANCE_METRIC COSINE 
    text TEXT 
    metadata TEXT 
    user_id TAG 
    created_at NUMERIC
EOF
```

### 3.2 Neo4j Initialization
```bash
# Initialize Neo4j constraints
docker-compose exec neo4j cypher-shell -u neo4j -p mem0graph -d neo4j "
CREATE CONSTRAINT user_id IF NOT EXISTS FOR (u:User) REQUIRE u.user_id IS UNIQUE;
CREATE CONSTRAINT memory_id IF NOT EXISTS FOR (m:Memory) REQUIRE m.memory_id IS UNIQUE;
"
```

### 3.3 Redis Vector Store Verification
```bash
# Verify Redis vector store setup
docker-compose exec redis redis-cli -a your_redis_password FT.INFO openmemory_vectors

# Test vector search index
docker-compose exec redis redis-cli -a your_redis_password FT.SEARCH openmemory_vectors "*" LIMIT 0 0

# Verify OpenMemory API can connect to Redis
docker-compose exec openmemory-api python -c "
import redis
r = redis.Redis.from_url('redis://:your_redis_password@redis:6379')
print(f'Redis connection: {r.ping()}')
"
```

## Step 4: Production Configuration

### 4.1 Memory Configuration
Create `api/app/utils/memory.py` with optimized production settings:

```python
def get_default_memory_config():
    """Production memory client configuration with Redis vector store and Neo4j."""
    return {
        "vector_store": {
            "provider": "redis",
            "config": {
                "redis_url": "redis://:your_redis_password@redis:6379",
                "collection_name": "openmemory_vectors",
                "embedding_model_dims": 1536,
                "index_name": "openmemory_vectors",
                "distance_metric": "COSINE",
                "vector_type": "FLOAT32",
                "hnsw_m": 6,
                "hnsw_ef_construction": 200,
                "hnsw_ef_runtime": 100
            }
        },
        "graph_store": {
            "provider": "neo4j",
            "config": {
                "url": "bolt://neo4j:7687",
                "username": "neo4j",
                "password": "mem0graph",
                "database": "neo4j"
            }
        },
        "llm": {
            "provider": "openai",
            "config": {
                "model": "gpt-4o-mini",
                "temperature": 0.1,
                "max_tokens": 2000,
                "api_key": "env:OPENAI_API_KEY"
            }
        },
        "embedder": {
            "provider": "openai",
            "config": {
                "model": "text-embedding-3-small",
                "api_key": "env:OPENAI_API_KEY"
            }
        },
        "version": "v1.1"
    }
```

### 4.2 Redis Connection Pooling
Update `api/app/redis_client.py`:

```python
import redis
import os
from redis.connection import ConnectionPool

# Redis connection configuration
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")

# Create Redis connection pool for optimal performance
redis_pool = ConnectionPool(
    host=REDIS_HOST,
    port=REDIS_PORT,
    password=REDIS_PASSWORD,
    decode_responses=True,
    max_connections=20,
    retry_on_timeout=True,
    health_check_interval=30
)

# Redis client instance
redis_client = redis.Redis(connection_pool=redis_pool)
```

### 4.3 Security Headers and Rate Limiting
Add to `api/app/main.py`:

```python
import redis
import json
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from datetime import datetime

# Redis client for caching and rate limiting
redis_client = redis.Redis.from_url(
    os.getenv("REDIS_URL", "redis://localhost:6379"),
    decode_responses=True
)

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

# Redis-based caching middleware
@app.middleware("http")
async def cache_middleware(request: Request, call_next):
    # Skip caching for non-GET requests
    if request.method != "GET":
        return await call_next(request)
    
    # Create cache key based on URL and user
    cache_key = f"cache:{request.url.path}:{request.headers.get('user-id', 'anonymous')}"
    
    # Try to get from cache
    cached_response = redis_client.get(cache_key)
    if cached_response:
        return Response(
            content=cached_response,
            media_type="application/json",
            headers={"X-Cache": "HIT"}
        )
    
    # Get response from upstream
    response = await call_next(request)
    
    # Cache successful responses for 5 minutes
    if response.status_code == 200:
        redis_client.setex(cache_key, 300, response.body.decode())
    
    return response

@app.get("/health")
async def health_check():
    # Check Redis connectivity
    redis_status = "healthy"
    try:
        redis_client.ping()
    except Exception as e:
        redis_status = f"unhealthy: {str(e)}"
    
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.0.0",
        "redis": redis_status
    }

@app.get("/health/readiness")
async def readiness_check():
    try:
        # Check Redis
        redis_client.ping()
        
        return {"status": "ready"}
    except Exception as e:
        return {"status": "not ready", "error": str(e)}
```

## Step 5: Deployment

### 5.1 Build and Start Services
```bash
# Build images
docker build -t openmemory-api:latest ./api
docker build -t openmemory-ui:latest ./ui

# Start services
docker-compose up -d

# Check status
docker-compose ps
```

### 5.2 Verify Deployment
```bash
# Health checks (localhost only)
curl http://localhost:8765/health
curl http://localhost:8765/health/readiness

# Redis vector store checks
docker-compose exec redis redis-cli -a your_redis_password ping
docker-compose exec redis redis-cli -a your_redis_password FT.INFO openmemory_vectors

# Neo4j check
curl http://localhost:7474

# UI check
curl http://localhost:3000
```

## Step 6: Testing and Validation

### 6.1 API Testing
```bash
# Test memory creation
curl -X POST "http://localhost:8765/api/v1/memories/" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "test-user",
    "text": "This is a test memory",
    "metadata": {"test": true}
  }'

# Test memory search
curl -X POST "http://localhost:8765/api/v1/memories/search/" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "test memory",
    "user_id": "test-user"
  }'
```

### 6.2 MCP Integration Test
```bash
# Install MCP client
npx @openmemory/install local \
  http://localhost:8765/mcp/test-client/sse/test-user \
  --client test-client
```

## Step 7: Backup and Maintenance

### 7.1 Automated Backup Script
```bash
cat > backup-production.sh << 'EOF'
#!/bin/bash
set -e

DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="./backups/$DATE"
RETENTION_DAYS=30

echo "Starting production backup at $(date)"

mkdir -p $BACKUP_DIR

# Backup Redis vector store
echo "Backing up Redis vector store..."
docker-compose exec redis redis-cli -a your_redis_password SAVE
docker cp openmemory-redis:/data/dump.rdb $BACKUP_DIR/redis_backup.rdb

# Backup Neo4j
echo "Backing up Neo4j..."
docker-compose exec neo4j neo4j-admin database dump neo4j
docker cp openmemory-neo4j:/var/lib/neo4j/data/dumps $BACKUP_DIR/neo4j

# Compress and clean
tar -czf $BACKUP_DIR.tar.gz -C ./backups $DATE
rm -rf $BACKUP_DIR

# Clean old backups
find ./backups -name "*.tar.gz" -mtime +$RETENTION_DAYS -delete

echo "Backup completed: $BACKUP_DIR.tar.gz"
EOF

chmod +x backup-production.sh
```

### 7.2 Health Check Script
```bash
cat > health-check.sh << 'EOF'
#!/bin/bash

echo "Checking OpenMemory Production Deployment..."

# Check API
if curl -f http://localhost:8765/health > /dev/null 2>&1; then
    echo "✅ API: OK"
else
    echo "❌ API: FAILED"
fi

# Check Redis vector store
if docker-compose exec redis redis-cli -a your_redis_password ping > /dev/null 2>&1; then
    echo "✅ Redis Vector Store: OK"
else
    echo "❌ Redis Vector Store: FAILED"
fi

# Check Neo4j
if curl -f http://localhost:7474 > /dev/null 2>&1; then
    echo "✅ Neo4j: OK"
else
    echo "❌ Neo4j: FAILED"
fi

# Check UI
if curl -f http://localhost:3000 > /dev/null 2>&1; then
    echo "✅ UI: OK"
else
    echo "❌ UI: FAILED"
fi

echo "Health check completed!"
EOF

chmod +x health-check.sh
```

## Step 8: Troubleshooting

### 8.1 Common Issues

**Redis Vector Store Connection Failed:**
```bash
docker-compose logs redis
docker-compose exec redis redis-cli -a your_redis_password ping
docker-compose restart redis
```

**Neo4j Connection Failed:**
```bash
docker-compose logs neo4j
docker-compose exec neo4j neo4j-admin set-initial-password newpassword
```

**API Server Issues:**
```bash
docker-compose logs openmemory-api
docker-compose exec openmemory-api env | grep OPENAI
```

### 8.2 Performance Optimization

**Slow Search Performance:**
```bash
# Check Redis vector search index status
docker-compose exec redis redis-cli -a your_redis_password FT.INFO openmemory_vectors

# Rebuild Redis vector index if needed
docker-compose exec redis redis-cli -a your_redis_password FT.DROPINDEX openmemory_vectors
docker-compose exec redis redis-cli -a your_redis_password --eval /dev/stdin << 'EOF'
FT.CREATE openmemory_vectors 
  ON HASH 
  PREFIX 1 memory: 
  SCHEMA 
    vector VECTOR HNSW 6 TYPE FLOAT32 DIM 1536 DISTANCE_METRIC COSINE 
    text TEXT 
    metadata TEXT 
    user_id TAG 
    created_at NUMERIC
EOF

# Check Neo4j indexes
docker-compose exec neo4j cypher-shell -u neo4j -p mem0graph "SHOW INDEXES"
```

**Memory Optimization:**
```bash
# Check Redis memory usage
docker-compose exec redis redis-cli -a your_redis_password INFO memory

# Monitor Redis performance
docker-compose exec redis redis-cli -a your_redis_password INFO stats
```

## Configuration Management Best Practices

### Environment Variable Management
- Use `.env.production` for production settings
- Never commit sensitive values to version control
- Use environment-specific configurations
- Validate required environment variables on startup

### Security Considerations
- Use strong, unique passwords for Redis and Neo4j
- Implement rate limiting and security headers
- Enable health checks for all services
- Use resource limits to prevent resource exhaustion

### Performance Optimization
- Configure Redis connection pooling for optimal performance
- Use HNSW indexing for vector similarity search
- Implement proper resource limits
- Monitor and optimize based on usage patterns

## Access Points

- **Web UI**: http://localhost:3000 (localhost only)
- **API Docs**: http://localhost:8765/docs (localhost only)
- **Neo4j Browser**: http://localhost:7474 (localhost only)
- **Redis Vector Store**: localhost:6379 (localhost only)
- **Health Check**: http://localhost:8765/health (localhost only)

**Note**: All services are bound to localhost only for security. External access is provided through Traefik and Cloudflare tunnel.

## Conclusion

This streamlined configuration provides:
- ✅ Redis vector store for ultra-fast memory operations
- ✅ Neo4j graph database for relationship mapping
- ✅ In-memory vector search with sub-millisecond latency
- ✅ HNSW indexing for optimized similarity search
- ✅ Production-ready security and performance settings
- ✅ Automated backup and health monitoring
- ✅ Proper configuration management practices 