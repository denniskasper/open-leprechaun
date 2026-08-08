from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import AwareDatetime, BaseModel, Field

from open_leprechaun.auth import AdminDep
from open_leprechaun.db import EngineDep
from open_leprechaun.rates import ReferenceRateSourceDep
from open_leprechaun.repositories.reports import Refusal
from open_leprechaun.services import reports
from open_leprechaun.services.fx import RateUnavailableError
from open_leprechaun.services.section23 import LotShortfallError, StatutoryValueUnsetError
from open_leprechaun.services.statutory import FIRST_YEAR

router = APIRouter(tags=["reports"])


class GenerateReportRequest(BaseModel):
    # The statutory store's own era bound: an earlier year is a typo, not
    # history this application computes.
    year: int = Field(ge=FIRST_YEAR)


class GeneratedResponse(BaseModel):
    id: int


class ChangedInputResponse(BaseModel):
    """One input class whose current state no longer matches what the report
    was generated from — the staleness notice names these, with counts."""

    input_class: str
    stored_count: int | None
    current_count: int


class ReportSummaryResponse(BaseModel):
    id: int
    year: int
    status: Literal["draft", "final"]
    generated_at: AwareDatetime
    finalised_at: AwareDatetime | None
    stale: bool
    changed_inputs: list[ChangedInputResponse]

    @classmethod
    def of(cls, report: reports.ReportOverview) -> ReportSummaryResponse:
        return cls(**_lifecycle(report))


class ReportResponse(ReportSummaryResponse):
    # The frozen figures verbatim as generation stored them — decimals as
    # fixed-point strings, instants as ISO-8601 — never recomputed on read.
    figures: dict

    @classmethod
    def of(cls, report: reports.ReportDetail) -> ReportResponse:
        return cls(**_lifecycle(report), figures=report.figures)


def _lifecycle(report: reports.ReportOverview) -> dict:
    return {
        "id": report.id,
        "year": report.year,
        "status": report.status,
        "generated_at": report.generated_at,
        "finalised_at": report.finalised_at,
        "stale": report.stale,
        "changed_inputs": [
            ChangedInputResponse(
                input_class=changed.input_class,
                stored_count=changed.stored_count,
                current_count=changed.current_count,
            )
            for changed in report.changed_inputs
        ],
    }


@router.get(
    "/reports",
    summary="Every report, newest first, each wearing its staleness verdict",
    response_model=list[ReportSummaryResponse],
)
def list_reports(admin: AdminDep, engine: EngineDep) -> list[ReportSummaryResponse]:
    return [ReportSummaryResponse.of(report) for report in reports.overview(engine)]


@router.get(
    "/reports/{report_id}",
    summary="One report with its frozen figures, exactly as generated",
    response_model=ReportResponse,
)
def get_report(report_id: int, admin: AdminDep, engine: EngineDep) -> ReportResponse:
    report = reports.detail(engine, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="No such report.")
    return ReportResponse.of(report)


@router.post(
    "/reports",
    summary="Generate a new draft report for one tax year",
    status_code=201,
    response_model=GeneratedResponse,
)
def generate_report(
    request: GenerateReportRequest,
    admin: AdminDep,
    engine: EngineDep,
    source: ReferenceRateSourceDep,
) -> GeneratedResponse:
    try:
        created = reports.generate(engine, source, year=request.year)
    except (
        StatutoryValueUnsetError,
        LotShortfallError,
        RateUnavailableError,
        reports.GenerationRacedError,
    ) as refusal:
        # The request is well-formed; the data underneath cannot honestly
        # produce the figure — the sentence names what stands in the way.
        raise HTTPException(status_code=409, detail=str(refusal)) from refusal
    return GeneratedResponse(id=created)


@router.post(
    "/reports/{report_id}/finalise",
    summary="Move a draft report to final — the one transition, made explicitly",
    status_code=204,
)
def finalise_report(report_id: int, admin: AdminDep, engine: EngineDep) -> None:
    refused = reports.finalise(engine, report_id)
    if refused is Refusal.no_such_report:
        raise HTTPException(status_code=404, detail="No such report.")
    if refused is Refusal.already_final:
        raise HTTPException(status_code=409, detail="This report is already final.")
