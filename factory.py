from flask import Flask
from dotenv import load_dotenv
import os
import app_config
from db_safety import enforce_local_database_safety
from extensions import db, jwt, init_firebase   # 🔥 ADD THIS

load_dotenv()

def create_app():
    app = Flask(__name__)

    app.config.from_object(app_config)

    # LOCAL/PRODUCTION SAFETY BOUNDARY -- Phase 1. Must run before
    # DATABASE_URL is wired into SQLAlchemy and before db.create_all()
    # below ever touches a table. See db_safety.py's own docstring for
    # the full decision contract; this call never prints secrets and
    # never connects to the database to make its decision.
    enforce_local_database_safety(os.getenv("DATABASE_URL"))

    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    jwt.init_app(app)

    init_firebase()   # 🔥 THIS LINE IS THE FIX

    # U6A.1 -- REMOVED: `with app.app_context(): db.create_all()`.
    #
    # This used to run on EVERY app startup (local dev, tests importing
    # `app`/`create_app`, gunicorn workers in production alike -- this
    # function has no environment branch of its own) and would silently
    # CREATE ANY MISSING TABLE for every currently-registered SQLAlchemy
    # model, using whatever bare column/type/nullable shape that model
    # happens to declare RIGHT NOW -- never the actual reviewed Alembic
    # migration for that table (no indexes beyond what the model
    # declares, no server_default nuances, no seed data such as
    # migration 0e2036a0b4b7's 13 seeded Ask Now categories). Two
    # earlier migrations (b3f8e6a2c9d4, c7d2f5a9e1b3) already had to be
    # written DEFENSIVELY around this exact behavior (existence-checking
    # a table/constraint before creating it, because a create_all()'d
    # local dev DB might already silently have it) -- direct, pre-
    # existing evidence this was a live correctness hazard, not a
    # hypothetical one. U6A's own saved_audiences table hit it for
    # real: create_all() created the table (matching the model exactly,
    # by luck) BEFORE Alembic ever got a chance to run its own
    # migration -- see 9f2a5c7e1b83_add_saved_audiences_table.py's own
    # migration-quality review (U6A.1) for the full incident.
    #
    # Frozen rule from here on: MODEL CHANGE -> `flask db migrate`
    # (reviewed) -> `flask db upgrade` -> PostgreSQL schema. Alembic is
    # the ONE schema source of truth, in every environment, including a
    # brand-new local dev DB (bootstrap it with `flask db upgrade`, not
    # by running this app once). Normal app startup (`python app.py`,
    # gunicorn, any `flask db ...`/`flask shell` command, any test that
    # imports `app`/`create_app`) now NEVER mutates schema as a side
    # effect of merely importing this module -- verified directly
    # (U6A.1): db.metadata's full set of registered model tables was
    # already an EXACT match for jyotishasha_local's real tables before
    # this line was removed, so removing it changes nothing about any
    # already-migrated environment's schema, local or production.
    #
    # An isolated test that needs its own throwaway schema (e.g.
    # test_activity_events_foundation.py's deliberately-unreachable-DB
    # subprocess) must build its own separate Flask+SQLAlchemy app and
    # call db.create_all() there explicitly -- exactly the pattern that
    # test already uses today, specifically so it never touches this
    # app/this factory at all.

    return app