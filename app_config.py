import os

SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL")
SQLALCHEMY_TRACK_MODIFICATIONS = False
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "change-this-in-prod")
SECRET_KEY = os.getenv("SECRET_KEY", "fallback-secret")

