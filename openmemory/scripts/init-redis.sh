#!/usr/bin/env bash
redis-cli -a "$REDIS_PASSWORD" FT.CREATE "${REDIS_COLLECTION_NAME}" \
  ON HASH PREFIX 1 memory: \
  SCHEMA vector VECTOR HNSW 6 TYPE FLOAT32 DIM 1536 DISTANCE_METRIC COSINE \
         text TEXT metadata TEXT user_id TAG created_at NUMERIC 