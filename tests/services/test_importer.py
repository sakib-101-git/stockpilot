from app.services.importer import RowError, format_error_report, parse_products_csv


def test_valid_rows_are_parsed() -> None:
    csv_text = "sku,name,category\nA1,Widget,Tools\nB2,Gadget,\n"
    result = parse_products_csv(csv_text)

    assert result.errors == []
    assert len(result.valid_rows) == 2
    assert result.valid_rows[0].sku == "A1"
    assert result.valid_rows[0].category == "Tools"
    assert result.valid_rows[1].category is None
    assert result.total_rows == 2


def test_missing_required_column_is_one_top_level_error() -> None:
    csv_text = "sku,category\nA1,Tools\n"
    result = parse_products_csv(csv_text)

    assert result.valid_rows == []
    assert len(result.errors) == 1
    assert "name" in result.errors[0].message
    assert result.errors[0].row == 1


def test_empty_file_is_an_error() -> None:
    result = parse_products_csv("")
    assert result.valid_rows == []
    assert len(result.errors) == 1
    assert result.errors[0].row == 1


def test_empty_sku_is_a_row_error_not_a_crash() -> None:
    csv_text = "sku,name\n,Widget\n"
    result = parse_products_csv(csv_text)

    assert result.valid_rows == []
    assert len(result.errors) == 1
    assert result.errors[0].row == 2


def test_duplicate_sku_within_the_file_is_a_row_error() -> None:
    csv_text = "sku,name\nA1,Widget\nA1,Other Widget\n"
    result = parse_products_csv(csv_text)

    assert len(result.valid_rows) == 1
    assert len(result.errors) == 1
    assert result.errors[0].row == 3
    assert "duplicate" in result.errors[0].message


def test_sku_too_long_is_rejected() -> None:
    csv_text = f"sku,name\n{'x' * 65},Widget\n"
    result = parse_products_csv(csv_text)

    assert result.valid_rows == []
    assert len(result.errors) == 1


def test_valid_and_invalid_rows_can_coexist() -> None:
    csv_text = "sku,name\nA1,Widget\n,Bad Row\nB2,Gadget\n"
    result = parse_products_csv(csv_text)

    assert [p.sku for p in result.valid_rows] == ["A1", "B2"]
    assert len(result.errors) == 1
    assert result.errors[0].row == 3
    assert result.total_rows == 3


def test_format_error_report_lists_each_error_by_row() -> None:
    errors = [RowError(row=2, message="bad sku"), RowError(row=5, message="bad name")]
    assert format_error_report(errors) == "row 2: bad sku\nrow 5: bad name"


def test_format_error_report_of_no_errors_is_empty() -> None:
    assert format_error_report([]) == ""
