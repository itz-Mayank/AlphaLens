def sql_string_list(values: tuple[str, ...]) -> str:
    """Renders values for a `CHECK (col IN (...))` constraint string.

    Never use Python's tuple repr (`str(("A",))`) for this: a one-element
    tuple reprs with a trailing comma — `('A',)` — which is invalid SQL and
    fails silently until whatever builds the schema from raw DDL (a
    migration someone hand-writes correctly, `Base.metadata.create_all()`
    used by the test suite) actually runs it. `JobType.ALL` (one value
    today) hit exactly this.
    """
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"
