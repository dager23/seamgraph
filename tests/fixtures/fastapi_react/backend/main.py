"""FastAPI app with routes, env reads, and Celery tasks for testing."""

import os

from fastapi import APIRouter, FastAPI

app = FastAPI()
router = APIRouter(prefix="/api/v1")

DATABASE_URL = os.environ["DATABASE_URL"]
SECRET_KEY = os.getenv("SECRET_KEY")
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")


@app.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/users/{user_id}")
async def get_user(user_id: int):
    return {"id": user_id}


@router.post("/users")
async def create_user():
    return {"created": True}


@router.get("/users/{user_id}/posts")
async def get_user_posts(user_id: int):
    return {"posts": []}


@router.delete("/users/{user_id}")
async def delete_user(user_id: int):
    return {"deleted": True}


app.include_router(router)
