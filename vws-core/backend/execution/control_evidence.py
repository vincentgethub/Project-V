"""AX-02/40/41/44: validate immutable host controls without importing execution."""

from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.database import ExecutionFillRecord, JobRun, SecurityEvent
from backend.core.errors import LedgerIntegrityError
from backend.domain.models import FrozenModel
from backend.execution.models import ModeOverride

CONTROL_EVENTS = frozenset(
    {
        "EXECUTION_MODE_OVERRIDE",
        "LIVE_ENABLED",
        "LIVE_DISABLED",
        "DESK_JOB_BINDING",
        "HOST_ACCOUNTING_READY",
        "EXECUTION_FILL_NOTICE_QUEUED",
    }
)


class AccountBinding(FrozenModel):
    account_id: str = Field(strict=True, min_length=1, max_length=128)
    environment: Literal["PAPER", "LIVE"]
    config_hash: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator("account_id")
    @classmethod
    def identity(cls, value: str) -> str:
        if value != value.strip() or not value.isprintable():
            raise ValueError("Account identity must be printable without surrounding whitespace")
        return value


class JobBinding(AccountBinding):
    job_run_id: UUID


class FillNotice(FrozenModel):
    fill_id: UUID


class LiveDisable(FrozenModel):
    operator: str = Field(strict=True, min_length=1, max_length=128)

    @field_validator("operator")
    @classmethod
    def identity(cls, value: str) -> str:
        if value != value.strip() or not value.isprintable():
            raise ValueError("Operator identity must be printable without surrounding whitespace")
        return value


class LiveEnable(LiveDisable):
    account_id: str = Field(strict=True, min_length=1, max_length=128)
    paper_account_id: str = Field(strict=True, min_length=1, max_length=128)
    config_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    effective_hash: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator("account_id", "paper_account_id")
    @classmethod
    def account(cls, value: str) -> str:
        return AccountBinding.identity(value)


def validate_control(session: Session, record: SecurityEvent) -> None:
    if record.kind == "EXECUTION_FILL_NOTICE_QUEUED":
        notice = FillNotice.model_validate(record.detail)
        fill = session.get(ExecutionFillRecord, notice.fill_id)
        prior = session.scalar(
            select(SecurityEvent.seq).where(
                SecurityEvent.kind == record.kind,
                SecurityEvent.seq < record.seq,
                SecurityEvent.detail["fill_id"].as_string() == str(notice.fill_id),
            )
        )
        if fill is None or fill.seq >= record.seq or prior is not None:
            raise LedgerIntegrityError("AX-50: fill notice requires one prior canonical fill")
    elif record.kind == "EXECUTION_MODE_OVERRIDE":
        ModeOverride.model_validate(record.detail)
    elif record.kind == "LIVE_DISABLED":
        LiveDisable.model_validate(record.detail)
    elif record.kind == "LIVE_ENABLED":
        LiveEnable.model_validate(record.detail)
    elif record.kind == "HOST_ACCOUNTING_READY":
        AccountBinding.model_validate(record.detail)
    elif record.kind == "DESK_JOB_BINDING":
        proof = JobBinding.model_validate(record.detail)
        parent = session.get(JobRun, proof.job_run_id)
        prior = session.scalar(
            select(SecurityEvent.seq).where(
                SecurityEvent.kind == record.kind,
                SecurityEvent.seq < record.seq,
                SecurityEvent.detail["job_run_id"].as_string() == str(proof.job_run_id),
            )
        )
        if parent is None or parent.seq >= record.seq or prior is not None:
            raise LedgerIntegrityError("AX-40: desk job binding lacks one prior immutable run")
