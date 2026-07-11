import React, { useState, useEffect, useRef } from 'react';
import { 
  BookOpen, 
  UploadCloud, 
  Trash2, 
  Send, 
  Clock, 
  CheckCircle2, 
  AlertTriangle, 
  Search, 
  FileText, 
  Layers, 
  Server, 
  BookMarked,
  StopCircle,
  Plus
} from 'lucide-react';

function App() {
  const [books, setBooks] = useState([]);
  const [selectedBook, setSelectedBook] = useState(null);
  const [compareBooks, setCompareBooks] = useState([]);
  const [scope, setScope] = useState('library'); // 'library', 'book', 'compare'
  
  // Session memory and local storage persistence of multiple chats
  const [sessions, setSessions] = useState(() => {
    const saved = localStorage.getItem('library_chat_sessions');
    return saved ? JSON.parse(saved) : [];
  });
  const [sessionId, setSessionId] = useState(() => {
    return localStorage.getItem('library_session_id') || 'session_' + Math.random().toString(36).substring(2, 9);
  });
  const [messages, setMessages] = useState([]);

  // Sync current messages when session changes
  useEffect(() => {
    const activeSession = sessions.find(s => s.id === sessionId);
    if (activeSession) {
      setMessages(activeSession.messages);
    } else {
      setMessages([]);
    }
  }, [sessionId, sessions]);
  
  const [inputVal, setInputVal] = useState('');
  const [isUploading, setIsUploading] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [apiHealth, setApiHealth] = useState({ online: false, stats: null });
  const [uploadError, setUploadError] = useState(null);
  
  const messagesEndRef = useRef(null);
  const fileInputRef = useRef(null);
  const selectedBookRef = useRef(selectedBook);
  const abortControllerRef = useRef(null);
  
  // Keep ref updated
  useEffect(() => {
    selectedBookRef.current = selectedBook;
  }, [selectedBook]);

  // Persist sessions and active sessionId to localStorage
  useEffect(() => {
    localStorage.setItem('library_session_id', sessionId);
  }, [sessionId]);

  useEffect(() => {
    localStorage.setItem('library_chat_sessions', JSON.stringify(sessions));
  }, [sessions]);

  // Session message updater helper
  const updateSessionMessages = (id, newMsgs) => {
    setSessions(prev => {
      const exists = prev.find(s => s.id === id);
      if (exists) {
        return prev.map(s => {
          if (s.id === id) {
            return { ...s, messages: newMsgs };
          }
          return s;
        });
      } else {
        const firstMsgText = newMsgs[0]?.text || "New Chat";
        const title = firstMsgText.length > 25 ? firstMsgText.substring(0, 25) + "..." : firstMsgText;
        return [
          { id, title, messages: newMsgs, timestamp: Date.now() },
          ...prev
        ];
      }
    });
  };

  // Format sizes to human-readable
  const formatBytes = (bytes) => {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  // Poll database status & books list
  const fetchLibraryData = async () => {
    try {
      // Fetch server status
      const statusRes = await fetch('/api/status');
      if (statusRes.ok) {
        const statusData = await statusRes.json();
        setApiHealth({ online: true, stats: statusData.statistics });
      } else {
        setApiHealth({ online: false, stats: null });
      }
      
      // Fetch books
      const booksRes = await fetch('/api/books');
      if (booksRes.ok) {
        const booksData = await booksRes.json();
        setBooks(booksData);
        
        // Update selected book if its status changed (using Ref to avoid closure loops)
        const currentSel = selectedBookRef.current;
        if (currentSel) {
          const updated = booksData.find(b => b.id === currentSel.id);
          if (updated && (updated.status !== currentSel.status || updated.title !== currentSel.title)) {
            setSelectedBook(updated);
          }
        }
      }
    } catch (e) {
      setApiHealth({ online: false, stats: null });
    }
  };

  // Run polling on mount (empty dependency array to prevent loops)
  useEffect(() => {
    fetchLibraryData();
    const interval = setInterval(fetchLibraryData, 4000);
    return () => clearInterval(interval);
  }, []);

  // Scroll to bottom of chat
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Handle book card click (sets scope to single book automatically)
  const handleSelectBook = (book) => {
    if (book.status !== 'completed') return;
    setSelectedBook(book);
    setScope('book');
  };

  // Handle multi-select toggle for compare mode
  const handleCompareToggle = (bookId, e) => {
    e.stopPropagation();
    setCompareBooks(prev => {
      const next = prev.includes(bookId)
        ? prev.filter(id => id !== bookId)
        : [...prev, bookId];
      
      // If we select comparison books, switch scope to compare
      if (next.length > 0) {
        setScope('compare');
      } else {
        setScope('library');
      }
      return next;
    });
  };

  // Handle file uploads
  const handleFileUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setIsUploading(true);
    setUploadError(null);

    const formData = new FormData();
    formData.append('file', file);

    try {
      const res = await fetch('/api/upload', {
        method: 'POST',
        body: formData,
      });

      if (res.ok) {
        const data = await res.json();
        fetchLibraryData();
      } else {
        const err = await res.json();
        setUploadError(err.detail || 'Failed to upload book.');
      }
    } catch (err) {
      setUploadError('Network error uploading file.');
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  // Delete a book
  const handleDeleteBook = async (bookId, e) => {
    e.stopPropagation();
    if (!confirm('Are you sure you want to delete this book? This will remove all chunks and vectors.')) return;
    
    try {
      const res = await fetch(`/api/books/${bookId}`, {
        method: 'DELETE'
      });
      if (res.ok) {
        if (selectedBook?.id === bookId) setSelectedBook(null);
        setCompareBooks(prev => prev.filter(id => id !== bookId));
        fetchLibraryData();
      }
    } catch (err) {
      alert('Error deleting book.');
    }
  };

  // Send message query with abort signal support and history updates
  const handleSendMessage = async () => {
    if (!inputVal.trim() || isSending) return;

    // Build context-aware argument
    let targetBookIds = [];
    if (scope === 'book' && selectedBook) {
      targetBookIds = [selectedBook.id];
    } else if (scope === 'compare') {
      targetBookIds = compareBooks;
    }

    const userMessage = {
      id: Date.now(),
      role: 'user',
      text: inputVal
    };

    const updatedMessages = [...messages, userMessage];
    setMessages(updatedMessages);
    updateSessionMessages(sessionId, updatedMessages);
    setInputVal('');
    setIsSending(true);

    // Create abort controller for stopping the request
    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: controller.signal,
        body: JSON.stringify({
          query: userMessage.text,
          scope: scope,
          book_ids: targetBookIds,
          session_id: sessionId
        })
      });

      if (res.ok) {
        const data = await res.json();
        const finalMessages = [...updatedMessages, {
          id: Date.now() + 1,
          role: 'assistant',
          text: data.response
        }];
        setMessages(finalMessages);
        updateSessionMessages(sessionId, finalMessages);
      } else {
        const err = await res.json();
        const finalMessages = [...updatedMessages, {
          id: Date.now() + 1,
          role: 'assistant',
          text: `Error calling agent: ${err.detail || 'Unknown error'}`
        }];
        setMessages(finalMessages);
        updateSessionMessages(sessionId, finalMessages);
      }
    } catch (err) {
      if (err.name === 'AbortError') {
        // Aborted query is handled in handleForceStop
        return;
      }
      const finalMessages = [...updatedMessages, {
        id: Date.now() + 1,
        role: 'assistant',
        text: 'Network error communicating with server.'
      }];
      setMessages(finalMessages);
      updateSessionMessages(sessionId, finalMessages);
    } finally {
      setIsSending(false);
      abortControllerRef.current = null;
    }
  };

  // Cancel ongoing agent execution
  const handleForceStop = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
      setIsSending(false);
      const finalMessages = [...messages, {
        id: Date.now() + 99,
        role: 'assistant',
        text: '❌ Query execution cancelled by user.'
      }];
      setMessages(finalMessages);
      updateSessionMessages(sessionId, finalMessages);
    }
  };

  // Start a fresh session and clear current chat
  const handleNewChat = () => {
    // If sending, stop it first
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    
    const newSessionId = 'session_' + Math.random().toString(36).substring(2, 9);
    setSessionId(newSessionId);
    setMessages([]);
    setIsSending(false);
  };

  // Select an old session from history
  const handleSelectSession = (id) => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setSessionId(id);
    setIsSending(false);
  };

  // Delete an old session from history
  const handleDeleteSession = (id, e) => {
    e.stopPropagation();
    if (!confirm('Are you sure you want to delete this chat history?')) return;
    setSessions(prev => prev.filter(s => s.id !== id));
    if (sessionId === id) {
      const newSessionId = 'session_' + Math.random().toString(36).substring(2, 9);
      setSessionId(newSessionId);
    }
  };

  // Citation highlighting parser
  const renderMessageContent = (text) => {
    // Regex matches bracket citations like [Book Title, Chapter: X, Page: Y] or similar
    const parts = text.split(/(\[[^\]]+\])/g);
    return parts.map((part, index) => {
      if (part.startsWith('[') && part.endsWith(']')) {
        return (
          <span 
            key={index} 
            className="citation" 
            title="Referenced source passage"
          >
            {part}
          </span>
        );
      }
      return part;
    });
  };

  return (
    <div className="app-container">
      {/* Sidebar Panel */}
      <div className="sidebar">
        <div className="sidebar-header">
          <div className="sidebar-logo">
            <BookMarked size={20} />
          </div>
          <span className="sidebar-title">Personal Library</span>
        </div>

        {/* Upload Button Box */}
        <div className="upload-container">
          <div 
            className="upload-box"
            onClick={() => !isUploading && fileInputRef.current?.click()}
          >
            <UploadCloud size={24} className="upload-icon" />
            <div className="upload-text">
              {isUploading ? 'Uploading & Queueing...' : 'Upload Document'}
            </div>
            <div className="upload-subtext">PDF, DOCX, EPUB, TXT, MD</div>
            {uploadError && <div style={{color: 'var(--danger)', fontSize: '0.7rem', marginTop: '6px'}}>{uploadError}</div>}
          </div>
          <input 
            type="file" 
            ref={fileInputRef}
            className="file-input" 
            onChange={handleFileUpload}
            accept=".pdf,.docx,.epub,.txt,.md"
          />
        </div>

        {/* List of Books */}
        <div className="book-list-container">
          <span className="section-title">Library Collection ({books.length})</span>
          <div className="book-list">
            {books.length === 0 ? (
              <div style={{color: 'var(--text-muted)', fontSize: '0.8rem', textAlign: 'center', marginTop: '20px'}}>
                No books indexed yet.<br/>Upload or copy a file to watch folder.
              </div>
            ) : (
              books.map((book) => {
                const isSelected = selectedBook?.id === book.id && scope === 'book';
                const isComparing = compareBooks.includes(book.id) && scope === 'compare';
                
                return (
                  <div 
                    key={book.id} 
                    className={`book-card ${isSelected ? 'selected' : ''} ${isComparing ? 'comparing' : ''}`}
                    onClick={() => handleSelectBook(book)}
                  >
                    <div className="book-details">
                      <div className="book-icon-wrapper">
                        <FileText size={18} />
                      </div>
                      <div className="book-info">
                        <div className="book-title-text" title={book.title}>
                          {book.title}
                        </div>
                        <div className="book-meta-text">
                          <span>{book.format.toUpperCase()}</span>
                          <span>•</span>
                          <span>{formatBytes(book.file_size)}</span>
                          <span>•</span>
                          <span className={`status-badge ${book.status}`}>
                            {book.status}
                          </span>
                        </div>
                      </div>
                    </div>
                    
                    <div className="book-actions">
                      {book.status === 'completed' && (
                        <div className="checkbox-container" title="Select for comparison">
                          <input 
                            type="checkbox" 
                            className="compare-checkbox"
                            checked={compareBooks.includes(book.id)}
                            onChange={(e) => handleCompareToggle(book.id, e)}
                          />
                        </div>
                      )}
                      
                      <button 
                        className="delete-btn" 
                        onClick={(e) => handleDeleteBook(book.id, e)}
                        title="Delete Book"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Chat History Panel */}
        <div className="chat-history-container">
          <span className="section-title">Chat History ({sessions.length})</span>
          <div className="chat-history-list">
            {sessions.length === 0 ? (
              <div className="empty-history-text">No active sessions.</div>
            ) : (
              sessions.map((s) => (
                <div 
                  key={s.id} 
                  className={`history-card ${sessionId === s.id ? 'active' : ''}`}
                  onClick={() => handleSelectSession(s.id)}
                >
                  <Clock size={13} className="history-icon" />
                  <span className="history-title" title={s.title}>{s.title}</span>
                  <button 
                    className="delete-history-btn" 
                    onClick={(e) => handleDeleteSession(s.id, e)}
                    title="Delete Chat"
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {/* Main Chat/RAG Panel */}
      <div className="chat-panel">
        <div className="chat-header">
          <div className="chat-scope-selector">
            <button 
              className={`scope-btn ${scope === 'library' ? 'active' : ''}`}
              onClick={() => setScope('library')}
            >
              <Layers size={14} style={{display: 'inline', marginRight: '6px', verticalAlign: 'text-bottom'}} />
              Entire Library
            </button>
            <button 
              className={`scope-btn ${scope === 'book' ? 'active' : ''}`}
              onClick={() => {
                if (selectedBook) setScope('book');
                else alert('Please select a book from the list first.');
              }}
              disabled={!selectedBook}
            >
              <BookOpen size={14} style={{display: 'inline', marginRight: '6px', verticalAlign: 'text-bottom'}} />
              {selectedBook ? `${selectedBook.title.substring(0, 15)}...` : 'Single Book'}
            </button>
            <button 
              className={`scope-btn ${scope === 'compare' ? 'active' : ''}`}
              onClick={() => {
                if (compareBooks.length > 0) setScope('compare');
                else alert('Please select comparison checkboxes in the list first.');
              }}
              disabled={compareBooks.length === 0}
            >
              Compare Mode ({compareBooks.length})
            </button>
          </div>

          <div className="header-status">
            <button className="new-chat-btn" onClick={handleNewChat} title="Start New Conversation">
              <Plus size={14} />
              <span>New Chat</span>
            </button>
            <div className="api-status">
              <div className={`api-status-indicator ${apiHealth.online ? '' : 'offline'}`}></div>
              <span>Backend: {apiHealth.online ? 'Online' : 'Offline'}</span>
            </div>
          </div>
        </div>

        {/* Message Screen Area */}
        <div className="messages-container">
          {messages.length === 0 ? (
            <div className="welcome-screen">
              <div className="welcome-icon">
                <BookOpen size={32} />
              </div>
              <h1 className="welcome-title">AI Personal Assistant</h1>
              <p className="welcome-subtitle">
                Welcome to your self-hosted digital library search engine. Ask questions across your books with complete, structure-aware citation grounding.
              </p>
            </div>
          ) : (
            messages.map((msg) => (
              <div key={msg.id} className={`message-card ${msg.role}`}>
                <div className="avatar">
                  {msg.role === 'user' ? 'U' : 'AI'}
                </div>
                <div className="message-content">
                  {msg.role === 'user' ? msg.text : renderMessageContent(msg.text)}
                </div>
              </div>
            ))
          )}
          {isSending && (
            <div className="message-card assistant">
              <div className="avatar">AI</div>
              <div className="message-content" style={{display: 'flex', alignItems: 'center', gap: '8px'}}>
                <svg className="spinner" viewBox="0 0 50 50">
                  <circle className="path" cx="25" cy="25" r="20" fill="none" strokeWidth="5"></circle>
                </svg>
                <span>Retrieving, merging and synthesizing...</span>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Query Input Box */}
        <div className="chat-input-container">
          <div className="chat-input-box">
            <textarea 
              className="chat-input"
              placeholder="Ask anything about the document(s)..."
              rows={1}
              value={inputVal}
              onChange={(e) => setInputVal(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  handleSendMessage();
                }
              }}
              disabled={isSending}
            />
            {isSending ? (
              <button 
                className="stop-btn" 
                onClick={handleForceStop}
                title="Force Stop Query"
              >
                <StopCircle size={16} />
              </button>
            ) : (
              <button 
                className="send-btn" 
                onClick={handleSendMessage}
                disabled={!inputVal.trim()}
              >
                <Send size={16} />
              </button>
            )}
          </div>
          <div className="input-scope-info">
            <span>Query scope active:</span>
            <span className="input-scope-pill">{scope}</span>
            {scope === 'book' && selectedBook && (
              <span style={{color: 'var(--text-muted)'}}>• Targeting "{selectedBook.title}"</span>
            )}
            {scope === 'compare' && (
              <span style={{color: 'var(--text-muted)'}}>• Comparing {compareBooks.length} books</span>
            )}
            <span style={{marginLeft: 'auto', fontSize: '0.7rem', color: 'var(--text-muted)'}}>
              Session: {sessionId.substring(0, 12)}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

export default App;
