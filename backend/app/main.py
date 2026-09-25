from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.config import Settings

settings = Settings()

app = FastAPI(
    title=settings.APP_NAME,
    openapi_tags=[
        {
            "name": "auth",
            "description": "Register, login, OAuth, password reset, and JWT token management.",
        },
        {"name": "works", "description": "Work search, work detail, shelf management."},
        {"name": "genres", "description": "Genre listing and genre-scoped work/thread lists."},
        {"name": "threads", "description": "Create and fetch discussion threads."},
        {"name": "posts", "description": "Post and reply within a thread, vote."},
        {"name": "users", "description": "User profile and shelf views."},
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Required by Authlib for storing OAuth state
app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY)

from app.api.auth import router as auth_router  # noqa: E402
from app.api import genres, posts, threads, users, works  # noqa: E402

# All routers are mounted under /api to match the frontend client baseURL.
# Each router already carries its own resource prefix (e.g. /auth, /works).
app.include_router(auth_router, prefix="/api")
app.include_router(works.router, prefix="/api")
app.include_router(genres.router, prefix="/api")
app.include_router(threads.router, prefix="/api")
app.include_router(posts.router, prefix="/api")
app.include_router(users.router, prefix="/api")


@app.get("/")
async def root():
    return {"name": settings.APP_NAME}
