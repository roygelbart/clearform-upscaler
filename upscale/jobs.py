from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class JobState:
    job_id: str
    created_at: float
    status: str
    total: int
    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    warnings: int = 0
    message: str = ""
    zip_path: Optional[str] = None
    report_path: Optional[str] = None
    current_item: str = ""
    items: List[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        progress = int((self.processed / self.total) * 100) if self.total else 0
        return {
            "job_id": self.job_id,
            "created_at": self.created_at,
            "status": self.status,
            "total": self.total,
            "processed": self.processed,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "skipped": self.skipped,
            "warnings": self.warnings,
            "message": self.message,
            "current_item": self.current_item,
            "progress": progress,
        }


class JobStore:
    def __init__(self) -> None:
        self._jobs: Dict[str, JobState] = {}
        self._lock = threading.Lock()

    def create(self, total: int) -> JobState:
        job_id = uuid.uuid4().hex
        state = JobState(job_id=job_id, created_at=time.time(), status="queued", total=total)
        with self._lock:
            self._jobs[job_id] = state
        return state

    def get(self, job_id: str) -> Optional[JobState]:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job_id: str, **kwargs) -> None:
        with self._lock:
            state = self._jobs.get(job_id)
            if not state:
                return
            for key, value in kwargs.items():
                setattr(state, key, value)

    def append_item(self, job_id: str, item: dict) -> None:
        with self._lock:
            state = self._jobs.get(job_id)
            if not state:
                return
            state.items.append(item)
