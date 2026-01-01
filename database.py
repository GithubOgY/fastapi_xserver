from sqlalchemy import create_engine, Column, Integer, String, Float, Text, DateTime, Date, ForeignKey, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
import os
from dotenv import load_dotenv
from datetime import datetime, timezone

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
    ticker = Column(String(20), index=True)  # Added length limit and index
    year = Column(Integer, index=True)  # Added index for faster queries
    revenue = Column(Float)
    operating_income = Column(Float)
    net_income = Column(Float)
    eps = Column(Float)
    
    # Composite index for common query pattern (ticker + year)
    __table_args__ = (
        {'sqlite_autoincrement': True} if DATABASE_URL.startswith("sqlite") else {},
    )

class Company(Base):
    __tablename__ = "companies"
    ticker = Column(String(20), primary_key=True, index=True) # 5-digit code (e.g. 72030)
    code_4digit = Column(String(10), index=True)              # 4-digit code (e.g. 7203)
    name = Column(String(200), index=True)  # Added length limit
    sector_17 = Column(String(100), nullable=True)
    sector_33 = Column(String(100), nullable=True)
    scale_category = Column(String(50), nullable=True) # J-Quants ScaleCat (Create/Update needed in DB)
    market = Column(String(50), nullable=True)
    next_earnings_date = Column(Date, nullable=True, index=True)      # 次回決算発表予定日 (indexed for faster queries)
    earnings_updated_at = Column(DateTime, nullable=True) # 決算日更新日時
    last_sync_at = Column(DateTime, nullable=True)
    last_sync_error = Column(String(500), nullable=True)  # Added length limit
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True)  # Added length limit
    hashed_password = Column(String(255))  # bcrypt hashes are 60 chars, but allow extra space
    is_admin = Column(Integer, default=0)  # 0=normal user, 1=admin

    # Premium plan fields
    premium_tier = Column(String(20), default="free", index=True)  # free, premium, enterprise
    premium_until = Column(DateTime, nullable=True, index=True)  # Premium expiration date
    stripe_customer_id = Column(String(100), nullable=True, unique=True)  # Stripe customer ID
    stripe_subscription_id = Column(String(100), nullable=True)  # Stripe subscription ID

    # Relationships with cascade delete for data integrity
    comments = relationship("StockComment", back_populates="user", cascade="all, delete-orphan")
    profile = relationship("UserProfile", back_populates="user", uselist=False, cascade="all, delete-orphan")

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
    
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    user = relationship("User", back_populates="profile")

class UserFavorite(Base):
    __tablename__ = "user_favorites"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)  # Added FK with cascade
    ticker = Column(String(20), index=True)  # Added length limit
    
    # Composite unique constraint to prevent duplicate favorites
    __table_args__ = (
        UniqueConstraint('user_id', 'ticker', name='_user_ticker_uc'),
    )

class StockComment(Base):
    __tablename__ = "stock_comments"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)  # Added cascade delete
    ticker = Column(String(20), index=True)  # Added length limit
    content = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)  # Added index for sorting

    # Relationships
    user = relationship("User", back_populates="comments")
    likes = relationship("CommentLike", back_populates="comment", cascade="all, delete-orphan")

class CommentLike(Base):
    __tablename__ = "comment_likes"
    id = Column(Integer, primary_key=True, index=True)
    comment_id = Column(Integer, ForeignKey("stock_comments.id", ondelete="CASCADE"), index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # 複合ユニーク制約 - 同じユーザーが同じコメントに複数いいね不可
    __table_args__ = (
        UniqueConstraint('comment_id', 'user_id', name='_comment_user_like_uc'),
    )

    # Relationships
    comment = relationship("StockComment", back_populates="likes")
    user = relationship("User")

class EdinetCache(Base):
    """Cache for EDINET financial data - expires after 7 days"""
    __tablename__ = "edinet_cache"
    id = Column(Integer, primary_key=True, index=True)
    company_code = Column(String(10), index=True)  # 4-digit security code (e.g., "7203")
    doc_id = Column(String(50), index=True)  # EDINET document ID
    period_end = Column(String(10), index=True)  # Period end date (e.g., "2024-03-31")
    data_json = Column(Text)  # JSON string of the parsed financial data
    cached_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)  # Added index for cleanup queries
    
    # Composite unique constraint to prevent duplicate cache entries
    __table_args__ = (
        UniqueConstraint('company_code', 'doc_id', 'period_end', name='_edinet_cache_uc'),
    )

class UserFollow(Base):
    __tablename__ = "user_follows"
    id = Column(Integer, primary_key=True, index=True)
    follower_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)  # Added cascade delete
    following_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)  # Added cascade delete
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    __table_args__ = (UniqueConstraint('follower_id', 'following_id', name='_follower_following_uc'),)
    
    follower = relationship("User", foreign_keys=[follower_id])
    following = relationship("User", foreign_keys=[following_id])

class AIAnalysisCache(Base):
    """Cache for AI-generated analysis results - reduces API costs"""
    __tablename__ = "ai_analysis_cache"
    id = Column(Integer, primary_key=True, index=True)
    ticker_code = Column(String(20), index=True, nullable=False)   # 銘柄コード (例: "7203")
    analysis_type = Column(String(50), default="general", index=True)           # 分析タイプ (将来の拡張用) - added index
    analysis_html = Column(Text, nullable=False)                # 分析結果HTML
    analysis_text = Column(Text, nullable=True)                 # プレーンテキスト版（コピー用）
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)      # 生成日時 - added index
    expires_at = Column(DateTime, nullable=False, index=True)               # 有効期限 - added index for cleanup queries

    # Composite unique constraint to prevent duplicate cache entries
    __table_args__ = (
        UniqueConstraint('ticker_code', 'analysis_type', name='_ai_cache_uc'),
    )


class AIAnalysisHistory(Base):
    """AI分析結果の履歴保存（時系列分析用） - Phase 2"""
    __tablename__ = "ai_analysis_history"

    id = Column(Integer, primary_key=True, index=True)
    ticker_code = Column(String(20), index=True, nullable=False)
    analysis_type = Column(String(50), default="visual", index=True)

    # 構造化データ（JSON文字列）
    analysis_json = Column(Text, nullable=False)

    # スコアデータ（検索・集計用）
    overall_score = Column(Integer, nullable=True, index=True)
    investment_rating = Column(String(20), nullable=True)
    score_profitability = Column(Integer, nullable=True)
    score_growth = Column(Integer, nullable=True)
    score_financial_health = Column(Integer, nullable=True)
    score_cash_generation = Column(Integer, nullable=True)
    score_capital_efficiency = Column(Integer, nullable=True)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    # 複合インデックス：ticker_code + created_at でソートクエリを高速化
    # 注意: ユニーク制約なし（同じ銘柄の複数履歴を許可）


class AIUsageTracking(Base):
    """Track AI analysis usage per user per day for premium tier limits"""
    __tablename__ = "ai_usage_tracking"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    usage_date = Column(Date, index=True, nullable=False)  # Date in UTC
    usage_count = Column(Integer, default=0, nullable=False)  # Number of AI analyses on this date

    # Composite unique constraint: one row per user per day
    __table_args__ = (
        UniqueConstraint('user_id', 'usage_date', name='_user_date_uc'),
    )


# DB initialization
Base.metadata.create_all(bind=engine)
