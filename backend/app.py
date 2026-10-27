import os

from extensions import db
from dotenv import load_dotenv
from flask import Flask, jsonify
from flask_migrate import Migrate
from sqlalchemy import text
from sqlalchemy.engine import URL
from flask_jwt_extended import JWTManager
from auth import auth_bp
from invoices import invoices_bp
from leases import leases_bp
from payments import payments_bp
from properties import properties_bp
from reports import reports_bp
from tenants import tenants_bp
from units import units_bp
from utility_billing import utility_billing_bp

load_dotenv()


def create_app(test_config=None):
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
    app.config["JWT_SECRET_KEY"] = os.getenv("JWT_SECRET_KEY")
    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = 3600

    # Allow explicit test configuration (especially the test database URI) to
    # override environment-backed defaults.
    if test_config:
        app.config.update(test_config)

    if not app.config.get("JWT_SECRET_KEY"):
        raise RuntimeError("JWT_SECRET_KEY must be set in the environment or app config.")

    db.init_app(app)
    jwt = JWTManager(app)
    Migrate(app, db)
    app.register_blueprint(auth_bp)
    app.register_blueprint(invoices_bp)
    app.register_blueprint(leases_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(properties_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(tenants_bp)
    app.register_blueprint(units_bp)
    app.register_blueprint(utility_billing_bp)
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
