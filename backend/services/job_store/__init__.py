"""Unified job store: every generation, analysis, download and training run
records itself here, and the History tab reads nothing else."""

from services.job_store.job_models import Job, JobKind, JobOutput, JobStatus, JOB_KINDS, JOB_STATUSES
from services.job_store.sqlite_job_store import SqliteJobStore

__all__ = ["Job", "JobKind", "JobOutput", "JobStatus", "JOB_KINDS", "JOB_STATUSES", "SqliteJobStore"]
