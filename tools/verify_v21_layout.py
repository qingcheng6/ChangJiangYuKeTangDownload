"""Authorized live archive check; output is confined to the local QA directory."""
import sys
from pathlib import Path
from queue import Empty
from threading import Event

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ykt.accounts import Accounts
from ykt.files import Manifest
from ykt.quiz_pdf import verified_pdf
from ykt.courseware import verified_courseware
from ykt.storage import read_json, write_json
from ykt.worker import ScanWorker


def main():
    accounts = Accounts(ROOT, "https://changjiang.yuketang.cn")
    row = next(r for r in accounts.rows if r["legacy"])
    task = read_json(ROOT / ".local/v2_stage3/page_probe.json")["task"]
    base = ROOT / ".local/v21"
    proof = dict(schema_version=1, cases={})
    def run(name, folder, images):
        directory = accounts.image_directory(row, base / folder, layout="flat")
        worker = ScanWorker(accounts.origin, accounts.site_dir(row), account_id=row["id"],
                            expected_owner=row["owner"], layout="flat")
        worker.start_download([task], directory, row["owner"],
                              dict(quiz_images=images, quiz_pdf=True, courseware_pdf=True))
        result = None
        errors = []
        while worker.running or not worker.events.empty():
            try:
                kind, data = worker.events.get(timeout=.25)
            except Empty:
                continue
            if kind in ("error", "needs_human"):
                errors.append(kind)
                worker.stop()
            if kind == "download_result":
                result = data
        worker.thread.join()
        assert result and result["success"] == 1 and not errors, (name, result, errors)
        manifest = Manifest(directory, row["owner"], accounts.origin, layout="flat")
        data = manifest.read_existing()
        lesson = next(iter(data["lessons"].values()))
        course = manifest.resolve(data["courses"][task["course_id"]])
        assert verified_pdf(manifest, lesson["quiz_pdf"], Event())
        assert verified_courseware(manifest, lesson["courseware_pdf"], Event())
        for feature in ("quiz_pdf", "courseware_pdf"):
            assert manifest.resolve(lesson[feature]["path"]).parent == course
        pictures = list(directory.rglob("*.jpg"))
        assert len(pictures) == (14 if images else 0)
        assert all(p.parent.parent == course / "习题图片" for p in pictures)
        assert (course / "习题图片").exists() == images
        assert lesson["quiz_pdf"]["pages"] == 14 and lesson["courseware_pdf"]["pages"] == 44
        assert not list(directory.rglob("*.part"))
        products = {str(p.relative_to(directory)): (p.read_bytes(), p.stat().st_mtime_ns)
                    for p in directory.rglob("*") if p.suffix in (".jpg", ".pdf")}
        proof["cases"][name] = dict(result=result, images=len(pictures), quiz_pdf_pages=14,
            courseware_pdf_pages=44, flat_pdf_parents_verified=True, no_empty_image_directory=not images,
            worker_closed=not worker.running)
        write_json(base / "real_layout_verified.json", proof)
        print("V21_REAL_CASE", name, "passed", flush=True)
        return products
    first = run("three_features", "real_output", True)
    assert run("three_features_repeat", "real_output", True) == first
    run("pdf_only", "real_pdf_only", False)
    proof["unchanged_bytes_and_mtime_on_repeat"] = True
    write_json(base / "real_layout_verified.json", proof)
    print("V21_REAL_ARCHIVE_CHECK_PASSED", flush=True)


if __name__ == "__main__":
    main()
