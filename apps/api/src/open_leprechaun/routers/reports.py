from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import AwareDatetime, BaseModel, Field, StringConstraints

from open_leprechaun.auth import AdminDep
from open_leprechaun.db import EngineDep
from open_leprechaun.rates import ReferenceRateSourceDep
from open_leprechaun.repositories.reports import Refusal
from open_leprechaun.services import appendix, reports
from open_leprechaun.services.fx import RateUnavailableError
from open_leprechaun.services.section23 import LotShortfallError, StatutoryValueUnsetError
from open_leprechaun.services.security_disposals import UnclassifiedSecurityError
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


class BlockerResponse(BaseModel):
    """One reason finalisation must wait: what kind of problem, a sentence
    naming it, how many instances stand open, and the path of the screen
    that resolves it."""

    kind: str
    detail: str
    resolve_path: str
    count: int


class OverrideRequest(BaseModel):
    """The Admin's deliberate acknowledgement that the blockers are
    understood and finalisation shall proceed over them."""

    acknowledgement: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class FinaliseReportRequest(BaseModel):
    override: OverrideRequest | None = None


class ReportSummaryResponse(BaseModel):
    id: int
    year: int
    status: Literal["draft", "final"]
    generated_at: AwareDatetime
    finalised_at: AwareDatetime | None
    stale: bool
    changed_inputs: list[ChangedInputResponse]
    # The pre-flight override, where finalisation was one: the
    # acknowledgement and the blockers it overrode, as recorded.
    override_acknowledgement: str | None
    overridden_blockers: list[BlockerResponse] | None

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
        "override_acknowledgement": report.override_acknowledgement,
        "overridden_blockers": report.overridden_blockers,
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
        UnclassifiedSecurityError,
        RateUnavailableError,
        reports.GenerationRacedError,
    ) as refusal:
        # The request is well-formed; the data underneath cannot honestly
        # produce the figure — the sentence names what stands in the way.
        raise HTTPException(status_code=409, detail=str(refusal)) from refusal
    return GeneratedResponse(id=created)


@router.get(
    "/reports/{report_id}/appendix.csv",
    summary="The report's line items behind every headline figure, as CSV",
)
def report_appendix_csv(report_id: int, admin: AdminDep, engine: EngineDep) -> Response:
    assembled = _appendix(engine, report_id)
    return Response(
        content=appendix.csv_export(assembled),
        media_type="text/csv; charset=utf-8",
        headers=_attachment(assembled, "csv"),
    )


@router.get(
    "/reports/{report_id}/appendix.pdf",
    summary="The same appendix, same figures, in archival form",
)
def report_appendix_pdf(report_id: int, admin: AdminDep, engine: EngineDep) -> Response:
    assembled = _appendix(engine, report_id)
    return Response(
        content=appendix.pdf_export(assembled),
        media_type="application/pdf",
        headers=_attachment(assembled, "pdf"),
    )


def _appendix(engine: EngineDep, report_id: int) -> appendix.Appendix:
    assembled = appendix.assemble(engine, report_id)
    if assembled is None:
        raise HTTPException(status_code=404, detail="No such report.")
    return assembled


def _attachment(assembled: appendix.Appendix, extension: str) -> dict[str, str]:
    filename = f"report-{assembled.report_id}-{assembled.year}-appendix.{extension}"
    return {"Content-Disposition": f'attachment; filename="{filename}"'}


@router.post(
    "/reports/{report_id}/finalise",
    summary="Move a draft report to final — the one transition, made explicitly",
    status_code=204,
)
def finalise_report(
    report_id: int,
    admin: AdminDep,
    engine: EngineDep,
    request: FinaliseReportRequest | None = None,
) -> None:
    override = request.override if request is not None else None
    refused = reports.finalise(
        engine,
        report_id,
        acknowledgement=override.acknowledgement if override is not None else None,
    )
    if refused is Refusal.no_such_report:
        raise HTTPException(status_code=404, detail="No such report.")
    if refused is Refusal.already_final:
        raise HTTPException(status_code=409, detail="This report is already final.")
    if isinstance(refused, reports.Blocked):
        raise HTTPException(
            status_code=409,
            detail={
                "message": "The report cannot be finalised while the application"
                " already knows something is wrong.",
                "blockers": [
                    BlockerResponse(
                        kind=blocker.kind,
                        detail=blocker.detail,
                        resolve_path=blocker.resolve_path,
                        count=blocker.count,
                    ).model_dump()
                    for blocker in refused.blockers
                ],
            },
        )
