import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from agent.agent_orchestrator import ask_library_agent

router = APIRouter(prefix="/api", tags=["chat"])

class ChatRequest(BaseModel):
    query: str
    scope: str = "library"  # library, book, compare
    book_ids: list[str] = Field(default_factory=list)
    session_id: str = "default"

@router.post("/chat")
async def chat_query(request: ChatRequest):
    """Queries the library agent with proper scope instructions."""
    # Ensure Google Gemini API key is configured
    if not os.getenv("GEMINI_API_KEY"):
        raise HTTPException(
            status_code=500, 
            detail="GEMINI_API_KEY environment variable is missing on server."
        )
        
    try:
        response = await ask_library_agent(
            query=request.query,
            scope=request.scope,
            book_ids=request.book_ids,
            session_id=request.session_id
        )
        return {"response": response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
