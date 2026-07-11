FROM python:3.10-slim

WORKDIR /app

# Install system utilities and build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
# Install CPU-only PyTorch first to prevent downloading heavy CUDA binaries
RUN pip install --no-cache-dir torch --extra-index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Ensure empty directories exist for volumes
RUN mkdir -p books uploads chroma_db database hf_cache

# Expose port
EXPOSE 8000

# Command to run FastAPI server
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
