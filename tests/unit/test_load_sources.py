from sources.load_sources import read_seed, split_sql


def test_split_sql_strips_comments_and_splits():
    sql = """
    -- header comment
    DROP TABLE IF EXISTS a;
    CREATE TABLE a (
      id INT,   -- inline comment
      name VARCHAR(10)
    );
    """
    stmts = split_sql(sql)
    assert len(stmts) == 2
    assert stmts[0] == "DROP TABLE IF EXISTS a"
    assert "--" not in stmts[1]


def test_read_seed_keeps_text_defects_and_parses_dates(tmp_path):
    p = tmp_path / "customers.csv"
    p.write_text(
        "customer_id,msisdn,postcode,email,created_at,period_start\n"
        "CUS1,447000000001,N/A,,2026-01-01 10:00:00,2026-07-01\n"
    )
    df = read_seed(p)
    assert df.loc[0, "postcode"] == "N/A"  # not turned into NULL
    assert df.loc[0, "msisdn"] == "447000000001"  # kept as text, not a number
    assert df["email"].isna().all()  # empty cell -> NULL
    assert str(df["created_at"].dtype).startswith("datetime64")
    assert str(df["period_start"].dtype).startswith("datetime64")
