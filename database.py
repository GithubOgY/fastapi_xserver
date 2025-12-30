from sqlalchemy import create_engine, Column, Integer, String, Float, Text, DateTime, Date, ForeignKey, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
import os
from dotenv import load_dotenv
from datetime import datetime

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
    ticker = Column(String, primary_key=True, index=True) # 5-digit code (e.g. 72030)
    code_4digit = Column(String, index=True)              # 4-digit code (e.g. 7203)
    name = Column(String, index=True)
    sector_17 = Column(String, nullable=True)
    sector_33 = Column(String, nullable=True)
    scale_category = Column(String, nullable=True) # J-Quants ScaleCat (Create/Update needed in DB)
    market = Column(String, nullable=True)
    next_earnings_date = Column(Date, nullable=True)      # 次回決算発表予定日
    earnings_updated_at = Column(DateTime, nullable=True) # 決算日更新日時
    last_sync_at = Column(DateTime, nullable=True)
    last_sync_error = Column(String, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow)

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    is_admin = Column(Integer, default=0)  # 0=normal user, 1=admin
    
    # Relationships
    comments = relationship("StockComment", back_populates="user")
    profile = relationship("UserProfile", back_populates="user", uselist=False)

class UserProfile(Base):
    __tablename__ = "user_profiles"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, index=True)
    display_name = Column(String(50), nullable=True)
    bio = Column(Text, nullable=True)
    investment_style = Column(String(50), nullable=True) # e.g. "Value", "Growth", "DayTrader"
    icon_emoji = Column(String(10), default="👤")
    twitter_url = Column(String(200), nullable=True)
    is_public = Column(Integer, default=0) # 0=Private, 1=Public
    
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    user = relationship("User", back_populates="profile")

class UserFavorite(Base):
    __tablename__ = "user_favorites"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True)
    ticker = Column(String, index=True)

class StockComment(Base):
    __tablename__ = "stock_comments"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    ticker = Column(String, index=True)
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="comments")

class EdinetCache(Base):
    """Cache for EDINET financial data - expires after 7 days"""
    __tablename__ = "edinet_cache"
    id = Column(Integer, primary_key=True, index=True)
    company_code = Column(String, index=True)  # 4-digit security code (e.g., "7203")
    doc_id = Column(String, index=True)  # EDINET document ID
    period_end = Column(String, index=True)  # Period end date (e.g., "2024-03-31")
    data_json = Column(Text)  # JSON string of the parsed financial data
    cached_at = Column(DateTime, default=datetime.utcnow)

class UserFollow(Base):
    __tablename__ = "user_follows"
    id = Column(Integer, primary_key=True, index=True)
    follower_id = Column(Integer, ForeignKey("users.id"), index=True)
    following_id = Column(Integer, ForeignKey("users.id"), index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (UniqueConstraint('follower_id', 'following_id', name='_follower_following_uc'),)
    
    follower = relationship("User", foreign_keys=[follower_id])
    following = relationship("User", foreign_keys=[following_id])

class AIAnalysisCache(Base):
    """Cache for AI-generated analysis results - reduces API costs"""
    __tablename__ = "ai_analysis_cache"
    id = Column(Integer, primary_key=True, index=True)
    ticker_code = Column(String, index=True, nullable=False)   # 銘柄コード (例: "7203")
    analysis_type = Column(String, default="general")           # 分析タイプ (将来の拡張用)
    analysis_html = Column(Text, nullable=False)                # 分析結果HTML
    analysis_text = Column(Text, nullable=True)                 # プレーンテキスト版（コピー用）
    created_at = Column(DateTime, default=datetime.utcnow)      # 生成日時
    expires_at = Column(DateTime, nullable=False)               # 有効期限

# DB initialization
Base.metadata.create_all(bind=engine)
