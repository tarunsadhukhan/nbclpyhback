from sqlalchemy import create_engine, MetaData
from sqlalchemy.orm import sessionmaker, declarative_base
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is not set")

try:
    print(f"Connecting to database with URL: {DATABASE_URL}")  # Debugging line
    engine = create_engine(DATABASE_URL, pool_size=1000, max_overflow=500)
    engine.connect()  # Try to connect immediately to catch errors early
    print("Database connection successful!")
except Exception as e:
    print(f"Error connecting to database: {e}")
    raise  # Re-raise the exception to stop execution
else:  # Only execute if the 'try' block completes without errors
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    metadata = MetaData()
    Base = declarative_base()
    
    def get_db():   
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()