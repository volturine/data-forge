import polars as pl

from datasources.datasource_service import _compute_histogram


class TestDatasourceHistogram:
    """Test _compute_histogram helper function."""

    def test_empty_series(self):
        """Empty series returns empty list."""
        s = pl.Series("x", [], dtype=pl.Float64)
        result = _compute_histogram(s)
        assert result == []

    def test_single_value(self):
        """Single value collapses to one bin."""
        s = pl.Series("x", [5.0, 5.0, 5.0])
        result = _compute_histogram(s)
        assert len(result) == 1
        assert result[0]["start"] == 5.0
        assert result[0]["end"] == 5.0
        assert result[0]["count"] == 3

    def test_two_values(self):
        """Two distinct values are split across bins."""
        s = pl.Series("x", [0.0, 10.0])
        result = _compute_histogram(s, bins=2)
        assert len(result) == 2
        assert result[0]["start"] == 0.0
        assert result[1]["end"] == 10.0
        total = sum(b["count"] for b in result)  # type: ignore[call-overload]
        assert total == 2

    def test_default_20_bins(self):
        """Default call returns 20 bins."""
        s = pl.Series("x", list(range(100)))
        result = _compute_histogram(s)
        assert len(result) == 20

    def test_custom_bin_count(self):
        """Custom bins parameter is respected."""
        s = pl.Series("x", list(range(100)))
        result = _compute_histogram(s, bins=5)
        assert len(result) == 5

    def test_all_values_covered(self):
        """Sum of bin counts equals series length."""
        s = pl.Series("x", [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])
        result = _compute_histogram(s, bins=5)
        total = sum(b["count"] for b in result)  # type: ignore[call-overload]
        assert total == 10

    def test_bins_are_contiguous(self):
        """Each bin starts where the previous one ended."""
        s = pl.Series("x", list(range(50)))
        result = _compute_histogram(s, bins=10)
        for i in range(1, len(result)):
            assert result[i]["start"] == result[i - 1]["end"]

    def test_negative_values(self):
        """Handles negative ranges correctly."""
        s = pl.Series("x", [-10.0, -5.0, 0.0, 5.0, 10.0])
        result = _compute_histogram(s, bins=4)
        assert len(result) == 4
        assert result[0]["start"] == -10.0
        assert result[-1]["end"] == 10.0
        total = sum(b["count"] for b in result)  # type: ignore[call-overload]
        assert total == 5

    def test_integer_series(self):
        """Works with integer (non-float) series."""
        s = pl.Series("x", [1, 2, 3, 4, 5])
        result = _compute_histogram(s, bins=3)
        assert len(result) == 3
        total = sum(b["count"] for b in result)  # type: ignore[call-overload]
        assert total == 5

    def test_values_rounded(self):
        """Bin edges are rounded to 4 decimal places."""
        s = pl.Series("x", [0.0, 1.0 / 3.0, 2.0 / 3.0, 1.0])
        result = _compute_histogram(s, bins=3)
        for b in result:
            start_str = str(b["start"])
            if "." in start_str:
                assert len(start_str.split(".")[1]) <= 4

    def test_single_element(self):
        """Single element series returns one bin."""
        s = pl.Series("x", [42.0])
        result = _compute_histogram(s)
        assert len(result) == 1
        assert result[0]["count"] == 1

    def test_with_nulls_filtered_out(self):
        """Histogram is computed on non-null values (caller should filter)."""
        s = pl.Series("x", [1.0, 2.0, 3.0])  # caller filters nulls before calling
        result = _compute_histogram(s, bins=3)
        total = sum(b["count"] for b in result)  # type: ignore[call-overload]
        assert total == 3
