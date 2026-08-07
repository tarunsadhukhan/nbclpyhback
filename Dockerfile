# FROM python:3.12-slim

# # Install system packages needed for mysqlclient (and other build tools)
# RUN apt-get update && apt-get install -y \
#     gcc \
#     default-libmysqlclient-dev \
#     pkg-config \
#     && rm -rf /var/lib/apt/lists/*

# # Set the working directory inside the container
# WORKDIR /app



# # Install `uv` package manager
# RUN pip install uv

# COPY . .
# COPY pyproject.toml ./

# RUN pip install --upgrade pip && pip install uv
# RUN uv --version

# # Copy requirements.txt first to leverage caching
# #COPY requirements.txt /app/
# #RUN test -f pyproject.toml && uv pip install --system || echo "pyproject.toml not found"

# RUN uv pip install --system --requirements pyproject.toml


# #RUN if [ -f "pyproject.toml" ]; then uv pip install --system; else echo "pyproject.toml not found"; fi

# # Copy the rest of the project files

# # Upgrade pip and install uv

# # Verify that uv is installed correctly

# # Install Python dependencies
# #RUN pip install --no-cache-dir -r requirements.txt

# # Copy the rest of the code
# #COPY . /app
# # Ensure `uvicorn` is installed
# RUN pip install uvicorn

# # Expose the application port


# # Run the FastAPI/uvicorn server

# # Expose port 8000 for the FastAPI app
# EXPOSE 8000

# # Run the app with Uvicorn
# CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]

# FROM python:3.12-slim

# # Install system packages needed for mysqlclient (and other build tools)
# RUN apt-get update && apt-get install -y \
#     gcc \
#     default-libmysqlclient-dev \
#     pkg-config \
#     && rm -rf /var/lib/apt/lists/*

# # Set the working directory inside the container
# WORKDIR /app

# # Copy dependency files
# COPY pyproject.toml ./

# # Copy .env file early
# COPY .env .env

# # Copy the rest of the project files
# COPY . .

# # Install `uv`, `python-dotenv`, and dependencies
# RUN pip install --upgrade pip uv python-dotenv \
#   && uv pip install --system --requirements pyproject.toml \
#   && pip install uvicorn

# # Expose FastAPI port
# EXPOSE 8000

# # Run the FastAPI app
# CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.12-slim

# Install system packages needed for mysqlclient
RUN apt-get update && apt-get install -y \
    gcc \
    default-libmysqlclient-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Accept secrets/env vars at build-time
ARG DATABASE_USER
ARG DATABASE_PASSWORD
ARG DATABASE_HOST
ARG DATABASE_PORT
ARG DATABASE_DEFAULT
ARG ENV

# Export them so your app can read them via os.getenv()
ENV DATABASE_USER=$DATABASE_USER
ENV DATABASE_PASSWORD=$DATABASE_PASSWORD
ENV DATABASE_HOST=$DATABASE_HOST
ENV DATABASE_PORT=$DATABASE_PORT
ENV DATABASE_DEFAULT=$DATABASE_DEFAULT
ENV ENV=$ENV

# Copy files
COPY pyproject.toml ./
COPY . .

# Install dependencies
RUN pip install --upgrade pip uv python-dotenv \
  && uv pip install --system --requirements pyproject.toml \
  && pip install uvicorn

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
