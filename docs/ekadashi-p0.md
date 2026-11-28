# Ekadashi P0 backend contract

The annual JSON contains one primary Lucknow observance per lunar cycle. Each
row can include separately dated Gauna or Vaishnava alternatives with their
own Parana. Repeated annual occurrences, such as the two Safala dates in
2027, remain separate rows with the same slug.

## API

- GET /api/ekadashi/all?year=2027 retains status, year, count, and data.
- GET /api/ekadashi/find-by-slug/saphala?year=2027 retains a single data
  object, selecting the first primary match.
- Add date=2027-12-23 to select an exact primary or alternate vrat date.
  Year can be inferred from date. A conflicting year or malformed date is
  a 400. A valid date with no matching occurrence is a 404.
- Add include_occurrences=true to get an occurrences array of all primary
  rows for that slug and year, including any nested alternate_observances.

Parana start and end are the recommended local window in IST with complete
dates. Dwadashi end is exposed separately as dwadashi_end, including when
it occurs on a different civil date. The rule field describes how the window
was selected. Pratahkal and Aparahna are the first and fourth fifths of
local daylight. If Dwadashi ends before sunrise, the next morning window is
used. If the usual periods are unavailable, the remaining daylight within
Dwadashi after Hari Vasara is used when available.

## Shared lunar-month dependency

The engine still reads name and is_adhik from get_lunar_month and retains
the existing +1 name lookup for regular festivals. The month label in
tithi.month therefore inherits the shared engine's known error. For example,
Utpanna still carries Kartik, and Padmini still carries Vaishakha in the
current JSON. Padmini and Parama retain their existing slugs and Adhik flags.
When the shared month engine is corrected, coordinate removal of the lookup
offset and verify all 26 slugs and both Adhik observances before regenerating
the data.

## Reference calendars

- https://www.drikpanchang.com/vrats/ekadashidates.html?year=2026&geoname-id=1264733
- https://www.drikpanchang.com/vrats/ekadashidates.html?year=2027&geoname-id=1264733
