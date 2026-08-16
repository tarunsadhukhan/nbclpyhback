"""Fill employee_face_mst.face_embedding_mobile from the enrolment photos.

Workers do NOT need to re-enrol: photo_html already holds the original base64
JPEG, so the mobile embedding is derived from the same image the dlib embedding
came from.

    python tools/offline_sync/backfill_mobile_embeddings.py --tenant nbcl                # only missing rows
    python tools/offline_sync/backfill_mobile_embeddings.py --tenant nbcl --all          # re-embed everything
    python tools/offline_sync/backfill_mobile_embeddings.py --tenant nbcl --branch 3     # one branch
    python tools/offline_sync/backfill_mobile_embeddings.py --tenant nbcl --limit 200

Idempotent and resumable — stop it any time and run it again.
"""
import argparse
import base64
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _db import add_tenant_arg, connect  # noqa: E402
from mobileface import MODEL_VER, MobileFaceEmbedder, embed_image_bytes  # noqa: E402


def _strip_data_url(photo_html):
    """photo_html may be a bare base64 blob or a data: URL / <img> tag."""
    if not photo_html:
        return None
    text = photo_html.strip()
    if 'base64,' in text:
        text = text.split('base64,', 1)[1]
        text = text.split('"', 1)[0].split("'", 1)[0].split('>', 1)[0]
    return text.strip()


def main():
    ap = argparse.ArgumentParser()
    add_tenant_arg(ap)
    ap.add_argument('--all', action='store_true', help='re-embed rows that already have one')
    ap.add_argument('--branch', type=int, help='restrict to one branch_id')
    ap.add_argument('--limit', type=int, default=0, help='stop after N rows')
    ap.add_argument('--model', help='path to the MobileFaceNet model')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    embedder = MobileFaceEmbedder(args.model)
    print(f"model : {embedder.model_path}\nver   : {MODEL_VER}")

    where = ["f.active = 1", "f.photo_html IS NOT NULL", "f.photo_html <> ''"]
    params = []
    if not args.all:
        where.append("(f.face_embedding_mobile IS NULL OR f.mobile_model_ver <> %s)")
        params.append(MODEL_VER)
    join = ""
    if args.branch:
        join = "JOIN hrms_ed_official_details o ON f.eb_id = o.eb_id"
        where.append("o.branch_id = %s")
        params.append(args.branch)

    db = connect(args.tenant)
    cursor = db.cursor(dictionary=True)
    cursor.execute(f"""SELECT f.emp_face_id, f.eb_id, f.photo_html
                       FROM employee_face_mst f {join}
                       WHERE {' AND '.join(where)}
                       ORDER BY f.emp_face_id""", tuple(params))
    rows = cursor.fetchall()
    if args.limit:
        rows = rows[:args.limit]
    print(f"rows  : {len(rows)}")

    ok = skipped = failed = 0
    for i, row in enumerate(rows, 1):
        b64 = _strip_data_url(row['photo_html'])
        if not b64:
            skipped += 1
            continue
        try:
            vector, reason = embed_image_bytes(embedder, base64.b64decode(b64))
        except Exception as exc:
            print(f"  ! emp_face_id={row['emp_face_id']} decode/embed failed: {exc}")
            failed += 1
            continue
        if vector is None:
            print(f"  - emp_face_id={row['emp_face_id']} skipped ({reason})")
            skipped += 1
            continue
        if not args.dry_run:
            cursor.execute("""UPDATE employee_face_mst
                              SET face_embedding_mobile = %s, mobile_model_ver = %s,
                                  mobile_embed_updated = %s
                              WHERE emp_face_id = %s""",
                           (json.dumps([round(float(v), 6) for v in vector]),
                            MODEL_VER, datetime.now(), row['emp_face_id']))
            db.commit()   # commit per row so an interrupted run keeps its progress
        ok += 1
        if i % 25 == 0:
            print(f"  … {i}/{len(rows)}")

    cursor.close()
    db.close()
    print(f"\ndone: {ok} embedded, {skipped} skipped (no usable face), {failed} failed")
    if skipped:
        print("Skipped rows have no detectable face in the enrolment photo — those "
              "employees stay online-only until they are re-enrolled.")


if __name__ == '__main__':
    main()
