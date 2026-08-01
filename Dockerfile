FROM python:3.11-slim

# uv — faster dependency resolution/installs than pip
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set the working directory inside the container
WORKDIR /app

# Set environment variables to prevent Python from writing .pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Use uv for runtime installs too (plugin requirements, WebUI package installs)
ENV KIRA_PACKAGE_INSTALLER=uv

# RUN apt-get update && apt-get install -y --no-install-recommends \
#     gcc \
#     python3-dev \
#  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install Python dependencies into the system environment
RUN uv pip install --system --no-cache -r requirements.txt

# Copy the application code
COPY . .

# Create the data directory to ensure it exists
RUN mkdir -p /app/data

# Expose the port the app runs on
EXPOSE 5267

# Define the volume for persistent data
VOLUME ["/app/data"]

# Command to run the application
CMD ["python", "main.py"]