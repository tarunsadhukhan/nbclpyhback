"""Part G — does MobileFaceNet actually match YOUR enrolled faces?

Run this BEFORE trusting offline attendance. It is the one unproven assumption
the whole offline plan rests on.

    # 1. export the enrolment gallery from employee_face_mst.photo_html
    python tools/offline_sync/eval_mobile_face_model.py export --tenant nbcl --out gallery/ --limit 200

    # 2. photograph ~30 of those people on the shop floor, 3-5 shots each, in
    #    real light/dust/caps. Save as probes/<emp_code>/<anything>.jpg
    #    (emp_code must match the gallery file name).

    # 3. score
    python tools/offline_sync/eval_mobile_face_model.py score --gallery gallery/ --probes probes/

Reports rank-1 accuracy, the false-accept rate at each candidate threshold, and
the genuine/impostor score distributions. If rank-1 is under ~95%, switch to a
heavier model before writing any more app code.
"""
import argparse
import base64
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _db import add_tenant_arg, connect  # noqa: E402
from mobileface import MobileFaceEmbedder, embed_image_bytes  # noqa: E402

THRESHOLDS = [0.45, 0.50, 0.55, 0.60, 0.62, 0.65, 0.70]
MARGIN = 0.05


def cmd_export(args):
    from backfill_mobile_embeddings import _strip_data_url

    os.makedirs(args.out, exist_ok=True)
    db = connect(args.tenant)
    cursor = db.cursor(dictionary=True)
    where = ["f.active = 1", "p.active = 1", "f.photo_html IS NOT NULL", "f.photo_html <> ''"]
    params = []
    if args.branch:
        where.append("o.branch_id = %s")
        params.append(args.branch)
    cursor.execute(f"""SELECT f.emp_face_id, o.emp_code, f.photo_html
                       FROM employee_face_mst f
                       JOIN hrms_ed_personal_details p ON f.eb_id = p.eb_id
                       JOIN hrms_ed_official_details o ON p.eb_id = o.eb_id
                       WHERE {' AND '.join(where)}
                       ORDER BY f.emp_face_id LIMIT %s""", tuple(params) + (args.limit,))
    n = 0
    for row in cursor.fetchall():
        b64 = _strip_data_url(row['photo_html'])
        if not b64:
            continue
        path = os.path.join(args.out, f"{row['emp_code']}__{row['emp_face_id']}.jpg")
        with open(path, 'wb') as fh:
            fh.write(base64.b64decode(b64))
        n += 1
    cursor.close()
    db.close()
    print(f"exported {n} enrolment photos to {args.out}")


def _embed_dir(embedder, folder, label_from):
    """-> (labels, matrix) for every image under [folder]."""
    labels, vectors = [], []
    for root, _dirs, files in os.walk(folder):
        for name in sorted(files):
            if not name.lower().endswith(('.jpg', '.jpeg', '.png')):
                continue
            path = os.path.join(root, name)
            with open(path, 'rb') as fh:
                vector, reason = embed_image_bytes(embedder, fh.read())
            if vector is None:
                print(f"  - {path}: {reason}")
                continue
            labels.append(label_from(root, name))
            vectors.append(vector)
    return labels, (np.vstack(vectors) if vectors else np.zeros((0, 1), dtype=np.float32))


def cmd_score(args):
    embedder = MobileFaceEmbedder(args.model)

    print("embedding gallery…")
    g_labels, gallery = _embed_dir(
        embedder, args.gallery, lambda _root, name: name.split('__')[0])
    print("embedding probes…")
    p_labels, probes = _embed_dir(
        embedder, args.probes, lambda root, _name: os.path.basename(root))

    if len(g_labels) == 0 or len(p_labels) == 0:
        print("nothing to score — check the folders")
        return

    known = set(g_labels)
    missing = sorted(set(p_labels) - known)
    if missing:
        print(f"! {len(missing)} probe identities are not in the gallery: {missing[:10]}")

    sims = probes @ gallery.T          # both sides are L2-normalised → cosine
    g_arr = np.array(g_labels)

    genuine, impostor = [], []
    rank1_hits = scored = 0
    for i, true_label in enumerate(p_labels):
        if true_label not in known:
            continue
        scored += 1
        row = sims[i]
        order = np.argsort(-row)
        best, second = order[0], order[1] if len(order) > 1 else order[0]
        if g_arr[best] == true_label:
            rank1_hits += 1
        genuine.extend(row[g_arr == true_label].tolist())
        impostor.extend(row[g_arr != true_label].tolist())
        del second

    print("\n" + "=" * 62)
    print(f"gallery      : {len(g_labels)} photos, {len(known)} identities")
    print(f"probes       : {len(p_labels)} photos, {scored} scorable")
    print(f"rank-1       : {rank1_hits}/{scored} = {100.0 * rank1_hits / max(scored, 1):.2f}%")

    genuine = np.array(genuine)
    impostor = np.array(impostor)
    print(f"\ngenuine  cos : mean {genuine.mean():.3f}  p5 {np.percentile(genuine, 5):.3f}  min {genuine.min():.3f}")
    print(f"impostor cos : mean {impostor.mean():.3f}  p95 {np.percentile(impostor, 95):.3f}  max {impostor.max():.3f}")

    print("\nthreshold   FAR (impostor accepted)   FRR (genuine rejected)")
    for t in THRESHOLDS:
        far = float((impostor >= t).mean()) * 100
        frr = float((genuine < t).mean()) * 100
        print(f"  {t:.2f}        {far:8.3f}%                  {frr:7.2f}%")

    print(f"\nmargin rule (best - second >= {MARGIN}) is applied on top of the "
          "accept threshold on the device; it mostly removes look-alike pairs.")
    print("=" * 62)
    if scored and 100.0 * rank1_hits / scored < 95.0:
        print("\n!! rank-1 below 95% — do NOT ship offline face matching with this "
              "model. Try a heavier ArcFace/ResNet TFLite build (~25 MB).")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)

    e = sub.add_parser('export')
    add_tenant_arg(e)
    e.add_argument('--out', default='gallery')
    e.add_argument('--limit', type=int, default=200)
    e.add_argument('--branch', type=int)
    e.set_defaults(func=cmd_export)

    s = sub.add_parser('score')
    s.add_argument('--gallery', required=True)
    s.add_argument('--probes', required=True)
    s.add_argument('--model')
    s.set_defaults(func=cmd_score)

    args = ap.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
