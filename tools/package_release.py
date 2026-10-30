"""Explicit source allowlist: never package account data or local environments."""
import hashlib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    files = [ROOT / name for name in ("run.bat", "bootstrap.py", "main.py", "requirements.txt",
                                      "README.md", "TEST_REPORT.md", "V21_TEST_REPORT.md", "COURSEWARE_BATCH_TEST_REPORT.md", "NAMING_V23_TEST_REPORT.md", "V1_TEST_REPORT.md",
                                      "V2_STAGE0_BASELINE.md", "V2_STAGE1.md", "V2_STAGE2.md", "V2_STAGE3.md",
                                      "tests/test_delivery.py", "tests/test_v2_delivery.py", "tests/test_layout_v21.py", "tests/test_courseware_batch.py", "tests/test_naming_v23.py")]
    files += sorted((ROOT / "ykt").glob("*.py"))
    output = ROOT / "dist/yuketang_resource_exporter_v2.3.zip"
    output.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for file in files:
            archive.write(file, file.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == {p.relative_to(ROOT).as_posix() for p in files}
        assert not any(part in (".local", ".venv", "html", "__pycache__")
                       for name in archive.namelist() for part in Path(name).parts)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(".sha256").write_text(digest + "  " + output.name + "\n", encoding="ascii")
    print("Packaged {} allowlisted source files; ZIP CRC verified".format(len(files)))
    print(digest)


if __name__ == "__main__":
    main()
