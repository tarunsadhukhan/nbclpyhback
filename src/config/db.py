import re
from fastapi import HTTPException, Request
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session as SQLAlchemySession
import os
import threading

# Load environment variables
try:
    load_dotenv("env/database.env")
except Exception as e:
    print(f"Warning: Could not load database.env file: {e}")

def get_engine(db_url: str):
    try:
        return create_engine(
            db_url,
            pool_pre_ping=True,
            # sync handlers run in FastAPI's threadpool (~40 workers); the
            # default pool of 5+10 starves under concurrent load
            pool_size=10,
            max_overflow=30,
            connect_args={"init_command": "SET SESSION time_zone='+05:30'"}
        )
    except Exception as e:
        print(f"Error creating database engine: {e}")
        raise

# Check for required environment variables
required_vars = ['DATABASE_USER', 'DATABASE_PASSWORD', 'DATABASE_HOST', 'DATABASE_PORT', 'DATABASE_DEFAULT']
missing_vars = [var for var in required_vars if not os.getenv(var)]
if missing_vars:
    raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")

# Default (main) database connection
DEFAULT_DATABASE_URL = f"mysql+pymysql://{os.getenv('DATABASE_USER')}:{os.getenv('DATABASE_PASSWORD')}@" \
                       f"{os.getenv('DATABASE_HOST')}:{os.getenv('DATABASE_PORT')}/{os.getenv('DATABASE_DEFAULT')}"
print('DE', DEFAULT_DATABASE_URL)
default_engine = get_engine(DEFAULT_DATABASE_URL)

# Create a sessionmaker
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=default_engine)

# Export the Session class
Session = SQLAlchemySession

# One engine (connection pool) per database, created lazily and shared
# across requests — creating an engine per request leaks connection pools.
_tenant_engines = {}
_tenant_engines_lock = threading.Lock()

def get_tenant_engine(db_name: str):
    """Return the cached engine for a database, creating it on first use."""
    # db_name comes from request headers — validate before it reaches the
    # connection URL or the engine cache
    if not re.fullmatch(r"[A-Za-z0-9_]+", db_name or ""):
        raise HTTPException(status_code=400, detail="Invalid tenant subdomain")
    engine = _tenant_engines.get(db_name)
    if engine is None:
        with _tenant_engines_lock:
            engine = _tenant_engines.get(db_name)
            if engine is None:
                db_url = f"mysql+pymysql://{os.getenv('DATABASE_USER')}:{os.getenv('DATABASE_PASSWORD')}@" \
                         f"{os.getenv('DATABASE_HOST')}:{os.getenv('DATABASE_PORT')}/{db_name}"
                engine = get_engine(db_url)
                _tenant_engines[db_name] = engine
    return engine

def extract_subdomain_from_request(request: Request) -> str:
    """
    Extract subdomain from request using multiple fallback methods
    """
    print("\n=== Extracting Subdomain ===")
    
    # Try X-Forwarded-Host first (common with proxies)
    forwarded_host = request.headers.get("x-forwarded-host")
    print(f"X-Forwarded-Host header: {forwarded_host}")
    if forwarded_host and '.' in forwarded_host:
        subdomain = forwarded_host.split('.')[0]
        if subdomain != "localhost":
            print(f"Found subdomain from X-Forwarded-Host: {subdomain}")
            return subdomain

    # Try regular host header
    host = request.headers.get("host", "")
    print(f"Host header: {host}")
    if host and '.' in host:
        subdomain = host.split('.')[0]
        if subdomain != "localhost":
            print(f"Found subdomain from Host: {subdomain}")
            return subdomain

    # Try getting from referer
    referer = request.headers.get("referer", "")
    print(f"Referer header: {referer}")
    if referer:
        try:
            from urllib.parse import urlparse
            parsed = urlparse(referer)
            if parsed.netloc and '.' in parsed.netloc:
                subdomain = parsed.netloc.split('.')[0]
                if subdomain != "localhost":
                    print(f"Found subdomain from Referer: {subdomain}")
                    return subdomain
        except Exception as e:
            print(f"Error parsing referer: {str(e)}")

    # Try explicit subdomain header as fallback
    subdomain = request.headers.get("subdomain")
    print(f"Explicit subdomain header: {subdomain}")
    if subdomain:
        print(f"Found explicit subdomain: {subdomain}")
        return subdomain.strip()

    # Default fallback
    print("No subdomain found, using default")
    return "default"

def get_db_names(request: Request):
    """Fetches dynamic database mappings and assigns database engines."""
    print("\n=== Setting up Database Connection ===")
    
    subdomain = extract_subdomain_from_request(request)
    print(f"Using subdomain for database: {subdomain}")

    try:
        db_engines = {"default": default_engine}

        # Calculate database names based on subdomain
        db = subdomain
        db1 = f"{subdomain}_c"
        db2 = f"{subdomain}_c_1"
        db3 = f"{subdomain}_c_2"
        db4 = f"{subdomain}_c_3"
        
        print(f"""Database mappings:
        Main DB: {db}
        DB1: {db1}
        DB2: {db2}
        DB3: {db3}
        DB4: {db4}""")

        return {
            "db_engines": db_engines,
            "db": db,
            "db1": db1,
            "db2": db2,
            "db3": db3,
            "db4": db4,
            "db_names_array": [db, db1, db2, db3, db4]
        }
    except Exception as e:
        print(f"Error in get_db_names: {str(e)}")
        print(f"Error type: {type(e).__name__}")
        raise

# Dependency function to get the correct database session
def get_db(request: Request):
    """Returns the correct database session dynamically."""
    db_engines = get_db_names(request)
    yield db_engines

def get_tenant_db(request:Request):
    """Returns the tenant database session."""
    subdomain = extract_subdomain_from_request(request)
    db = Session(get_tenant_engine(subdomain), autoflush=False)
    try:
        yield db
    finally:
        db.close()
        


