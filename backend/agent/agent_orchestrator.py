import os
import asyncio
# pyrefly: ignore [missing-import]
from google.genai import types

# Defensive imports for google-adk (compatible across 1.x and 2.0+)
try:
    # pyrefly: ignore [missing-import]
    from google.adk.agents import LlmAgent as Agent
except ImportError:
    try:
        # pyrefly: ignore [missing-import]
        from google.adk import Agent
    except ImportError:
        try:
            # pyrefly: ignore [missing-import]
            from google.adk.agents import Agent
        except ImportError:
            # Fallback mock for testing if library not installed yet
            class Agent:
                def __init__(self, **kwargs):
                    self.kwargs = kwargs

try:
    # pyrefly: ignore [missing-import]
    from google.adk.runners import Runner
except ImportError:
    try:
        # pyrefly: ignore [missing-import]
        from google.adk import Runner
    except ImportError:
        class Runner:
            def __init__(self, **kwargs):
                pass

try:
    # pyrefly: ignore [missing-import]
    from google.adk.sessions import InMemorySessionService
except ImportError:
    class InMemorySessionService:
        pass

# Import the tools
from agent.tools import search_book, search_library, compare_books

# Define Agent Instruction
INSTRUCTION = """
You are the AI Personal Library assistant, a helpful and precise assistant designed to help users query their digital library.
Your primary role is to answer questions about the books in the library by retrieving matching document passages using the tools provided.

You have three retrieval tools:
1. 'search_book': Use this when the user is asking about a single selected book. You must provide the exact book_id and query.
2. 'search_library': Use this when the user is asking a general question across the entire library.
3. 'compare_books': Use this when the user selects N specific books to compare, contrast, or analyze together.

Guidelines:
- Carefully evaluate the user query and instructions to choose the correct tool.
- When answering, you MUST include clear, inline citations (such as [Book Title, Chapter: X, Page: Y]) for any claims you make.
- Base your answers ONLY on the passages retrieved by the tools. If the tools do not return enough relevant information, state that you cannot find the answer in the retrieved documents.
"""

# Initialize Agent
gemini_model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")

# Auto-correct deprecated or invalid model names to prevent ADK runner memory leaks/hangs
if "gemini-2.5" in gemini_model or "gemini-1.5" in gemini_model:
    print(f"Normalizing deprecated Gemini model '{gemini_model}' to 'gemini-3.5-flash'...")
    gemini_model = "gemini-3.5-flash"

library_agent = Agent(
    name="library_agent",
    model=gemini_model,
    instruction=INSTRUCTION,
    tools=[search_book, search_library, compare_books]
)

# Initialize Runner and Session Service
session_service = InMemorySessionService()
runner = Runner(agent=library_agent, app_name="personal_library", session_service=session_service)

async def ask_library_agent(
    query: str, 
    scope: str, 
    book_ids: list = None, 
    session_id: str = "default_session"
) -> str:
    """
    Sends a query to the Google ADK Agent.
    Injects contextual hints into the prompt to ensure the agent calls the correct retrieval tool
    with appropriate arguments (book IDs).
    """
    # 1. Structure the prompt with scope instructions
    if scope == "book" and book_ids and len(book_ids) > 0:
        prompt = (
            f"[Context: The user has selected a single book. "
            f"You MUST use the 'search_book' tool with book_id='{book_ids[0]}' "
            f"to query its contents. Do not use search_library.]\n"
            f"Question: {query}"
        )
    elif scope == "compare" and book_ids and len(book_ids) > 0:
        prompt = (
            f"[Context: The user has selected multiple books for comparison. "
            f"You MUST use the 'compare_books' tool with book_ids={book_ids} "
            f"to retrieve and contrast information. Do not use search_library.]\n"
            f"Question: {query}"
        )
    else:
        prompt = (
            f"[Context: The user is querying the entire library. "
            f"You MUST use the 'search_library' tool to retrieve matching context.]\n"
            f"Question: {query}"
        )
        
    # 2. Format user message
    new_message = types.Content(
        role="user",
        parts=[types.Part(text=prompt)]
    )
    
    response_text = ""
    
    # Ensure session is created in session service before running the agent
    try:
        await session_service.create_session(
            app_name="personal_library",
            user_id="library_user",
            session_id=session_id
        )
    except Exception as se:
        # Ignore if session already exists
        pass
        
    import asyncio
    
    try:
        # Run agent runner async stream with a 30-second timeout to prevent infinite hangs
        async def run_stream():
            nonlocal response_text
            async for event in runner.run_async(
                user_id="library_user",
                session_id=session_id,
                new_message=new_message
            ):
                # Check for final response event
                if hasattr(event, "is_final_response") and event.is_final_response():
                    if event.content and event.content.parts:
                        response_text = "".join([p.text for p in event.content.parts if p.text])
                elif hasattr(event, "content") and event.content:
                    # Fallback check for content parts
                    if hasattr(event.content, "parts") and event.content.parts:
                        response_text = "".join([p.text for p in event.content.parts if p.text])

        await asyncio.wait_for(run_stream(), timeout=30.0)
    except asyncio.TimeoutError:
        print("Error: Google ADK Agent query execution timed out after 30 seconds.")
        response_text = "Error: Agent execution timed out. The Gemini server is currently experiencing high demand or load. Please try again."
    except Exception as e:
        print(f"Error running Google ADK Agent: {e}")
        # Fallback raw execution if Runner fails (e.g. key missing, network, etc)
        response_text = f"Error: Agent execution failed. Details: {e}"
        
    if not response_text:
        response_text = "I'm sorry, I was unable to retrieve a response from the library agent."
        
    return response_text
