import json
import os
from datetime import datetime
from pathlib import Path


class JsonStorage:
    def __init__(self, data_dir: str = "data/daily"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def _filepath(self, date_str: str = None) -> Path:
        if date_str is None:
            date_str = datetime.now().strftime("%Y-%m-%d")
        return self.data_dir / f"{date_str}.json"

    def save(self, data: dict, date_str: str = None):
        filepath = self._filepath(date_str)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return filepath

    def load(self, date_str: str = None) -> dict:
        filepath = self._filepath(date_str)
        if not filepath.exists():
            return {}
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)

    def list_dates(self) -> list:
        files = sorted(self.data_dir.glob("*.json"), reverse=True)
        return [f.stem for f in files]

    def copy_to_web(self, date_str: str = None, web_data_dir: str = "web/data"):
        src = self._filepath(date_str)
        if not src.exists():
            return None
        dst_dir = Path(web_data_dir)
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / src.name
        with open(src, "r", encoding="utf-8") as f:
            content = f.read()
        with open(dst, "w", encoding="utf-8") as f:
            f.write(content)
        return dst
