# modules/models_app_version_policy.py

"""
Force-Update / Minimum-Supported-Build Policy.

One row per platform (today: "android" only -- iOS is not built). This is
the ONLY place minimum_supported_build lives -- the Play Store build
itself never carries this decision, so it can be raised (or a rollout
frozen/reverted) without shipping a new app version at all, per the
Ask Now Security + Force Update task's own requirement.

Deliberately a plain, single-row-per-platform table -- same "one cache
row per key, update in place" shape already established by
CurrentEntitlement (modules/models_premium_subscription.py) and AppUser
itself, not a new pattern. No history/audit table: a change here is an
operational config flip, not a business event worth its own append-only
log (unlike SubscriptionEvent, which records financial state changes).

Version comparison is ALWAYS on the integer Android versionCode
(PackageInfo.buildNumber client-side, `flutter.versionCode` from
pubspec.yaml's `version: X.Y.Z+build` at build time) -- never a semantic-
version string. String comparison ("1.10.0" vs "1.9.0") sorts wrong;
integer versionCode comparison does not.
"""

from datetime import datetime
from extensions import db


class AppVersionPolicy(db.Model):
    __tablename__ = "app_version_policy"

    id = db.Column(db.Integer, primary_key=True)

    # "android" today; a distinct row per platform going forward if/when
    # iOS ships -- never a shared row two platforms both interpret.
    platform = db.Column(db.String(20), nullable=False, unique=True)

    # The integer versionCode/build number below which the app must be
    # blocked. Compared against PackageInfo.buildNumber on the client --
    # never a version STRING comparison (see module docstring).
    minimum_supported_build = db.Column(db.Integer, nullable=False)

    # The newest build actually published -- informational only today
    # (no "a newer build exists, please update" soft-nudge UI is built
    # in this phase); kept so that future soft-nudge UX has a real value
    # to read without a schema change.
    latest_build = db.Column(db.Integer, nullable=False)

    # Safe Deployment Split (Task B) -- descriptive/UI-severity metadata
    # ONLY. Deliberately NEVER an independent blocking condition: the
    # sole gate the client evaluates is
    # `installedBuild < minimum_supported_build` (see
    # lib/services/app_version_gate_service.dart's own docstring for the
    # real bug this correction fixes -- treating this as an
    # unconditional kill switch would block a build that IS the
    # current, fully-supported latest_build the moment an operator set
    # this for any other reason). To actually force every installed
    # build to update, raise minimum_supported_build itself -- that is
    # the only lever that does it. False in the seeded initial state.
    force_update = db.Column(db.Boolean, nullable=False, default=False)

    store_url = db.Column(db.String(500), nullable=False)

    # Optional, operator-supplied context shown alongside the client's
    # own static, branded, bilingual copy -- e.g. "Payment security
    # update required." NULL means the client shows only its own default
    # copy; this is never the ONLY source of the update message (the
    # blocking screen's primary text lives in Flutter, not fetched here
    # -- see lib/features/update_required/update_required_page.dart).
    message = db.Column(db.String(500), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False,
    )

    def to_public_dict(self) -> dict:
        """Only the fields the client-facing, unauthenticated
        /api/app/version-policy route ever returns -- created_at/updated_at/
        id are operational metadata, not part of the public contract."""
        return {
            "platform": self.platform,
            "minimum_supported_build": self.minimum_supported_build,
            "latest_build": self.latest_build,
            "force_update": self.force_update,
            "store_url": self.store_url,
            "message": self.message,
        }

    def __repr__(self) -> str:
        return (
            f"<AppVersionPolicy platform={self.platform} "
            f"minimum_supported_build={self.minimum_supported_build} "
            f"force_update={self.force_update}>"
        )
