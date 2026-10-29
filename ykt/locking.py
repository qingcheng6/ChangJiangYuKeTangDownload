"""Non-blocking OS lease, released even when its owning process exits."""
import os


class BusyError(Exception):
    pass


class LocalLock:
    def __init__(self, path):
        self.path = path
        self.stream = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open("a+b")
        if self.stream.tell() == 0:
            self.stream.write(b"0")
            self.stream.flush()
        self.stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.stream.close()
            self.stream = None
            raise BusyError("本地资料正在使用，请等待其他任务结束") from None
        return self

    def __exit__(self, *args):
        if self.stream:
            self.stream.close()
            self.stream = None
