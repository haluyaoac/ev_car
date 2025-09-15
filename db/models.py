from sqlalchemy import Column, Integer, String, Float, DateTime
from sqlalchemy.orm import declarative_base
import datetime

Base = declarative_base()

class Car(Base):
    __tablename__ = "cars"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(128), nullable=False, index=True)
    brand = Column(String(128), nullable=True, index=True)
    model = Column(String(128), nullable=True)
    battery_kwh = Column(Float, nullable=False)
    consumption_kwh_per_km = Column(Float, nullable=False)
    initial_soc_percent = Column(Integer, default=100)
    avg_speed_kmph = Column(Float, default=60.0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)