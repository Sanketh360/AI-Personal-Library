import os
import time
import hashlib
import threading
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from services.database import SessionLocal, Book
from services.indexing import run_indexing_pipeline

def wait_for_file_stable(file_path: str, timeout: int = 15) -> bool:
    """
    Waits for the file to be fully copied/written by checking if its size remains stable.
    Returns True if the file is stable, False if it timed out or was deleted.
    """
    last_size = -1
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        if not os.path.exists(file_path):
            return False
        try:
            current_size = os.path.getsize(file_path)
            if current_size == last_size and current_size > 0:
                # File size hasn't changed, assume copy is complete
                return True
            last_size = current_size
        except OSError:
            # File might be locked during copy
            pass
        time.sleep(1.0)
        
    # Final check
    return os.path.exists(file_path) and os.path.getsize(file_path) > 0

class BookFileHandler(FileSystemEventHandler):
    """Listens for file creation events in the watched directory."""
    def __init__(self, callback_func):
        super().__init__()
        self.callback_func = callback_func
        
    def on_created(self, event):
        if event.is_directory:
            return
            
        file_path = event.src_path
        ext = os.path.splitext(file_path)[1].lower()
        
        # Only watch supported extensions
        if ext in ['.pdf', '.docx', '.epub', '.txt', '.md']:
            print(f"Directory Watcher: Detected new file: {file_path}")
            # Spin up a daemon thread to wait for file writing to finish, then process it
            thread = threading.Thread(
                target=self._process_file_when_stable, 
                args=(file_path,), 
                daemon=True
            )
            thread.start()
            
    def _process_file_when_stable(self, file_path: str):
        if wait_for_file_stable(file_path):
            print(f"Directory Watcher: File stable, triggering indexing: {file_path}")
            try:
                self.callback_func(file_path)
            except Exception as e:
                print(f"Directory Watcher: Error in callback for {file_path}: {e}")
        else:
            print(f"Directory Watcher: Timeout waiting for file to stabilize: {file_path}")

def handle_watcher_new_file(file_path: str):
    """Callback for watcher thread to ingest files manually copied into folders."""
    print(f"Watcher: Ingesting file: {file_path}")
    db = SessionLocal()
    try:
        filename = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        
        # Read contents to compute hash
        with open(file_path, "rb") as f:
            content = f.read()
        file_hash = hashlib.sha256(content).hexdigest()
        
        # Check duplicate
        existing = db.query(Book).filter(Book.file_hash == file_hash).first()
        if existing:
            print(f"Watcher: File '{filename}' is a duplicate of {existing.title}. Skipping.")
            return
            
        # Register book
        book_id = file_hash
        ext = os.path.splitext(filename)[1].lower()
        title = os.path.splitext(filename)[0].replace('_', ' ')
        
        new_book = Book(
            id=book_id,
            title=title,
            author=None,
            format=ext,
            file_size=file_size,
            file_hash=file_hash,
            status="queued",
            file_path=os.path.abspath(file_path)  # Save actual file path (resolving Issue 3)
        )
        db.add(new_book)
        db.commit()
        
        print(f"Watcher: Book registered. Queuing for indexing pipeline...")
        run_indexing_pipeline(book_id, file_path)
        
    except Exception as e:
        print(f"Watcher: Error processing {file_path}: {e}")
    finally:
        db.close()

def scan_existing_books(books_dir: str):
    """Scans the books/ folder on startup and registers/indexes any unindexed books."""
    print("Startup Scan: Scanning books folder for existing documents...")
    db = SessionLocal()
    try:
        if not os.path.exists(books_dir):
            return
            
        for filename in os.listdir(books_dir):
            file_path = os.path.join(books_dir, filename)
            if os.path.isdir(file_path):
                continue
                
            ext = os.path.splitext(filename)[1].lower()
            if ext in ['.pdf', '.docx', '.epub', '.txt', '.md']:
                try:
                    file_size = os.path.getsize(file_path)
                    with open(file_path, "rb") as f:
                        content = f.read()
                    file_hash = hashlib.sha256(content).hexdigest()
                    
                    # Check if already in db
                    existing = db.query(Book).filter(Book.file_hash == file_hash).first()
                    if not existing:
                        print(f"Startup Scan: Found new book '{filename}'. Registering...")
                        book_id = file_hash
                        title = os.path.splitext(filename)[0].replace('_', ' ')
                        
                        new_book = Book(
                            id=book_id,
                            title=title,
                            author=None,
                            format=ext,
                            file_size=file_size,
                            file_hash=file_hash,
                            status="queued",
                            file_path=os.path.abspath(file_path)  # Save actual file path (resolving Issue 3)
                        )
                        db.add(new_book)
                        db.commit()
                        
                        # Queue for indexing sequentially in a thread
                        thread = threading.Thread(
                            target=run_indexing_pipeline, 
                            args=(book_id, file_path), 
                            daemon=True
                        )
                        thread.start()
                    else:
                        # Reset status if it crashed or failed in a previous run to try again
                        if existing.status in ["processing", "queued", "failed"]:
                            existing.status = "queued"
                            db.commit()
                            print(f"Startup Scan: Retrying failed/incomplete book '{filename}'...")
                            thread = threading.Thread(
                                target=run_indexing_pipeline, 
                                args=(existing.id, file_path), 
                                daemon=True
                            )
                            thread.start()
                        else:
                            print(f"Startup Scan: Book '{filename}' already registered and completed.")
                except Exception as e:
                    print(f"Startup Scan: Error processing '{filename}': {e}")
    finally:
        db.close()

def start_watcher(books_dir: str) -> Observer:
    """Starts the folder watcher daemon thread."""
    if not os.path.exists(books_dir):
        os.makedirs(books_dir, exist_ok=True)
        
    event_handler = BookFileHandler(handle_watcher_new_file)
    observer = Observer()
    observer.schedule(event_handler, path=books_dir, recursive=False)
    observer.start()
    print(f"Directory Watcher started: monitoring '{books_dir}' for changes.")
    return observer
