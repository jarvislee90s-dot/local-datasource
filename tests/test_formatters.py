import pandas as pd
from local_datasource.formatters import format_csv_output


def test_format_csv_output():
    df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
    path, preview = format_csv_output(df, "/tmp/test.csv")
    assert path == "/tmp/test.csv"
    assert "a,b" in preview
