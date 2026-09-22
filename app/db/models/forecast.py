import uuid
from datetime import date, datetime

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Date

from app.db.base import Base


class Forecast(Base):
    __tablename__ = "forecasts"
    __table_args__ = (
        Index("ix_forecasts_product_target", "tenant_id", "product_id", "target_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"), index=True)
    target_date: Mapped[date] = mapped_column(Date)
    point_estimate: Mapped[float] = mapped_column(Numeric(10, 2))
    upper_bound: Mapped[float] = mapped_column(Numeric(10, 2))
    model_version: Mapped[int]
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
