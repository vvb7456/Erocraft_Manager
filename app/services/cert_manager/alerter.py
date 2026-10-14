"""Evaluate certificate problems and enqueue administrator notifications."""

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models.notifications import NotificationIssue

from app.core.time import utc_naive_now
from app.services.notifications.center import certificate_problems
from app.services.notifications.queue import enqueue_safely


async def run_certificate_alerts(db: AsyncSession, *, expiry_only: bool = False) -> list[dict]:
    results = []
    problems = await certificate_problems(db)
    await db.execute(delete(NotificationIssue).where(NotificationIssue.category == "certificate", NotificationIssue.key.not_in([p["key"] for p in problems])))
    for problem in problems:
        kind = problem["key"].split(":")[2]
        if (kind == "cert_source_expiring") != expiry_only:
            continue
        cert_id = int(problem["key"].split(":")[1])
        ids = await enqueue_safely(db, event_key=f"{problem['key']}:{utc_naive_now().date()}",
            category="certificate", severity=problem["severity"], title=problem["title"],
            body=problem["body"], path=problem["path"], context={"certificate_id": cert_id, "problem_key": problem["key"]})
        results.append({"certificate_id": cert_id, "type": kind, "queued": len(ids)})
    await db.commit()
    return results
