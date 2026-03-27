FROM python:3.10-slim

WORKDIR /

# Install system dependencies if any
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend folder content into /backend
COPY . /backend

# Expose port
EXPOSE 8000

# Set environment variable to help relative imports if needed
ENV PYTHONPATH=/

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--timeout-keep-alive", "120"]
