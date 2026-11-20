"""Extract the public source ZIP and run its portable checks independently."""
import hashlib
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def main():
    archive_path=ROOT/'dist/yuketang_resource_exporter_v2.3_shared_grid.zip'
    expected=archive_path.with_suffix('.sha256').read_text('ascii').split()[0]
    assert hashlib.sha256(archive_path.read_bytes()).hexdigest()==expected
    with tempfile.TemporaryDirectory(prefix='ykt_answers_release_') as temporary:
        destination=Path(temporary)
        with zipfile.ZipFile(archive_path) as archive:
            assert archive.testzip() is None
            for item in archive.infolist():
                assert not Path(item.filename).is_absolute() and '..' not in Path(item.filename).parts
                assert archive.read(item)==(ROOT/item.filename).read_bytes()
            archive.extractall(destination)
        log=ROOT/'.local/courseware_grid/package_tests.log'
        with log.open('w',encoding='utf-8') as stream:
            result=subprocess.run([sys.executable,str(destination/'run_tests.py')],
                                  cwd=destination,stdout=stream,stderr=subprocess.STDOUT,timeout=120)
        assert result.returncode==0,'Portable package tests failed; see private log'
        print(log.read_text('utf-8')[-150:])
        print('SOURCE_ZIP_CRC_SHA_AND_CONTENT_MATCH_PASS')


if __name__=='__main__':main()
