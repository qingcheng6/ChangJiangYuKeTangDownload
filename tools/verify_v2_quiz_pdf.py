"""Real authorized downloads for stage 2, isolated from historical output."""
import hashlib
import sys
from pathlib import Path
from queue import Empty

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ykt.accounts import Accounts
from ykt.files import Manifest
from ykt.pdf_work import PdfWork
from ykt.quiz_pdf import verified_pdf
from ykt.storage import read_json, write_json
from ykt.worker import ScanWorker


def main():
    store = Accounts(ROOT, "https://changjiang.yuketang.cn")
    known = read_json(ROOT / ".local/v2_stage1/gui_live.json")
    row = store.get(known["new_account_id"])
    site = store.site_dir(row)
    cache = read_json(site / "courses.json")
    historic = read_json(next((ROOT / ".local/phase3_output/雨课堂习题下载").glob("任务清单_*.json")))
    tasks = []
    for status in ("complete", "no_images"):
        record = next(l for l in historic["lessons"].values() if l["status"] == status)
        course = next(c for c in cache["courses"] if c["id"] == record["course_id"])
        lesson = next(l for l in course["lessons"] if l["id"] == record["lesson_id"])
        tasks.append(dict(course_id=course["id"], course_name=course["name"], class_name=course["class_name"], lesson=lesson))
    base = ROOT / ".local/v2_stage2/live"
    base.mkdir(parents=True, exist_ok=True)
    proof = dict(schema_version=1, cases={})

    def run(name, options, folder=None, selected=None):
        directory = base / (folder or name)
        directory.mkdir(exist_ok=True)
        worker = ScanWorker(store.origin, site, account_id=row["id"], expected_owner=row["owner"], layout="v2")
        worker.start_download(selected or tasks, directory, row["owner"], options=options)
        result, features, errors = None, None, []
        while worker.running or not worker.events.empty():
            try:
                kind, data = worker.events.get(timeout=0.25)
            except Empty:
                continue
            if kind == "log":
                print(data, flush=True)
            elif kind == "download_result":
                result = data
            elif kind == "feature_progress":
                features = data
            elif kind in ("needs_human", "error"):
                errors.append(data)
                worker.stop()
        worker.thread.join()
        assert result is not None and not errors, "Real worker did not complete: " + repr(errors)
        manifest = Manifest(directory, row["owner"], store.origin, layout="v2")
        data = manifest.read_existing()
        pdfs = [l["quiz_pdf"] for l in data["lessons"].values() if l.get("quiz_pdf", {}).get("status") == "complete"]
        assert all(verified_pdf(manifest, pdf) for pdf in pdfs)
        proof["cases"][name] = dict(result=result, features=features, complete_pdf_pages=[p["pages"] for p in pdfs],
            jpg_files=len(list(directory.rglob("*.jpg"))), part_files=len(list(directory.rglob("*.part"))))
        write_json(ROOT / ".local/v2_stage2/live_verified.json", proof)
        print("CASE_VERIFIED=" + name, flush=True)
        return manifest, data, result

    combined = dict(quiz_images=True, quiz_pdf=True)
    pdf_only = dict(quiz_images=False, quiz_pdf=True)
    manifest, data, result = run("images_and_pdf", combined)
    assert result["success"] == 2 and result["downloaded"] == 14 and result["no_images"] == 1
    images_before = {p: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) for p in manifest.root.rglob("*.jpg")}
    pdf = next(manifest.root.rglob("*.pdf"))
    pdf_mtime = pdf.stat().st_mtime_ns
    _, _, result = run("combined_repeat", combined, "images_and_pdf")
    assert result["downloaded"] == 0 and result["skipped"] == 14 and pdf.stat().st_mtime_ns == pdf_mtime
    only, _, result = run("pdf_only", pdf_only)
    assert result["success"] == 2 and not list(only.root.rglob("*.jpg"))
    only_pdf = next(only.root.rglob("*.pdf"))
    only_mtime = only_pdf.stat().st_mtime_ns
    _, _, result = run("pdf_only_repeat", pdf_only, "pdf_only")
    assert result["downloaded"] == 0 and only_pdf.stat().st_mtime_ns == only_mtime
    for task in tasks:
        assert not PdfWork(site, row["id"], task, row["owner"], store.origin).root.exists()
    (ROOT / ".local/v2_stage2/own_pdf_corruption_backup.pdf").write_bytes(pdf.read_bytes())
    pdf.write_bytes(pdf.read_bytes()[:100])  # Only our newly-created verification PDF.
    _, _, result = run("corrupt_pdf_only_recovery", pdf_only, "images_and_pdf")
    assert result["downloaded"] == 0 and result["skipped"] == 14
    assert all((hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) == value for p, value in images_before.items())
    fault_dir = base / "partial_images"
    with Manifest(fault_dir, row["owner"], store.origin, layout="v2") as fault:
        lesson = fault.lesson(tasks[0])
        directory = fault.directory_for(tasks[0], lesson) / "习题图片"
        directory.mkdir(parents=True)
        collision = directory / "习题_001.jpg.part"
        collision.mkdir()
        fault.save()
    broken, broken_data, result = run("partial_images", combined, selected=[tasks[0]])
    assert result["failed"] == 1 and result["image_failed"] == 1 and result["downloaded"] == 13
    assert not list(broken.root.rglob("*.pdf"))
    failed_resource = next(r for l in broken_data["lessons"].values() for r in l["resources"].values() if r["status"] == "failed")
    assert failed_resource["attempts_last_run"] == 3
    assert base.resolve() in collision.resolve().parents and collision.is_dir() and not list(collision.iterdir())
    collision.rmdir()  # Only the exact empty test collision directory above.
    _, _, result = run("partial_resume", combined, "partial_images", selected=[tasks[0]])
    assert result["downloaded"] == 1 and result["skipped"] == 13 and result["success"] == 1
    _, image_data, result = run("images_only", dict(quiz_images=True, quiz_pdf=False))
    assert result["success"] == 2 and result["downloaded"] == 14
    assert all("quiz_pdf" not in l for l in image_data["lessons"].values())
    proof["historical_images_preserved"] = True
    proof["pdf_only_temporary_caches_removed"] = True
    write_json(ROOT / ".local/v2_stage2/live_verified.json", proof)
    print("REAL_STAGE2_CASES_PASSED", flush=True)


if __name__ == "__main__":
    main()
