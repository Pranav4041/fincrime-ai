from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime
from datetime import datetime
from database import Base

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True)
    amount = Column(Float)
    time = Column(String)
    state = Column(String)
    is_new_device = Column(Boolean)
    ip_address = Column(String)
    timestamp = Column(DateTime, default=datetime.utcnow)