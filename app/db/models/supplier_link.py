import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ProductSupplier(Base):
    __tablename__ = "product_suppliers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "supplier_id", name="uq_product_supplier"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"), index=True)
    supplier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("suppliers.id"), index=True)
    unit_cost: Mapped[float] = mapped_column(Numeric(10, 2))
    lead_time_days_mean: Mapped[float] = mapped_column(Numeric(5, 1))
    lead_time_days_std: Mapped[float] = mapped_column(Numeric(5, 1))
    moq: Mapped[int] = mapped_column(Integer, default=1)
    pack_size: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
