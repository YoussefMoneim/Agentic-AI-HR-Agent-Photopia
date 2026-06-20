from data.base import DataSource


def get_data_source() -> DataSource:
    import config

    if config.DATA_SOURCE == "mock":
        from data.mock import MockDataSource
        return MockDataSource(config.DATABASE_URL)

    raise ValueError(f"Unknown DATA_SOURCE: {config.DATA_SOURCE!r}. Supported: mock")
