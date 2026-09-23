import uuid

from pydantic import BaseModel, ConfigDict


class ReorderRecommendationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_id: uuid.UUID
    current_stock: int
    reorder_point: float
    lead_time_window_days: int
    should_reorder: bool
    order_quantity: int


class OptimizedOrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_id: uuid.UUID
    sku: str
    order_quantity: int
    cost: float
    priority: float


class OptimizationResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    budget: float
    total_cost: float
    orders: list[OptimizedOrderOut]
    skipped_product_ids: list[uuid.UUID]
