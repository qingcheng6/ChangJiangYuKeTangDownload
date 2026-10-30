"""Extract the public source ZIP and run its portable checks independently."""
import hashlib
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def main():
    archive_path=ROOT/'dist/yuketang_resource_exporter_v2.3_native_only.zip'
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
        log=ROOT/'.local/native_only/package_tests.log'
        with log.open('w',encoding='utf-8') as stream:
            # Existing Tk tests destroy their roots but leave reference cycles.
            # Collect between tests on the main thread, before worker tests can
            # trigger finalizers. No checks or core paths are skipped.
            runner="""import gc,sys,unittest
class MainThreadCleanup(unittest.TextTestResult):
    def stopTest(self,test):
        super().stopTest(test)
        gc.collect()
suite=unittest.defaultTestLoader.discover('tests')
result=unittest.TextTestRunner(verbosity=2,resultclass=MainThreadCleanup).run(suite)
sys.exit(not result.wasSuccessful())
"""
            result=subprocess.run([sys.executable,'-c',runner],
                                  cwd=destination,stdout=stream,stderr=subprocess.STDOUT,timeout=120)
        assert result.returncode==0,'Portable package tests failed; see private log'
        print(log.read_text('utf-8')[-150:])
        print('SOURCE_ZIP_CRC_SHA_AND_CONTENT_MATCH_PASS')


if __name__=='__main__':main()
