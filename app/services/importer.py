"""CSV parsing and validation for product imports.

Never raises on bad input. Every problem in the file — malformed structure,
a missing column, a bad value in one row — becomes a recorded error, so a
file with a few bad rows still imports everything else.
"""

import csv
import io
from dataclasses import dataclass, field

from pydantic import ValidationError

from app.schemas.product import ProductCreate

REQUIRED_COLUMNS = {"sku", "name"}


@dataclass(frozen=True)
class RowError:
    row: int  # 1-indexed; row 1 is the header, so the first data row is row 2
    message: str


@dataclass
class ParseResult:
    valid_rows: list[ProductCreate] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)

    @property
    def total_rows(self) -> int:
        return len(self.valid_rows) + len(self.errors)


def parse_products_csv(content: str) -> ParseResult:
    """Parse and validate a product CSV against the ProductCreate schema."""
    result = ParseResult()
    reader = csv.DictReader(io.StringIO(content))

    if reader.fieldnames is None:
        result.errors.append(RowError(row=1, message="file is empty"))
        return result

    missing = REQUIRED_COLUMNS - set(reader.fieldnames)
    if missing:
        result.errors.append(
            RowError(row=1, message=f"missing required column(s): {', '.join(sorted(missing))}")
        )
        return result

    seen_skus: set[str] = set()
    for line_number, raw_row in enumerate(reader, start=2):
        sku = (raw_row.get("sku") or "").strip()
        try:
            product = ProductCreate(
                sku=sku,
                name=(raw_row.get("name") or "").strip(),
                category=(raw_row.get("category") or "").strip() or None,
            )
        except ValidationError as exc:
            messages = "; ".join(e["msg"] for e in exc.errors())
            result.errors.append(RowError(row=line_number, message=messages))
            continue

        if product.sku in seen_skus:
            result.errors.append(
                RowError(row=line_number, message=f"duplicate sku '{product.sku}' in this file")
            )
            continue

        seen_skus.add(product.sku)
        result.valid_rows.append(product)

    return result


def format_error_report(errors: list[RowError]) -> str:
    """Human-readable report, one line per error, for storing on the ImportJob."""
    return "\n".join(f"row {e.row}: {e.message}" for e in errors)
