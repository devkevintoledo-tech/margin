import math

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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
        {"name": "series", "description": "Series pages: member books and the series discussion room."},
        {"name": "threads", "description": "Create and fetch discussion threads."},
        {"name": "posts", "description": "Post and reply within a thread, vote."},
        {"name": "users", "description": "User profile and shelf views."},
        {"name": "librarian", "description": "Catalog fixes by trusted users."},
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

def _finite(value):
    """NaN and infinity as strings: JSON has no spelling for them."""
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {k: _finite(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite(v) for v in value]
    return value


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    # FastAPI's own handler, except that a rejected NaN in the echoed input
    # would make the 422 itself unserialisable (a 500).
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(_finite(exc.errors()))})


from app.api.auth import router as auth_router  # noqa: E402
from app.api import genres, librarian, posts, series, threads, users, works  # noqa: E402

# All routers are mounted under /api to match the frontend client baseURL.
# Each router already carries its own resource prefix (e.g. /auth, /works).
app.include_router(auth_router, prefix="/api")
app.include_router(works.router, prefix="/api")
app.include_router(genres.router, prefix="/api")
app.include_router(series.router, prefix="/api")
app.include_router(threads.router, prefix="/api")
app.include_router(posts.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(librarian.router, prefix="/api")


@app.get("/")
async def root():
    return {"name": settings.APP_NAME}
