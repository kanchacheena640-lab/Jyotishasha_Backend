UPDATE user_dasha_timeline
SET start_date = CURRENT_DATE + INTERVAL '5 days'
WHERE user_id = 276
LIMIT 1;