from sqlalchemy.orm import Session
from .models import Car
from typing import Optional, Dict

def get_car_by_name(db: Session, name: str) -> Optional[Car]:
    return db.query(Car).filter(Car.name == name).first()

def get_car_by_brand(db: Session, brand: str) -> Optional[Car]:
    return db.query(Car).filter(Car.brand == brand).order_by(Car.id.asc()).first()

def get_default_car(db: Session) -> Optional[Car]:
    return db.query(Car).order_by(Car.id.asc()).first()

def create_car(db: Session, data: Dict) -> Car:
    car = Car(
        name=data.get("name", "unnamed"),
        brand=data.get("brand"),
        model=data.get("model"),
        battery_kwh=float(data["battery_kwh"]),
        consumption_kwh_per_km=float(data["consumption_kwh_per_km"]),
        initial_soc_percent=int(data.get("initial_soc_percent", 100)),
        avg_speed_kmph=float(data.get("avg_speed_kmph", 60.0)),
    )
    db.add(car)
    db.commit()
    db.refresh(car)
    return car