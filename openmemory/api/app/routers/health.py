import os
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, HTTPException

router = APIRouter()

TRUTHY = {"1", "true", "yes", "on"}

def _is_truthy(value: str) -> bool:
    return str(value).strip().lower() in TRUTHY

async def _check_redis() -> Dict[str, Any]:
    try:
        from redis import asyncio as aioredis  # type: ignore
    except Exception:
        # If deep readiness is enabled and dependency missing, surface via caller
        raise RuntimeError("redis package not installed")

    url = os.getenv("REDIS_URL", "")
    coll = os.getenv("REDIS_COLLECTION_NAME", "")

    if not url or not coll:
        return {"redis": "skipped"}

    r = aioredis.from_url(url, decode_responses=True)
    # Connectivity check
    await r.ping()
    has_index = False
    try:
        # Optional: check RediSearch index existence
        # Permission errors or module absence should not fail readiness if ping succeeded
        await r.execute_command("FT.INFO", coll)
        has_index = True
    except Exception:
        has_index = False
    finally:
        try:
            await r.close()
        except Exception:
            pass

    return {"redis": "ok", "has_index": has_index}

async def _check_neo4j() -> Dict[str, Any]:
    try:
        from neo4j import AsyncGraphDatabase  # type: ignore
    except Exception:
        raise RuntimeError("neo4j package not installed")

    uri = os.getenv("NEO4J_URI", "")
    user = os.getenv("NEO4J_USERNAME", "")
    pwd = os.getenv("NEO4J_PASSWORD", "")

    if not uri or not user or not pwd:
        return {"neo4j": "skipped"}

    driver = AsyncGraphDatabase.driver(uri, auth=(user, pwd))
    try:
        async with driver.session() as session:
            result = await session.run("RETURN 1 AS ok")
            _ = await result.single()
    finally:
        try:
            await driver.close()
        except Exception:
            pass

    return {"neo4j": "ok"}

@router.get("/health")
async def health():
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}

@router.get("/health/readiness")
async def readiness():
    enable_deep = _is_truthy(os.getenv("ENABLE_DEEP_READINESS", ""))
    if not enable_deep:
        return {"status": "ready"}

    checks: Dict[str, Any] = {}

    # Redis deep check
    try:
        checks.update(await _check_redis())
    except RuntimeError as e:
        # Missing optional dependency
        raise HTTPException(status_code=503, detail={"status": "not_ready", "redis_error": str(e)})
    except Exception as e:
        # Avoid leaking secrets; only include message
        raise HTTPException(status_code=503, detail={"status": "not_ready", "redis_error": str(e)})

    # Neo4j deep check
    try:
        checks.update(await _check_neo4j())
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail={"status": "not_ready", "neo4j_error": str(e)})
    except Exception as e:
        raise HTTPException(status_code=503, detail={"status": "not_ready", "neo4j_error": str(e)})

    return {"status": "ready", "checks": checks}