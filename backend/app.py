import os

from extensions import db
from dotenv import load_dotenv
from flask import Flask, jsonify
from flask_migrate import Migrate
from sqlalchemy import text
from sqlalchemy.engine import URL
from flask_jwt_extended import JWTManager
from auth import auth_bp
from properties import properties_bp
from units import units_bp

load_dotenv()


def create_app(test_config=None):
    app = Flask(__name__)

    if test_config:
        app.config.update(test_config)

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
    app.config["JWT_SECRET_KEY"] = os.getenv("JWT_SECRET_KEY")
    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = 3600

    db.init_app(app)
    jwt = JWTManager(app)
    Migrate(app, db)
    app.register_blueprint(auth_bp)
    app.register_blueprint(properties_bp)
    app.register_blueprint(units_bp)
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

import models #Register models for Flask-Migrate

if __name__ == "__main__":
    app.run(debug=True)