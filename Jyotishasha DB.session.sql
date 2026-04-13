SELECT id, name, firebase_uid, created_at
FROM app_users
WHERE created_at >= NOW() - INTERVAL '3 days'
ORDER BY created_at DESC;