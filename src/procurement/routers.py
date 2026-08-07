# # ...existing code...
# from fastapi import APIRouter, Depends
# from sqlalchemy.orm import Session
# from .database import get_db
# from .models import User

# router = APIRouter()

# @router.get("/users")
# def get_users(db: Session = Depends(get_db)):
#     return db.query(User).all()


# ...existing code...
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List
from src.config.database import get_db
from . import models, schemas

router = APIRouter()

@router.get("/items", response_model=List[schemas.ItemOut])
def get_items(db: Session = Depends(get_db)):
    return db.query(models.Item).all()