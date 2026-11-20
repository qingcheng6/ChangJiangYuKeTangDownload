"""Run every available unittest; finalize destroyed Tk fixtures on the main thread."""
import gc
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class MainThreadCleanup(unittest.TextTestResult):
    def stopTest(self, test):
        super().stopTest(test)
        # Older Tk tests leave reference cycles after destroying their roots.
        # Do not let a later browser worker trigger those GUI finalizers.
        gc.collect()


def main():
    suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'))
    result = unittest.TextTestRunner(verbosity=2, resultclass=MainThreadCleanup).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
