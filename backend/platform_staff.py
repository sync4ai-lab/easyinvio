"""Server-owned staff authorization; client roles and JWT metadata cannot grant it."""
async def platform_role(connection, settings, user_id):
    if user_id in set(getattr(settings, 'platform_admin_user_ids', [])):
        return 'SUPER_ADMIN'
    if not await connection.fetchval("SELECT to_regclass('public.platform_staff') IS NOT NULL"):
        return None
    if await connection.fetchval("SELECT EXISTS(SELECT 1 FROM public.platform_staff WHERE auth_user_id=$1 AND is_active AND role='AGENT')", user_id):
        return 'AGENT'
    return None


async def checkout_roles(connection, context, cart_id=None, amount=None):
    """A dispatcher may fund a validated label basket, never an arbitrary top-up."""
    from fastapi import HTTPException
    roles = {'OWNER','ADMIN','ACCOUNTANT'}
    if cart_id is None:
        return roles
    cart = await connection.fetchrow("""SELECT id,amount FROM public.payment_carts
        WHERE id=$1 AND tenant_id=$2 AND requested_by=$3
        AND status IN ('CREATING','AWAITING_PAYMENT') AND amount BETWEEN 1 AND 10000 FOR SHARE""",
        cart_id, context.tenant_id, context.user_id)
    if not cart or (amount is not None and cart['amount'] != amount):
        raise HTTPException(403, 'A matching, reviewed shipping basket is required')
    return roles | {'DISPATCHER'}
