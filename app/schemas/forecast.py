import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class ForecastDay(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    target_date: date
    point_estimate: float
    upper_bound: float
    model_version: int
    generated_at: datetime


class ForecastSummaryRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_id: uuid.UUID
    sku: str
    target_date: date
    point_estimate: float
    upper_bound: float
