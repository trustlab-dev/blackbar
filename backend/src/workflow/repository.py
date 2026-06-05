"""
Workflow repository — advanced workflow and queue management.

Handles database operations for:
- Clock events
- Case messages
- Case contributors
- Case reminders
"""

import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta

from motor.motor_asyncio import AsyncIOMotorDatabase


def _parse_iso_naive(value: str) -> datetime:
    """Parse an ISO-format datetime string into a NAIVE datetime.

    Phase 4 Batch 4.4 (audit B43): the repository compares parsed
    timestamps against `datetime.utcnow()` (naive), so any `Z`-suffixed
    ISO string must be coerced back to naive after parsing. Without
    this normalisation, external writers that drop "...Z" strings into
    Mongo trip a `TypeError` (`can't subtract offset-naive and offset-
    aware datetimes`) at the arithmetic site. Same defect class as
    B11, which was previously fixed in `collection_link_service`.
    """
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.replace(tzinfo=None)
    return parsed


from .models import (
    CaseContributor,
    CasePriorityScore,
    CaseReminder,
    CaseTransfer,
    ClockEvent,
    ClockEventCreate,
    ClockEventType,
    ClockPauseReason,
    ClockStatus,
    ContributorCreate,
    ContributorStatus,
    ContributorUpdate,
    QueueFilter,
    ReminderCreate,
    ReminderStatus,
    TransferCreate,
)

logger = logging.getLogger(__name__)


def hash_token(token: str) -> str:
    """Hash a token using SHA-256. Tokens are high-entropy so don't need slow hashing."""
    return hashlib.sha256(token.encode()).hexdigest()


def verify_token(token: str, token_hash: str) -> bool:
    """Verify a token against its hash."""
    return hashlib.sha256(token.encode()).hexdigest() == token_hash


class ClockEventsRepository:
    """Repository for statutory clock events"""

    def __init__(self, db: AsyncIOMotorDatabase):
        self.collection = db.clock_events
        self.cases = db.cases

    async def create(
        self, case_id: str, event_data: ClockEventCreate, user_id: str, user_name: str
    ) -> ClockEvent:
        """Create a new clock event"""
        event_id = str(uuid.uuid4())
        now = datetime.utcnow()

        # Calculate days elapsed at this event
        case = await self.cases.find_one({"id": case_id})
        days_elapsed = 0
        if case and case.get("received_date"):
            received = case["received_date"]
            if isinstance(received, str):
                received = _parse_iso_naive(received)
            days_elapsed = (now - received).days

        event_dict = {
            "id": event_id,
            "case_id": case_id,
            "event_type": event_data.event_type.value,
            "reason": event_data.reason.value if event_data.reason else None,
            "event_date": now,
            "created_by": user_id,
            "created_by_name": user_name,
            "notes": event_data.notes,
            "days_elapsed_at_event": days_elapsed,
        }

        await self.collection.insert_one(event_dict)

        # Update case clock status
        await self._update_case_clock_status(case_id, event_data.event_type, event_data.reason, now)

        return ClockEvent(**event_dict)

    async def _update_case_clock_status(
        self,
        case_id: str,
        event_type: ClockEventType,
        reason: ClockPauseReason | None,
        event_date: datetime,
    ):
        """Update case document with clock status"""
        update = {"updated_at": event_date}

        if event_type == ClockEventType.PAUSE:
            update["clock_status"] = "paused"
            update["clock_paused_at"] = event_date
            update["clock_pause_reason"] = reason.value if reason else None

            # Update workflow stage if fee-related
            if reason == ClockPauseReason.FEE_PENDING:
                update["workflow_stage"] = "pending_fee_payment"
            elif reason == ClockPauseReason.PRIVACY_COMMISSION_REVIEW:
                update["workflow_stage"] = "privacy_commission_review"

        elif event_type == ClockEventType.RESUME:
            # Calculate paused days
            case = await self.cases.find_one({"id": case_id})
            paused_days = 0
            if case and case.get("clock_paused_at"):
                paused_at = case["clock_paused_at"]
                if isinstance(paused_at, str):
                    paused_at = _parse_iso_naive(paused_at)
                paused_days = (event_date - paused_at).days

            current_total = case.get("total_paused_days", 0) if case else 0

            update["clock_status"] = "running"
            update["clock_paused_at"] = None
            update["clock_pause_reason"] = None
            update["total_paused_days"] = current_total + paused_days

            # Recalculate adjusted due date
            if case and case.get("due_date"):
                original_due = case["due_date"]
                if isinstance(original_due, str):
                    original_due = _parse_iso_naive(original_due)
                update["adjusted_due_date"] = original_due + timedelta(
                    days=current_total + paused_days
                )

        elif event_type == ClockEventType.START:
            update["clock_status"] = "running"
            update["clock_paused_at"] = None
            update["total_paused_days"] = 0

        await self.cases.update_one({"id": case_id}, {"$set": update})

    async def get_by_case(self, case_id: str) -> list[ClockEvent]:
        """Get all clock events for a case"""
        cursor = self.collection.find({"case_id": case_id}).sort("event_date", 1)
        events = []
        async for doc in cursor:
            doc.pop("_id", None)
            events.append(ClockEvent(**doc))
        return events

    async def get_clock_status(self, case_id: str) -> ClockStatus:
        """Get current clock status for a case"""
        case = await self.cases.find_one({"id": case_id})
        events = await self.get_by_case(case_id)

        return ClockStatus(
            case_id=case_id,
            status=case.get("clock_status", "running") if case else "running",
            original_due_date=case.get("due_date") if case else None,
            adjusted_due_date=case.get("adjusted_due_date") if case else None,
            total_paused_days=case.get("total_paused_days", 0) if case else 0,
            current_pause_start=case.get("clock_paused_at") if case else None,
            current_pause_reason=case.get("clock_pause_reason") if case else None,
            events=events,
        )


class ContributorsRepository:
    """Repository for case contributors (named record providers)"""

    def __init__(self, db: AsyncIOMotorDatabase):
        self.collection = db.case_contributors

    async def create(
        self, case_id: str, contributor_data: ContributorCreate, user_id: str, user_name: str
    ) -> tuple[CaseContributor, str]:
        """
        Create a new contributor invitation.
        Returns (contributor, raw_token) - raw_token is for the magic link.
        """
        contributor_id = str(uuid.uuid4())
        now = datetime.utcnow()

        # Generate secure token
        raw_token = secrets.token_urlsafe(32)
        token_hash = hash_token(raw_token)

        expires_at = now + timedelta(days=contributor_data.token_expiration_days)

        contributor_dict = {
            "id": contributor_id,
            "case_id": case_id,
            "name": contributor_data.name,
            "email": contributor_data.email,
            "department": contributor_data.department,
            "status": ContributorStatus.INVITED.value,
            "upload_token": token_hash,
            "token_expires_at": expires_at,
            "documents_uploaded": 0,
            "last_upload_at": None,
            "invited_by": user_id,
            "invited_by_name": user_name,
            "created_at": now,
            "first_access_at": None,
            "completed_at": None,
            "notes": contributor_data.notes,
        }

        await self.collection.insert_one(contributor_dict)
        return CaseContributor(**contributor_dict), raw_token

    async def get_by_case(self, case_id: str) -> list[CaseContributor]:
        """Get all contributors for a case"""
        cursor = self.collection.find({"case_id": case_id}).sort("created_at", -1)
        contributors = []
        async for doc in cursor:
            doc.pop("_id", None)
            contributors.append(CaseContributor(**doc))
        return contributors

    async def get_by_id(self, contributor_id: str) -> CaseContributor | None:
        """Get a specific contributor"""
        doc = await self.collection.find_one({"id": contributor_id})
        if doc:
            doc.pop("_id", None)
            return CaseContributor(**doc)
        return None

    async def verify_token(self, contributor_id: str, raw_token: str) -> CaseContributor | None:
        """Verify a contributor's upload token"""
        contributor = await self.get_by_id(contributor_id)
        if not contributor:
            return None

        # Check expiration
        if datetime.utcnow() > contributor.token_expires_at:
            await self.collection.update_one(
                {"id": contributor_id}, {"$set": {"status": ContributorStatus.EXPIRED.value}}
            )
            return None

        # Verify token
        if not verify_token(raw_token, contributor.upload_token):
            return None

        # Update first access if needed
        if not contributor.first_access_at:
            await self.collection.update_one(
                {"id": contributor_id},
                {
                    "$set": {
                        "first_access_at": datetime.utcnow(),
                        "status": ContributorStatus.ACTIVE.value,
                    }
                },
            )

        return await self.get_by_id(contributor_id)

    async def record_upload(self, contributor_id: str) -> CaseContributor | None:
        """Record that a contributor uploaded a document"""
        await self.collection.update_one(
            {"id": contributor_id},
            {"$inc": {"documents_uploaded": 1}, "$set": {"last_upload_at": datetime.utcnow()}},
        )
        return await self.get_by_id(contributor_id)

    async def update(
        self, contributor_id: str, update_data: ContributorUpdate
    ) -> CaseContributor | None:
        """Update contributor details"""
        update_dict = {k: v for k, v in update_data.model_dump().items() if v is not None}
        if not update_dict:
            return await self.get_by_id(contributor_id)

        # Handle status enum
        if "status" in update_dict:
            update_dict["status"] = update_dict["status"].value
            if update_dict["status"] == ContributorStatus.COMPLETED.value:
                update_dict["completed_at"] = datetime.utcnow()

        await self.collection.update_one({"id": contributor_id}, {"$set": update_dict})
        return await self.get_by_id(contributor_id)

    async def delete(self, contributor_id: str) -> bool:
        """Delete a contributor invitation"""
        result = await self.collection.delete_one({"id": contributor_id})
        return result.deleted_count > 0

    async def bulk_create(
        self, case_id: str, contributors_data: list[ContributorCreate], user_id: str, user_name: str
    ) -> list[tuple[CaseContributor, str]]:
        """
        Bulk create contributor invitations.
        Returns list of (contributor, raw_token) tuples.
        """
        results = []
        for contributor_data in contributors_data:
            contributor, raw_token = await self.create(
                case_id=case_id,
                contributor_data=contributor_data,
                user_id=user_id,
                user_name=user_name,
            )
            results.append((contributor, raw_token))
        return results

    async def confirm_records_complete(self, contributor_id: str) -> CaseContributor | None:
        """Contributor confirms they have submitted all records"""
        now = datetime.utcnow()
        await self.collection.update_one(
            {"id": contributor_id},
            {
                "$set": {
                    "records_confirmed": True,
                    "records_confirmed_at": now,
                    "status": ContributorStatus.COMPLETED.value,
                    "completed_at": now,
                }
            },
        )
        return await self.get_by_id(contributor_id)

    async def update_last_access(self, contributor_id: str) -> None:
        """Update the last access timestamp"""
        await self.collection.update_one(
            {"id": contributor_id}, {"$set": {"last_access_at": datetime.utcnow()}}
        )


class RemindersRepository:
    """Repository for case reminders"""

    def __init__(self, db: AsyncIOMotorDatabase):
        self.collection = db.case_reminders

    async def create(
        self, case_id: str, reminder_data: ReminderCreate, user_id: str | None = None
    ) -> CaseReminder:
        """Create a new reminder"""
        reminder_id = str(uuid.uuid4())
        now = datetime.utcnow()

        reminder_dict = {
            "id": reminder_id,
            "case_id": case_id,
            "reminder_type": reminder_data.reminder_type.value,
            "trigger_date": reminder_data.trigger_date,
            "recipient_ids": reminder_data.recipient_ids,
            "message": reminder_data.message,
            "status": ReminderStatus.PENDING.value,
            "sent_at": None,
            "sent_via": [],
            "created_at": now,
            "created_by": user_id or "system",
            "dismissed_by": None,
            "dismissed_at": None,
        }

        await self.collection.insert_one(reminder_dict)
        return CaseReminder(**reminder_dict)

    async def get_by_case(self, case_id: str, include_sent: bool = False) -> list[CaseReminder]:
        """Get reminders for a case"""
        query = {"case_id": case_id}
        if not include_sent:
            query["status"] = {"$in": [ReminderStatus.PENDING.value]}

        cursor = self.collection.find(query).sort("trigger_date", 1)
        reminders = []
        async for doc in cursor:
            doc.pop("_id", None)
            reminders.append(CaseReminder(**doc))
        return reminders

    async def get_pending_reminders(
        self, before_date: datetime | None = None
    ) -> list[CaseReminder]:
        """Get all pending reminders that should be sent"""
        query = {"status": ReminderStatus.PENDING.value}
        if before_date:
            query["trigger_date"] = {"$lte": before_date}
        else:
            query["trigger_date"] = {"$lte": datetime.utcnow()}

        cursor = self.collection.find(query).sort("trigger_date", 1)
        reminders = []
        async for doc in cursor:
            doc.pop("_id", None)
            reminders.append(CaseReminder(**doc))
        return reminders

    async def mark_sent(self, reminder_id: str, sent_via: list[str]) -> CaseReminder | None:
        """Mark a reminder as sent"""
        await self.collection.update_one(
            {"id": reminder_id},
            {
                "$set": {
                    "status": ReminderStatus.SENT.value,
                    "sent_at": datetime.utcnow(),
                    "sent_via": sent_via,
                }
            },
        )
        doc = await self.collection.find_one({"id": reminder_id})
        if doc:
            doc.pop("_id", None)
            return CaseReminder(**doc)
        return None

    async def dismiss(self, reminder_id: str, user_id: str) -> CaseReminder | None:
        """Dismiss a reminder"""
        await self.collection.update_one(
            {"id": reminder_id},
            {
                "$set": {
                    "status": ReminderStatus.DISMISSED.value,
                    "dismissed_by": user_id,
                    "dismissed_at": datetime.utcnow(),
                }
            },
        )
        doc = await self.collection.find_one({"id": reminder_id})
        if doc:
            doc.pop("_id", None)
            return CaseReminder(**doc)
        return None

    async def delete(self, reminder_id: str) -> bool:
        """Delete a reminder"""
        result = await self.collection.delete_one({"id": reminder_id})
        return result.deleted_count > 0


class QueueRepository:
    """Repository for priority queue operations"""

    def __init__(self, db: AsyncIOMotorDatabase):
        self.cases = db.cases
        self.documents = db.documents

    async def get_prioritized_queue(self, filters: QueueFilter) -> list[CasePriorityScore]:
        """Get cases ordered by priority score"""
        now = datetime.utcnow()

        # Build query
        query = {}
        if not filters.include_closed:
            query["status"] = {"$ne": "closed"}
        if filters.analyst_id:
            query["$or"] = [
                {"assigned_user_ids": filters.analyst_id},
                {"assignee": filters.analyst_id},
            ]
        if filters.workflow_stages:
            query["workflow_stage"] = {"$in": filters.workflow_stages}
        if filters.clock_status:
            query["clock_status"] = filters.clock_status

        # Get cases
        cursor = self.cases.find(query).skip(filters.offset).limit(filters.limit)

        results = []
        async for case in cursor:
            # Calculate priority score
            score = await self._calculate_priority_score(case, now)
            results.append(score)

        # Sort by priority score (descending - higher is more urgent)
        results.sort(key=lambda x: (x.priority_override or 0, x.priority_score), reverse=True)

        return results

    async def _calculate_priority_score(self, case: dict, now: datetime) -> CasePriorityScore:
        """Calculate priority score for a case"""
        score = 0.0

        # Due date factor (most important)
        due_date = case.get("adjusted_due_date") or case.get("due_date")
        days_until_due = None
        if due_date:
            if isinstance(due_date, str):
                due_date = _parse_iso_naive(due_date)
            days_until_due = (due_date - now).days

            # Overdue cases get highest priority
            if days_until_due < 0:
                score += 1000 + abs(days_until_due) * 10
            elif days_until_due <= 3:
                score += 500 + (3 - days_until_due) * 50
            elif days_until_due <= 7:
                score += 200 + (7 - days_until_due) * 20
            elif days_until_due <= 14:
                score += 100 + (14 - days_until_due) * 5
            else:
                score += max(0, 100 - days_until_due)

        # Case age factor (older cases get slight boost)
        received_date = case.get("received_date")
        case_age_days = 0
        if received_date:
            if isinstance(received_date, str):
                received_date = _parse_iso_naive(received_date)
            case_age_days = (now - received_date).days
            score += min(case_age_days * 0.5, 50)  # Cap at 50 points

        # Document count factor (larger cases flagged for early start)
        doc_count = len(case.get("document_ids", []))
        if doc_count > 50:
            score += 30
        elif doc_count > 20:
            score += 15
        elif doc_count > 10:
            score += 5

        return CasePriorityScore(
            case_id=case["id"],
            tracking_number=case.get("tracking_number", ""),
            title=case.get("title", ""),
            due_date=due_date,
            days_until_due=days_until_due,
            case_age_days=case_age_days,
            document_count=doc_count,
            priority_score=score,
            priority_override=case.get("priority_override"),
            status=case.get("status", "new"),
            workflow_stage=case.get("workflow_stage"),
            clock_status=case.get("clock_status", "running"),
            analyst_ids=case.get("assigned_user_ids", []),
        )

    async def set_priority_override(self, case_id: str, override: int | None) -> bool:
        """Set manual priority override for a case"""
        result = await self.cases.update_one(
            {"id": case_id},
            {"$set": {"priority_override": override, "updated_at": datetime.utcnow()}},
        )
        return result.modified_count > 0


class TransfersRepository:
    """Repository for case transfers to other public bodies"""

    def __init__(self, db: AsyncIOMotorDatabase):
        self.collection = db.case_transfers
        self.cases = db.cases

    async def create(
        self,
        case_id: str,
        tracking_number: str,
        transfer_data: TransferCreate,
        user_id: str,
        user_name: str,
        token_expiration_days: int = 30,
    ) -> tuple[CaseTransfer, str]:
        """
        Create a new case transfer.
        Returns (transfer, raw_token) - raw_token is for the secure link.
        """
        transfer_id = str(uuid.uuid4())
        now = datetime.utcnow()

        # Generate secure token
        raw_token = secrets.token_urlsafe(32)
        token_hash = hash_token(raw_token)

        expires_at = now + timedelta(days=token_expiration_days)

        transfer_dict = {
            "id": transfer_id,
            "case_id": case_id,
            "tracking_number": tracking_number,
            "recipient_organization": transfer_data.recipient_organization,
            "recipient_email": transfer_data.recipient_email,
            "recipient_name": transfer_data.recipient_name,
            "include_documents": transfer_data.include_documents,
            "included_document_ids": transfer_data.included_document_ids or [],
            "transfer_reason": transfer_data.transfer_reason,
            "notes": transfer_data.notes,
            "access_token": token_hash,
            "token_expires_at": expires_at,
            "status": "pending",
            "transferred_by": user_id,
            "transferred_by_name": user_name,
            "transferred_at": now,
            "accessed_at": None,
            "downloaded_at": None,
        }

        await self.collection.insert_one(transfer_dict)
        return CaseTransfer(**transfer_dict), raw_token

    async def get_by_id(self, transfer_id: str) -> CaseTransfer | None:
        """Get a specific transfer"""
        doc = await self.collection.find_one({"id": transfer_id})
        if doc:
            doc.pop("_id", None)
            return CaseTransfer(**doc)
        return None

    async def get_by_case(self, case_id: str) -> list[CaseTransfer]:
        """Get all transfers for a case"""
        cursor = self.collection.find({"case_id": case_id}).sort("transferred_at", -1)
        transfers = []
        async for doc in cursor:
            doc.pop("_id", None)
            transfers.append(CaseTransfer(**doc))
        return transfers

    async def verify_token(self, transfer_id: str, raw_token: str) -> CaseTransfer | None:
        """Verify a transfer's access token"""
        transfer = await self.get_by_id(transfer_id)
        if not transfer:
            return None

        # Check expiration
        if datetime.utcnow() > transfer.token_expires_at:
            await self.collection.update_one({"id": transfer_id}, {"$set": {"status": "expired"}})
            return None

        # Verify token
        if not verify_token(raw_token, transfer.access_token):
            return None

        # Update accessed_at if first access
        if not transfer.accessed_at:
            await self.collection.update_one(
                {"id": transfer_id},
                {"$set": {"accessed_at": datetime.utcnow(), "status": "accessed"}},
            )

        return await self.get_by_id(transfer_id)

    async def mark_downloaded(self, transfer_id: str) -> CaseTransfer | None:
        """Mark a transfer as downloaded"""
        await self.collection.update_one(
            {"id": transfer_id},
            {"$set": {"downloaded_at": datetime.utcnow(), "status": "downloaded"}},
        )
        return await self.get_by_id(transfer_id)
