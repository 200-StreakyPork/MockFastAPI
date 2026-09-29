"""Input and output shapes for leave requests."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


LeaveType = Literal["annual", "sick", "personal", "compensatory"]


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("datetime must include a timezone")
    return value.astimezone(timezone.utc)


class LeaveCreate(BaseModel):
    days: Decimal = Field(gt=0)
    leave_type: LeaveType
    start_at: datetime
    end_at: datetime
    approver_id: int
    reason: str = Field(min_length=1)

    @field_validator("start_at", "end_at")
    @classmethod
    def normalize_datetime(cls, value: datetime) -> datetime:
        return as_utc(value)

    @model_validator(mode="after")
    def check_interval(self) -> "LeaveCreate":
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be later than start_at")
        return self


class LeavePatch(BaseModel):
    days: Decimal | None = Field(default=None, gt=0)
    leave_type: LeaveType | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    approver_id: int | None = None
    reason: str | None = Field(default=None, min_length=1)

    @field_validator("start_at", "end_at")
    @classmethod
    def normalize_datetime(cls, value: datetime | None) -> datetime | None:
        return as_utc(value) if value is not None else None


class LeaveDecision(BaseModel):
    decision: Literal["approved", "rejected"]


class LeaveOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    days: Decimal
    leave_type: str
    start_at: datetime
    end_at: datetime
    applicant_id: int
    approver_id: int
    created_at: datetime
    updated_at: datetime
    decided_at: datetime | None
    decision: str | None
    status: str
    reason: str

    @field_validator("start_at", "end_at", "created_at", "updated_at", "decided_at", mode="before")
    @classmethod
    def normalize_output_datetime(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        # MySQL DATETIME discards timezone metadata; all stored values are UTC.
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
