INSERT INTO user_notifications (user_id, title, body, is_read)
SELECT id,
       '🎉 Congratulations!',
       'Now you will receive Tithi & Transit related alerts directly on your Jyotishasha notifications 🔔',
       false
FROM app_users
WHERE fcm_token IS NOT NULL;