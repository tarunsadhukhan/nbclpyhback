-- employee_face_mst.photo_thumb — the thumbnail cache /sync/face-embeddings
-- already reads and writes (src/mobileapp/src/sync/routes.py). Without the
-- column every gallery pull re-fetches each 60 KB photo_html and re-encodes it:
-- 18 MB and 6 s per 200-row page, on every sync. With it, that is paid once.
ALTER TABLE employee_face_mst ADD COLUMN photo_thumb MEDIUMTEXT NULL AFTER photo_html;
