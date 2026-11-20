"""Atomic local JSON cache and task metadata."""

import json
import os
import time
from pathlib import Path
from typing import Any, Dict


def write_json(path: Path, value: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    for attempt in range(4):
        try:
            with temporary.open("w", encoding="utf-8") as stream:
                json.dump(value, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(str(temporary), str(path))
            return
        except PermissionError:
            # A Windows reader may briefly deny rename/delete sharing. Retry
            # only this local operation; never alter permissions or old data.
            if attempt == 3:
                raise
            time.sleep(0.05 * (2 ** attempt))



def read_json(path: Path) -> Dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("不支持的缓存版本，请重新扫描")
    return data
