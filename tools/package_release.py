"""Explicit source allowlist: never package account data or local environments."""
import hashlib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    files = [ROOT / name for name in ("run.bat", "bootstrap.py", "main.py", "requirements.txt",
                                      "README.md", "TEST_REPORT.md", "tests/test_delivery.py")]
    files += sorted((ROOT / "ykt").glob("*.py"))
    output = ROOT / "dist/yuketang_exercise_downloader.zip"
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
