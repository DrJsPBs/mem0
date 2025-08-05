#!/usr/bin/env bash
DATE=$(date +%Y%m%d_%H%M%S)
mkdir -p backups/$DATE
docker exec $(docker compose ps -q redis) redis-cli -a "$REDIS_PASSWORD" SAVE
cp redis_data/dump.rdb backups/$DATE/redis.rdb
docker exec $(docker compose ps -q neo4j) neo4j-admin database dump neo4j --to-path /data/dumps
cp -r neo4j_data/dumps backups/$DATE/
tar -czf backups/$DATE.tar.gz -C backups $DATE
rm -rf backups/$DATE 