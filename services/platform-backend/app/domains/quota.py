from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError
from app.models import QuotaAccount, QuotaLedger, ResourceLimit


async def provision_quota(
    session: AsyncSession, *, user_id: str, initial_balance: int
) -> tuple[QuotaAccount, ResourceLimit]:
    account = QuotaAccount(owner_id=user_id, balance=initial_balance)
    limits = ResourceLimit(owner_id=user_id)
    session.add_all([account, limits])
    await session.flush()
    if initial_balance:
        session.add(
            QuotaLedger(
                account_id=account.id,
                direction="credit",
                amount=initial_balance,
                reason="开户赠送",
                business_type="account_opening",
                business_id=user_id,
                balance_after=initial_balance,
            )
        )
    return account, limits


async def get_quota_account(session: AsyncSession, user_id: str) -> QuotaAccount:
    account = await session.scalar(
        select(QuotaAccount).where(QuotaAccount.owner_id == user_id).with_for_update()
    )
    if not account:
        raise ApiError(500, "QUOTA_ACCOUNT_MISSING", "额度账户不存在。")
    return account


async def apply_quota_change(
    session: AsyncSession,
    *,
    user_id: str,
    direction: str,
    amount: int,
    reason: str,
    business_type: str,
    business_id: str,
) -> QuotaAccount:
    if amount <= 0 or direction not in {"credit", "debit"}:
        raise ApiError(422, "INVALID_QUOTA_CHANGE", "额度变更参数无效。")
    account = await get_quota_account(session, user_id)
    existing = await session.scalar(
        select(QuotaLedger).where(
            QuotaLedger.account_id == account.id,
            QuotaLedger.business_type == business_type,
            QuotaLedger.business_id == business_id,
            QuotaLedger.direction == direction,
        )
    )
    if existing:
        return account
    next_balance = account.balance + amount if direction == "credit" else account.balance - amount
    if next_balance < 0:
        raise ApiError(
            402,
            "QUOTA_INSUFFICIENT",
            "积分余额不足。",
            details={"balance": account.balance, "required": amount},
        )
    account.balance = next_balance
    account.version += 1
    session.add(
        QuotaLedger(
            account_id=account.id,
            direction=direction,
            amount=amount,
            reason=reason,
            business_type=business_type,
            business_id=business_id,
            balance_after=next_balance,
        )
    )
    return account
