"""FastAPI application for the polity visualizer."""

import logging
import traceback
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .routes import polities, individuals, cities

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Historical Polity Visualizer API",
    description="API for visualizing historical polities on a world map",
    version="1.0.0",
)

# CORS middleware for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:5174", "http://127.0.0.1:5174"],  # Vite dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled error on {request.method} {request.url.path}: {exc}")
    logger.error(traceback.format_exc())
    return JSONResponse(status_code=500, content={"detail": str(exc)})

# Include routers
app.include_router(polities.router, prefix="/api")
app.include_router(individuals.router, prefix="/api")
app.include_router(cities.router, prefix="/api")


@app.get("/")
def root():
    """Root endpoint."""
    return {
        "name": "Historical Polity Visualizer API",
        "version": "1.0.0",
        "docs": "/docs",
    }


@app.get("/api/health")
def health_check():
    """Health check endpoint."""
    from .database import get_db

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM polities")
        polity_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM individuals_light")
        individual_count = cursor.fetchone()[0]

    return {
        "status": "healthy",
        "polities": polity_count,
        "individuals": individual_count,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
