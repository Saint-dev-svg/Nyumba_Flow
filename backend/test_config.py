
import os

from app import create_app
from sqlalchemy.engine import URL


def create_test_app():
    test_database_url = URL.create(
        drivername="postgresql+psycopg",
        username=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        database="nyumbaflow_test",
    )

    return create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": test_database_url,
    })
