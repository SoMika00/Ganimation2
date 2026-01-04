"""
Ganimation Studio - Main API
FastAPI application entry point
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

from api.routers import ingestion, gallery, generation, system
from api.config import settings
from api.services.gpu_manager import GPUManager


# =============================================================================
# Lifespan Events
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    # Startup
    logger.info("🚀 Starting Ganimation Studio API...")
    
    # Initialize GPU manager
    gpu_manager = GPUManager()
    app.state.gpu_manager = gpu_manager
    
    gpu_info = gpu_manager.get_info()
    logger.info(f"🎮 GPU Config: {gpu_info['num_gpus']} GPU(s), {gpu_info['total_vram_gb']:.1f}GB VRAM")
    
    if gpu_info.get('is_h100'):
        logger.info("✅ H100 detected - Optimizations enabled")
    
    # Ensure directories exist
    for dir_name in ['gallery/source_media', 'gallery/generated_images', 
                     'gallery/generated_videos', 'temp', 'models']:
        Path(settings.data_dir / dir_name).mkdir(parents=True, exist_ok=True)
    
    logger.info(f"📁 Data directory: {settings.data_dir}")
    logger.info("✅ Ganimation Studio API ready!")
    
    yield
    
    # Shutdown
    logger.info("👋 Shutting down Ganimation Studio API...")
    
    # Cleanup GPU resources
    gpu_manager.cleanup()


# =============================================================================
# Application
# =============================================================================

app = FastAPI(
    title="Ganimation Studio API",
    description="""
    🎬 AI-Powered Video Editing Platform
    
    Transform your shorts into Ghibli-style animations.
    
    ## Features
    
    * **Ingestion** - Import videos via URL (YouTube, TikTok) or upload
    * **Gallery** - Browse and manage media library
    * **Image Generation** - Create Ghibli-style frames with SDXL + LoRA
    * **Video Generation** - Animate with Wan2.2 + RIFE
    
    ## GPU Optimized
    
    Configured for NVIDIA H100 with Flash Attention 2, TF32, and BFloat16.
    """,
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)


# =============================================================================
# Middleware
# =============================================================================

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request logging
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all requests"""
    logger.debug(f"📥 {request.method} {request.url.path}")
    response = await call_next(request)
    logger.debug(f"📤 {request.method} {request.url.path} -> {response.status_code}")
    return response


# =============================================================================
# Exception Handlers
# =============================================================================

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": True,
            "message": exc.detail,
            "status_code": exc.status_code,
        },
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle general exceptions"""
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "error": True,
            "message": "Internal server error",
            "status_code": 500,
        },
    )


# =============================================================================
# Routes
# =============================================================================

# Include routers
app.include_router(system.router, prefix="/api/v1", tags=["System"])
app.include_router(ingestion.router, prefix="/api/v1/ingestion", tags=["Ingestion"])
app.include_router(gallery.router, prefix="/api/v1/gallery", tags=["Gallery"])
app.include_router(generation.router, prefix="/api/v1/generation", tags=["Generation"])


# Health check endpoint
@app.get("/health", tags=["Health"])
async def health_check():
    """Health check endpoint for Docker/Kubernetes"""
    return {
        "status": "healthy",
        "service": "ganimation-api",
        "version": "1.0.0",
    }


# Root endpoint
@app.get("/", tags=["Root"])
async def root():
    """Root endpoint with API info"""
    return {
        "name": "Ganimation Studio API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
    }

