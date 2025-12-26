from sqlalchemy import create_all, Column, Integer, String, Float, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

SQLALCHEMY_DATABASE_URL = "sqlite:///./sql_app.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class CompanyFundamental(Base):
    __tablename__ = "fundamentals"

    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String, index=True)
    year = Column(Integer)
    revenue = Column(Float)  # 売上高
    operating_income = Column(Float)  # 営業利益
    net_income = Column(Float)  # 純利益
    eps = Column(Float)  # 1株利益

Base.metadata.create_all(bind=engine)
