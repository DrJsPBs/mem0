#!/usr/bin/env bash
curl -fs http://localhost:8765/health && echo "API OK"
docker exec $(docker compose ps -q redis) redis-cli -a "$REDIS_PASSWORD" ping
curl -fs http://localhost:7474 && echo "Neo4j OK" 