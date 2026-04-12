SELECT id, name, email, firebase_uid, fcm_token
FROM app_users
WHERE fcm_token IS NOT NULL;