import os

from dotenv import load_dotenv
from flask import Flask, jsonify
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from sqlalchemy.engine import URL

load_dotenv()

db = SQLAlchemy()


def create_app():
    app = Flask(__name__)

    database_url = URL.create(
        drivername="postgresql+psycopg",
        username=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        database=os.getenv("DB_NAME", "nyumbaflow"),
    )

    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    Migrate(app, db)

    @app.get("/api/health")
    def health_check():
        return jsonify({
            "status": "ok",
            "application": "NyumbaFlow API"
        })

    @app.get("/api/db-health")
    def database_health_check():
        try:
            with db.engine.connect() as connection:
                connection.execute(text("SELECT 1"))

            return jsonify({
                "status": "connected",
                "database": "nyumbaflow"
            })
        except Exception:
            app.logger.exception("Database connection failed")
            return jsonify({
                "status": "error",
                "message": "Database connection failed. Check the backend logs."
            }), 500

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)