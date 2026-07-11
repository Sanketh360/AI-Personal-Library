import os
import sys

# Ensure backend directory is in the import path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from services.database import init_db
from services.watcher import start_watcher, scan_existing_books

# Import API Routers
from api.upload import router as upload_router
from api.books import router as books_router
from api.chat import router as chat_router
from api.status import router as status_router

# Initialize database and execute WAL mode parameters
init_db()

# Ensure directories exist
BOOKS_DIR = os.getenv("BOOKS_DIR", "./books")
UPLOADS_DIR = os.getenv("UPLOADS_DIR", "./uploads")
os.makedirs(BOOKS_DIR, exist_ok=True)
os.makedirs(UPLOADS_DIR, exist_ok=True)

# Initialize FastAPI App
app = FastAPI(title="AI Personal Library API", version="2.2")

# Configure CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount APIRouters
app.include_router(upload_router)
app.include_router(books_router)
app.include_router(chat_router)
app.include_router(status_router)

@app.on_event("startup")
def startup_event():
    # 1. Pre-load local embedding model to avoid first-query delays
    print("Startup: Pre-loading sentence-transformer embedding model...")
    from services.embedding import get_embedding_model
    get_embedding_model()
    print("Startup: Embedding model pre-loaded successfully.")
    
    # 2. Pre-load reranker if not disabled
    if os.getenv("DISABLE_RERANKER", "false").lower() != "true":
        print("Startup: Pre-loading CrossEncoder reranker model...")
        from services.reranker import get_reranker_model
        get_reranker_model()
        print("Startup: Reranker model pre-loaded successfully.")
        
    # 3. Start folder watcher
    app.state.watcher = start_watcher(BOOKS_DIR)
    
    # 4. Scan and register existing books
    scan_existing_books(BOOKS_DIR)

@app.on_event("shutdown")
def shutdown_event():
    # Stop folder watcher thread
    if hasattr(app.state, "watcher"):
        app.state.watcher.stop()
        app.state.watcher.join()
        print("Directory Watcher stopped.")
