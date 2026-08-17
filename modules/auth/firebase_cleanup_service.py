# modules/auth/firebase_cleanup_service.py

"""
Firebase Auth + Firestore Cleanup Service -- D3.

==================================================
GATE 1 AUDIT FINDING (grounds this file's exact scope)
==================================================
Zero backend Python file anywhere in this repository has EVER used
Firestore before this file -- confirmed by a repo-wide search (only
this file's own docstring and D1/D2's own text mention the word). This
is genuinely new backend surface area, not an extension of an existing
pattern.

Firebase Admin (`firebase_admin==7.1.0`) is already fully initialized
with a real service-account credential in `extensions.py::init_firebase()`
-- confirmed live: `firebase_admin.auth.delete_user` and
`firebase_admin.firestore.client` are both callable in this exact
environment with zero new dependency.

Firestore's real, complete account structure -- confirmed directly
from the Flutter repository (`firestore_profile_repository.dart`,
re-verified again for D3, not assumed from D0.1):
    users/{firebaseUid}                    (document)
    users/{firebaseUid}/profiles/{id}      (subcollection, N documents)
No other top-level collection or UID-owned document exists anywhere in
the Flutter codebase (verified via a repo-wide `.collection(` search --
"users" and "profiles" are the only two collection names that appear).

FCM/device-token data: confirmed there is NO Firestore-side storage of
this at all -- `fcm_token_manager.dart` sends the token to the BACKEND
(the existing `/api/users/update-fcm` endpoint), not to Firestore.
`app_users.fcm_token`/`users.fcm_token` are the only storage locations,
and both are already fully handled by D1 (deleted or nulled as part of
`delete_account_data()`). Responsibility #2 below is therefore a
documented no-op for this codebase, not unimplemented.

==================================================
OWNERSHIP (D0.1 lock, preserved)
==================================================
The backend is the ONLY authoritative owner of Firebase Auth/Firestore
deletion. Flutter must never call FirebaseAuth.currentUser.delete() or
delete any Firestore document itself for this flow -- this file is
reached exclusively from the backend (routes/routes_auth.py's
delete_account() route, D2), using the Admin SDK already initialized
server-side. No Flutter file is touched by this change.

==================================================
WHY NOT A GENERIC RECURSIVE-DELETE UTILITY
==================================================
Deliberately hardcoded to the EXACT, known "users/{uid}" +
"users/{uid}/profiles/*" shape above -- not a generic
"delete_path(path)" helper capable of removing arbitrary Firestore
data. A generic recursive deleter would be a genuinely dangerous
capability to introduce for what is, today, exactly two collection
names. `firebase_uid` is a required, non-optional parameter with no
default -- there is no code path in this file that can be pointed at a
namespace the caller didn't explicitly supply. This file does NOT
verify that supplied firebase_uid on its own; verifying it corresponds
to the authenticated caller is the ROUTE's job (D2, already proven by
that layer's own tests) -- this service trusts the value it is given,
exactly like modules/auth/account_deletion_service.py's
delete_account_data() trusts its own ResolvedIdentity input.

==================================================
IDEMPOTENCY
==================================================
A missing Firestore document/subcollection, or a missing Firebase Auth
user (firebase_admin.auth.UserNotFoundError), are both treated as
SUCCESS, not failure -- required for the retry behavior D2's route
relies on (see that file's own docstring for the full partial-failure
design). Any OTHER exception is raised as FirebaseCleanupError.

==================================================
ORDERING (D0.1/D3 lock)
==================================================
Firestore cleanup ALWAYS completes (or is confirmed already-absent)
BEFORE Firebase Auth deletion is even attempted. This is enforced by
plain sequential code, not a flag -- the Auth deletion call is
physically unreachable if the Firestore step raises.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from firebase_admin import auth as _default_auth_module
from firebase_admin import firestore as _default_firestore_module


class FirebaseCleanupError(Exception):
    """Raised only for a genuine failure -- never for the expected/
    idempotent 'already gone' case, which is success, not an
    exception."""


@dataclass(frozen=True)
class FirebaseCleanupResult:
    firebase_uid: str
    firestore_profiles_deleted: int = 0
    firestore_user_doc_deleted: bool = False
    firestore_already_absent: bool = False
    auth_user_deleted: bool = False
    auth_already_absent: bool = False


def cleanup_firebase_account(
    firebase_uid: str,
    *,
    firestore_client=None,
    auth_module=None,
) -> FirebaseCleanupResult:
    """
    Deletes the complete Firestore account tree for `firebase_uid`
    (profiles subcollection, then the parent user document), then
    deletes the Firebase Auth user LAST. `firebase_uid` must already be
    server-side verified by the caller -- this function does not, and
    cannot, re-derive or validate WHO it belongs to; see module
    docstring.

    `firestore_client`/`auth_module` are injectable (default to the
    real, already-initialized Admin SDK) purely so tests can supply
    fakes -- no real Firebase/Firestore call is ever made in this
    repository's own test suite.
    """
    if not firebase_uid:
        raise ValueError("firebase_uid is required")

    firestore_client = firestore_client if firestore_client is not None else _default_firestore_module.client()
    auth_module = auth_module if auth_module is not None else _default_auth_module

    # ---- Step 1: Firestore -- profiles subcollection, then the parent
    # user document. Hardcoded structure, see module docstring. ----
    user_doc_ref = firestore_client.collection("users").document(firebase_uid)

    profiles_deleted = 0
    try:
        for doc in list(user_doc_ref.collection("profiles").stream()):
            doc.reference.delete()
            profiles_deleted += 1
    except Exception as exc:
        raise FirebaseCleanupError(
            f"Firestore profile subcollection cleanup failed for firebase_uid={firebase_uid!r}: {exc}"
        ) from exc

    user_doc_existed = False
    try:
        snapshot = user_doc_ref.get()
        user_doc_existed = bool(snapshot.exists)
        if user_doc_existed:
            user_doc_ref.delete()
    except Exception as exc:
        raise FirebaseCleanupError(
            f"Firestore user document cleanup failed for firebase_uid={firebase_uid!r}: {exc}"
        ) from exc

    # ---- Step 2: Firebase Auth -- LAST, unreachable if step 1 raised. ----
    auth_user_deleted = False
    auth_already_absent = False
    try:
        auth_module.delete_user(firebase_uid)
        auth_user_deleted = True
    except auth_module.UserNotFoundError:
        auth_already_absent = True
    except Exception as exc:
        raise FirebaseCleanupError(
            f"Firebase Auth user deletion failed for firebase_uid={firebase_uid!r}: {exc}"
        ) from exc

    return FirebaseCleanupResult(
        firebase_uid=firebase_uid,
        firestore_profiles_deleted=profiles_deleted,
        firestore_user_doc_deleted=user_doc_existed,
        firestore_already_absent=(profiles_deleted == 0 and not user_doc_existed),
        auth_user_deleted=auth_user_deleted,
        auth_already_absent=auth_already_absent,
    )
