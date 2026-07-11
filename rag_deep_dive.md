# Deep Dive: The Complete Lifecycle of the Local CPU RAG System

This guide provides a granular, step-by-step breakdown of how the **AI Personal Library** operates under the hood. It follows a single transaction from the moment you hit enter on your terminal, trace the virtual files, explain the underlying hardware interactions, and simulate the neural network operations.

---

## Part 1: The Virtualization & Infrastructure Layer
### Step 1.1: Typing `docker compose up -d --build`
When you execute this command on your Windows terminal:
1. **CLI Parsing:** The Docker CLI parses the command.
   * `--build` instructs Docker to inspect all `Dockerfile` blueprints in the project and rebuild container images if the code or dependencies changed.
   * `-d` (detached) instructs Docker to daemonize the container processes, running them in the background.
2. **Docker Engine Coordination:** The Docker daemon reads [docker-compose.yml](file:///e:/AI%20Personal%20Library/docker-compose.yml) and identifies two services:
   * **`library_backend`** (built from `./backend/Dockerfile`)
   * **`library_frontend`** (built from `./frontend/Dockerfile`)
3. **Caching & Rebuilding:** 
   * Docker checks the build cache layer-by-layer. Since dependencies like `torch` take several minutes to download, Docker caches the python package layers (`pip install`). 
   * It copies only your refactored Python code (`api/`, `services/`, `main.py`) onto a new container filesystem layer, which takes less than 2 seconds.

---

### Step 1.2: The WSL 2 (Windows Subsystem for Linux) Sandbox
Because Docker containers run native Linux binaries, they cannot run directly on the Windows NT kernel.
1. **Lightweight Virtual Machine:** Docker Desktop uses **WSL 2** (Windows Subsystem for Linux 2) to launch a lightweight Linux utility VM.
2. **Resource Allocation:** WSL 2 allocates a portion of your physical hardware (by default, up to 50% of your RAM, e.g., 4GB, and all CPU cores) and starts a Linux kernel instance.
3. **The Sandbox:** Inside this Linux kernel, Docker creates isolated namespaces (cgroups) for your containers. The containers believe they are running on a raw Linux machine with their own virtual network interfaces and file system trees.

---

### Step 1.3: Docker Volumes (The Windows-to-Linux File Bridge)
To prevent your data from vanishing when containers are destroyed, we map host directories to container paths:
* **The Bridge:** When Docker mounts `./hf_cache:/app/hf_cache`, it hooks the Windows directory (`E:\AI Personal Library\hf_cache`) into the container's virtual path `/app/hf_cache`.
* **Under the Hood (9P Protocol):** Since the container is running inside a Linux kernel (WSL 2) and your code is on a Windows NTFS drive, WSL uses a high-speed file system protocol (9P / VirtIO-FS) to translate read/write calls in real-time. 
* When the Python container writes database records or loads weights, the Docker daemon immediately translates and writes them onto your physical Windows SSD/HDD.

---

## Part 2: Backend Boot & Model Preloading
Once the container starts, the Docker entrypoint executes:
```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```
This triggers the following sequential lifecycle:

### Step 2.1: Database Initialization & Schema Migrations
1. **Uvicorn Loading:** Python loads `main.py` and executes `init_db()` from [database.py](file:///e:/AI%20Personal%20Library/backend/services/database.py#L61).
2. **WAL Mode Activation:** The database engine connects to `database/library.db` and executes:
   ```sql
   PRAGMA journal_mode=WAL;
   ```
   * *Why:* Standard SQLite locks the entire database file during writes, crashing background threads if they attempt to write concurrently. **WAL (Write-Ahead Logging)** writes changes to a sidecar log file (`library.db-wal`) first, allowing readers to read the original file while writer threads write. This enables safe multi-threaded concurrency.
3. **Schema Check & Migration:** 
   * SQLite runs `PRAGMA table_info(books);` to inspect columns.
   * If `file_path` is missing (i.e. if using an older database from previous runs), it runs:
     ```sql
     ALTER TABLE books ADD COLUMN file_path VARCHAR;
     ```
     This automatically updates the schema without wiping out your uploaded books.

---

### Step 2.2: Preloading the Nomic Embedding Model
FastAPI triggers the `@app.on_event("startup")` block.
1. **Instance Check:** Python executes `get_embedding_model()` inside [embedding.py](file:///e:/AI%20Personal%20Library/backend/services/embedding.py#L9).
2. **Local Shelf Lookup:** The library checks the mounted cache directory `/app/hf_cache` for the folder `models--nomic-ai--nomic-embed-text-v1.5`.
3. **Hugging Face Hub Integration:**
   * **If Empty:** The Hugging Face Hub client contacts `huggingface.co` via HTTPS, downloads the 270MB of model weights, creates metadata folders, and writes them to the mounted Windows folder.
   * **If Cached:** It skips the network and loads the files directly from your hard drive.
4. **Warming the RAM (PyTorch):**
   * The model parameters (layers of neural weights) are read from disk.
   * **Memory Allocation:** The Python process allocates **~350MB of physical RAM** to hold these matrix weights in memory, ensuring that subsequent text embedding tasks can run instantly on your CPU.

---

### Step 2.3: Spawning the Directory Watcher
1. **Watcher Thread:** The backend spawns a background daemon thread running the `watchdog` library Observer.
2. **Monitoring:** It binds to `/app/books/` and listens for operating system file system interrupts (like file additions, deletions, or modification signals).

---

### Step 2.4: Startup Scan
The backend executes `scan_existing_books()` inside [watcher.py](file:///e:/AI%20Personal%20Library/backend/services/watcher.py#L112).
* It scans the `/app/books/` folder.
* If it finds any books that are not in the SQLite database, or whose status is marked as `failed` or `processing` (indicating a crash in a previous run), it automatically spawns a background thread to re-run the indexing pipeline for those books.

---

## Part 3: The Document Ingestion Pipeline
**Scenario:** You copy a new PDF called `The_Time_Machine.pdf` into your local `books/` folder.

```
[New Book Added] ---> [Watcher Detects] ---> [Acquire lock] ---> [Parse Text]
                                                                        |
[ChromaDB Index] <--- [Local Embedding] <--- [Token Chunker] <--- [Heading Split]
```

### Step 3.1: Detection & Stabilization
1. **Watcher Event:** The watchdog Observer detects `IN_CLOSE_WRITE` (file closed after writing).
2. **Stability Check:** Before parsing, `wait_for_file_stable()` runs a loop comparing the file size every 1 second. If the size is identical for two iterations, it assumes copying is finished and starts processing.
3. **Acquiring the Indexing Lock:** The backend runs `run_indexing_pipeline()` inside [indexing.py](file:///e:/AI%20Personal%20Library/backend/services/indexing.py#L14). It enters the `with indexing_lock:` block. If another book is currently being indexed, this thread halts and waits, preventing CPU spikes that would crash an 8GB RAM host.

---

### Step 3.2: Extraction (Parsing)
1. **PyMuPDF Parsing:** Inside [parser.py](file:///e:/AI%20Personal%20Library/backend/services/parser.py), `fitz` opens the document and extracts the text page-by-page.
2. **Layout Clean-up:** Trailing headers, footers, and extra whitespaces are stripped, creating an array of text objects mapped to page numbers.

---

### Step 3.3: Document Structure Detection
To preserve context, the parser must understand headers.
1. **Heading Detection:** The structural analyzer scans font metrics (font size, style, uppercase flags) to identify potential headers.
2. **Structural Annotation:** Pages are annotated with structural metadata (e.g. mapping which chapter title applies to which page range).

---

### Step 3.4: Hierarchical Token Chunking
If we give an entire book to the AI at once, it will exceed limit thresholds and respond slowly. We must cut it into chunks.
1. **Tokenization:** Text is split into small pieces (tokens).
2. **Window Slicing:** A sliding window chunks the text into overlapping segments of ~500 tokens (approx. 350 words). 
3. **Injecting Context:** Each chunk is prefixed with its structural context, for example:
   ```text
   Document: The Time Machine | Chapter: II | Page: 4
   ---
   [Actual paragraph text here...]
   ```
   *Why:* This ensures that even if a paragraph doesn't mention the book title or chapter name, the semantic search index still retains that contextual connection.

---

### Step 3.5: Batch Embedding Generation
1. **Batching:** The chunks are grouped into batches of 16.
2. **Matrix Multiplication (CPU Math):** 
   * The text chunk strings are converted into token ID lists.
   * The lists are fed into the Nomic Embed model loaded in RAM.
   * Your CPU cores perform matrix multiplications across the model layers.
3. **The Result:** The model output is a **768-dimensional float array** (a vector of 768 decimal numbers, e.g., `[0.015, -0.043, 0.112, ...]`) representing the semantic concept of that text segment.

---

### Step 3.6: Database Registration (Relational & Sparse FTS)
1. **Relational Database Write:** 
   * The book meta (ID, title, author, file size, pages, and `file_path=os.path.abspath(file_path)`) is inserted into the `books` table in `library.db`.
   * The individual chunks are inserted into the `chunks` table, referencing the parent `book_id`.
2. **FTS5 Indexing:** Each chunk's raw text is inserted into the virtual table `chunk_fts`. SQLite compiles this text into a lookup table for quick keyword search.

---

### Step 3.7: Vector Indexing (ChromaDB HNSW)
1. **ChromaDB Write:** The backend passes the 768-dimensional vectors and chunk IDs to the ChromaDB client.
2. **Building the HNSW Graph:**
   * ChromaDB's engine processes the vectors.
   * It calculates their coordinates relative to existing vectors in the database.
   * It updates the HNSW graph links inside the UUID folder in `./chroma_db/`.
   * It writes these graph updates to the `.bin` files (such as `data_level0.bin` and `link_lists.bin`).

Once all steps succeed, `book.status` is updated to `completed`, and the lock is released for the next file.

---

## Part 4: The Chat and Query Retrieval Workflow (RAG)
**Scenario:** You ask: *"Who wrote the Time Machine?"* in your web browser.

```
[Browser UI] --- (Vite Proxy) ---> [FastAPI /api/chat]
                                           |
[Gemini LLM] <--- [Cross-Encoder] <--- [Hybrid RRF Search] <--- [Agent Plan]
```

### Step 4.1: Frontend UI State Changes
1. **React State:** React sets `isLoading = true`, displaying the pulsing loading spinner.
2. **Local Storage:** The message is saved locally in the browser's `localStorage` array under `library_chat_sessions`.
3. **AbortController:** React instantiates a JavaScript `AbortController` linked to the request.
4. **Network Dispatch:** Axios sends a POST request:
   ```json
   {
     "query": "Who wrote the Time Machine?",
     "scope": "library",
     "book_ids": [],
     "session_id": "session-12345"
   }
   ```

---

### Step 4.2: Vite Reverse Proxy Forwarding
1. **Listening:** The Vite dev server container listens on port `5173`.
2. **Proxy Mapping:** It intercepts the `/api/chat` request path.
3. **Forwarding:** Vite forwards this request to the backend container's port `8000` (`http://library_backend:8000/api/chat`), bypassing CORS restrictions.

---

### Step 4.3: FastAPI Router Reception
1. **Routing:** The FastAPI Chat Router ([api/chat.py](file:///e:/AI%20Personal%20Library/backend/api/chat.py)) captures the request.
2. **Validation:** Pydantic validates the request schema.
3. **Execution:** The router executes `ask_library_agent()` in [agent_orchestrator.py](file:///e:/AI%20Personal%20Library/backend/agent/agent_orchestrator.py).

---

### Step 4.4: Agent Planning (First LLM Call)
1. **Agent Setup:** The Google ADK Agent constructs the agent session using the normalized Gemini model (`gemini-3.1-flash-lite`).
2. **Prompting the LLM:** The ADK runs the prompt telling the agent what tools are available (`search_book`, `search_library`, `compare_books`).
3. **LLM Planner Call:** Gemini parses the user's question: *"Who wrote the Time Machine?"*
4. **Tool Selection:** Gemini decides: *"This is a library-wide query. I should call the `search_library` tool with the query 'Who wrote the Time Machine'."*

---

### Step 4.5: Hybrid Retrieval & RRF Fusion
The agent executes the `search_library` tool, which triggers `retrieve_hybrid()` in [retrieval.py](file:///e:/AI%20Personal%20Library/backend/services/retrieval.py).

1. **Path A: Vector Semantic Search (ChromaDB)**
   * The query is converted into a 768-dimensional concept vector using the preloaded Nomic model in RAM.
   * ChromaDB searches its HNSW graph index (`.bin` files) to find the top 8 chunks closest to this concept vector.
   * It returns a list of chunks sorted by cosine similarity.
2. **Path B: Keyword Search (SQLite FTS5)**
   * The query is sent to `library.db` as a Full-Text Search SQL query:
     ```sql
     SELECT chunk_id, text FROM chunk_fts WHERE text MATCH :query LIMIT 8;
     ```
   * It returns the top 8 chunks sorted by exact keyword relevance.
3. **RRF (Reciprocal Rank Fusion) Merging:**
   * The two lists are merged mathematically.
   * **RRF Formula:** Each chunk gets a score calculated as:
     $$\text{Score} = \sum_{m \in M} \frac{1}{60 + \text{Rank}_m}$$
     *(where $M$ is the set of retrieval models, and $\text{Rank}_m$ is the position of the chunk in that search model).*
   * This formula rewards chunks that ranked high in *both* keyword and concept searches. The merged list is trimmed to the top candidate chunks.

---

### Step 4.6: Cross-Encoder Reranking
1. **Reranker Scoring:** The merged candidate chunks are sent to the local `ms-marco-MiniLM-L-6-v2` model in RAM.
2. **Scoring:** The model evaluates how well each chunk answers the specific question: *"Who wrote the Time Machine?"*
3. **Sorting:** Chunks are sorted by their evaluation scores. Only the top, most relevant chunks are returned to the agent.

---

### Step 4.7: Context Formulation & Final Answer
1. **Context Prompt Building:** The retrieved text chunks are formatted into a clean context prompt block:
   ```text
   Answer the user's question based strictly on the following source passages.
   ---
   Passage 1: [The Time Machine, Page 2]
   Written by H. G. Wells, published in 1895.
   ---
   User Question: Who wrote the Time Machine?
   ```
2. **Second LLM Call:** The agent passes this prompt to the Gemini API (`gemini-3.1-flash-lite`) via HTTPS.
3. **Response Generation:** Gemini reads the context, extracts the answer, formats the markdown citations (e.g. `[The Time Machine, Document Body, Page 2]`), and returns it to the backend.
4. **FastAPI Return:** FastAPI returns the text response to the Vite frontend.
5. **UI Update:** React receives the payload, appends the assistant's message, saves it to `localStorage`, and sets `isLoading = false` to remove the spinner.

---

## Part 5: Real-World Hardware Simulation
Here is what is happening across your physical hardware components during a single search query:

```
[Network Card] ---> [CPU Core 1] ---> [RAM Cache] ---> [SSD Disk Read]
   (Get Request)       (RRF Math)       (Model Weights)    (Database Fetch)
```

1. **Network Card (Wi-Fi/Ethernet):** Receives the HTTP payload on port 5173, passing it to the OS kernel.
2. **CPU (Core 1 - Web Server thread):** Wakes up to handle the FastAPI request, allocates execution stack frames, and queries the database.
3. **RAM Cache:** The CPU reads the preloaded Nomic embedding model weights directly from the RAM buffer, calculating the concept vector for your query in milliseconds.
4. **SSD (Disk Read):** SQLite performs read operations on `library.db`, loading candidate text chunks from disk.
5. **CPU (All Cores - PyTorch thread):** The Cross-Encoder reranker utilizes multiple CPU threads to score and rank the candidate passages.
6. **Network Card (SSL/TLS egress):** The backend sends the consolidated context prompt out to the internet to the Google Gemini servers.
7. **Network Card (ingress):** The Gemini API returns the text response.
8. **CPU (Core 1 - Serialization):** Formats the response, commits the updated chat history to the SQLite database file, and sends the payload back to the browser.
