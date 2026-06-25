from data.base import DataSource


def get_data_source() -> DataSource:
    import config

    from data.postgresql import PostgreSQLDataSource
    return PostgreSQLDataSource(config.DATABASE_URL)
