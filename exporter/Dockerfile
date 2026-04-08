# Dockerfile
# Builds the Python telemetry exporter image.
# Note: nvidia-ml-py requires the NVIDIA driver to be accessible
# on the host. On Windows with Docker Desktop, GPU passthrough
# requires WSL2 backend with NVIDIA Container Toolkit.

FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["python", "main.py"]