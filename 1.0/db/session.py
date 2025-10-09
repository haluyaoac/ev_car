from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import config
from .models import Base

_engine = create_engine(config.DB_URL, echo=False, future=True, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)

def init_db(create_sample: bool = False):
    """创建表；create_sample=False 时仅建表不插数据。"""
    Base.metadata.create_all(bind=_engine)
    if create_sample:
        # 延迟导入以避免循环
        from .crud import get_default_car, create_car
        with SessionLocal() as db:
            if get_default_car(db) is None:
                create_car(db, {
                    "name": "EV-Demo",
                    "brand": "DemoBrand",
                    "model": "DemoModel",
                    "battery_kwh": 60.0,
                    "consumption_kwh_per_km": 0.18,
                    "initial_soc_percent": 70,
                    "avg_speed_kmph": 80.0,
                })