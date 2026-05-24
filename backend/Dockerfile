# Use official lightweight Python image
FROM python:3.11-slim

# Set environment variables for Python
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set container working directory
WORKDIR /app

# Copy dependency configuration and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source files
COPY . .

# Cloud Run injects $PORT environment variable, default to 8080
ENV PORT=8080

# Launch uvicorn, dynamically binding to the port injected by Cloud Run
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
