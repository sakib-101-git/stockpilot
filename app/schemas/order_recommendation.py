import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class OrderRecommendationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    suggested_quantity: int
    suggested_cost: float
    status: str
    final_quantity: int | None
    decided_by: uuid.UUID | None
    decided_at: datetime | None
    created_at: datetime


class GenerateRecommendationsRequest(BaseModel):
    budget: float = Field(gt=0, description="Purchasing budget for this round")


class EditRecommendationRequest(BaseModel):
    new_quantity: int = Field(ge=0)
