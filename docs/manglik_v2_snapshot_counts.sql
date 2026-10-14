-- REVIEW ONLY: execute only after explicit production read authorization.
-- Read seven source columns; export no identifiers or birthplace text.
WITH source AS (
    SELECT firebase_uid, dob, tob, pob, lat, lng, static_dosh
    FROM public.app_users
), parsed AS (
    SELECT *,
        CASE WHEN length(dob) = 10 AND dob ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
             THEN substring(dob FROM 1 FOR 4)::integer END AS yr,
        CASE WHEN length(dob) = 10 AND dob ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
             THEN substring(dob FROM 6 FOR 2)::integer END AS mo,
        CASE WHEN length(dob) = 10 AND dob ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
             THEN substring(dob FROM 9 FOR 2)::integer END AS dy
    FROM source
), classified AS (
    SELECT *, CASE
        WHEN firebase_uid IS NULL THEN 'unlinked'
        WHEN dob IS NULL OR dob = '' OR tob IS NULL OR tob = ''
          OR pob IS NULL OR pob = '' OR lat IS NULL OR lng IS NULL
            THEN 'incomplete'
        WHEN NOT COALESCE(
            yr BETWEEN 1 AND 9999 AND mo BETWEEN 1 AND 12
            AND dy BETWEEN 1 AND CASE
                WHEN mo = 2 THEN CASE WHEN yr % 400 = 0 OR (yr % 4 = 0 AND yr % 100 <> 0)
                                      THEN 29 ELSE 28 END
                WHEN mo IN (4, 6, 9, 11) THEN 30 ELSE 31 END
            AND length(tob) = 5 AND tob ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$'
            AND pob ~ '[^[:space:]]'
            AND lat BETWEEN -90 AND 90 AND lng BETWEEN -180 AND 180,
            FALSE) THEN 'invalid_input'
        ELSE 'eligible'
    END AS eligibility
    FROM parsed
)
SELECT jsonb_build_object(
    'database_total', count(*),
    'unlinked', count(*) FILTER (WHERE eligibility = 'unlinked'),
    'incomplete', count(*) FILTER (WHERE eligibility = 'incomplete'),
    'invalid_input', count(*) FILTER (WHERE eligibility = 'invalid_input'),
    'eligible', count(*) FILTER (WHERE eligibility = 'eligible'),
    'old_json_missing', count(*) FILTER (
        WHERE eligibility = 'eligible'
          AND (static_dosh IS NULL OR jsonb_typeof(static_dosh) = 'null')),
    'old_json_malformed', count(*) FILTER (
        WHERE eligibility = 'eligible' AND CASE
            WHEN static_dosh IS NULL OR jsonb_typeof(static_dosh) = 'null' THEN FALSE
            WHEN jsonb_typeof(static_dosh) <> 'object' THEN TRUE
            WHEN NOT (static_dosh ? 'manglik') THEN FALSE
            WHEN jsonb_typeof(static_dosh -> 'manglik') = 'object'
              AND jsonb_typeof(static_dosh -> 'manglik' -> 'severity') = 'string'
              AND static_dosh -> 'manglik' ->> 'severity' IN ('Strong', 'Partial')
                THEN FALSE
            ELSE TRUE END)
)::text AS aggregate_counts
FROM classified;
