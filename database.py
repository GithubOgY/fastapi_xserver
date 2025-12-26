from sqlalchemy import create_engine, Column, Integer, String, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv

load_dotenv()

# PostgreSQL URL prioritized, fallback to SQLite for local development if needed
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./sql_app.db")

# SQLAlchemy setup
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class CompanyFundamental(Base):
    __tablename__ = "fundamentals"
    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String)
    year = Column(Integer)
    revenue = Column(Float)
    operating_income = Column(Float)
    net_income = Column(Float)
    eps = Column(Float)

class Company(Base):
    __tablename__ = "companies"
    ticker = Column(String, primary_key=True, index=True)
    name = Column(String)
    last_sync_at = Column(String, nullable=True)
    last_sync_error = Column(String, nullable=True)

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    is_admin = Column(Integer, default=0)  # 0=通常ユーザー, 1=管理者

# DB initialization
Base.metadata.create_all(bind=engine)
