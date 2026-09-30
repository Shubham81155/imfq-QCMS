"""
Centralized Financial Metrics Engine (Single Source of Truth)
Unified Financial Ledger & Analytics Engine for QCMS Enterprise OS.
"""

from datetime import datetime, timedelta, timezone
from sqlalchemy import func, or_
from app.infrastructure.database.models.models import (
    db, Organization, Subscription, SubscriptionPayment, SubscriptionInvoice, SubscriptionRefund, SaaSPlan, SaaSPlanPricing
)

class FinancialMetricsEngine:
    @staticmethod
    def extract_invoice_amount(inv):
        if not inv:
            return 0.0
        tot = float(inv.total_amount or 0.0)
        if tot > 0:
            return tot
        base = float(inv.base_amount or 0.0)
        gst = float(inv.gst_amount or 0.0)
        disc = float(inv.discount_amount or 0.0)
        calc_tot = base + gst - disc
        if calc_tot > 0:
            return calc_tot
        if base > 0:
            return base
        if getattr(inv, 'usage_breakdown', None) and isinstance(inv.usage_breakdown, dict):
            brk_tot = float(inv.usage_breakdown.get('total_amount') or inv.usage_breakdown.get('subtotal_amount') or 0.0)
            if brk_tot > 0:
                return brk_tot
        if getattr(inv, 'payment', None):
            pay_tot = float(inv.payment.final_amount or inv.payment.amount or 0.0)
            if pay_tot > 0:
                return pay_tot
        if getattr(inv, 'payment_id', None):
            pmt = db.session.get(SubscriptionPayment, inv.payment_id)
            if pmt:
                pay_tot = float(pmt.final_amount or pmt.amount or 0.0)
                if pay_tot > 0:
                    return pay_tot
        return 0.0

    @classmethod
    def get_consolidated_kpis(cls, org_id=None, date_range=None, start_date=None, end_date=None, date_range_name=None):
        """
        Calculates unified, non-redundant, cross-module financial KPIs.
        
        Single Source of Truth Rules:
        - Real-time deduplicated transaction ledger from all paid invoices and completed payments.
        - total_revenue: Cumulative gross revenue or scoped period revenue without synthetic multipliers.
        - all_time_revenue: Cumulative all-time revenue across all paid subscriptions.
        - mrr: Contractual MRR from active subscriptions plus active monthly PAYG metered usage.
        - arr: mrr * 12.
        - trends: Dynamically bucketed real revenue series matching the requested date range.
        - monthly_trends: True calendar month-by-month historical trends (past 6 calendar months).
        """
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if not end_date:
            end_date = now
        if not start_date:
            start_date = now - timedelta(days=30)
            
        month_start = datetime(now.year, now.month, 1)

        # Exclude platform organizations
        platform_org_ids = [
            r[0] for r in db.session.query(Organization.id).filter(Organization.is_platform_org == True).all()
        ]

        def _apply_org_filter(q, model):
            if org_id:
                q = q.filter(getattr(model, 'org_id') == org_id)
            if platform_org_ids:
                q = q.filter(~getattr(model, 'org_id').in_(platform_org_ids))
            return q

        # ── 1. Unified Real-Time Transaction Ledger ─────────────────────────
        # Case-insensitive query for all legitimately paid invoices and payments
        valid_inv_statuses = ['paid', 'completed', 'settled', 'success']
        valid_pay_statuses = ['completed', 'paid', 'success', 'captured', 'approved', 'verified', 'settled']

        inv_query = db.session.query(SubscriptionInvoice).filter(
            func.lower(func.trim(SubscriptionInvoice.invoice_status)).in_(valid_inv_statuses)
        )
        if org_id:
            inv_query = inv_query.filter(SubscriptionInvoice.org_id == org_id)
        if platform_org_ids:
            inv_query = inv_query.filter(~SubscriptionInvoice.org_id.in_(platform_org_ids))
        all_paid_invoices = inv_query.all()

        pay_query = db.session.query(SubscriptionPayment).filter(
            func.lower(func.trim(SubscriptionPayment.payment_status)).in_(valid_pay_statuses)
        )
        if org_id:
            pay_query = pay_query.filter(SubscriptionPayment.org_id == org_id)
        if platform_org_ids:
            pay_query = pay_query.filter(~SubscriptionPayment.org_id.in_(platform_org_ids))
        all_paid_payments = pay_query.all()

        transactions = []
        accounted_payment_ids = set()

        for inv in all_paid_invoices:
            inv_amt = cls.extract_invoice_amount(inv)
            inv_dt = inv.invoice_date or inv.created_at or now

            # Linked payment deduplication
            linked_pmt = None
            if inv.payment_id:
                linked_pmt = next((p for p in all_paid_payments if p.id == inv.payment_id), None)
            if not linked_pmt:
                linked_pmt = next((p for p in all_paid_payments if getattr(p, 'invoice_id', None) == inv.id), None)

            if linked_pmt:
                accounted_payment_ids.add(linked_pmt.id)
                p_amt = float(linked_pmt.final_amount or linked_pmt.amount or 0.0)
                chosen_amt = max(inv_amt, p_amt)
                chosen_dt = linked_pmt.created_at or inv_dt
            else:
                chosen_amt = inv_amt
                chosen_dt = inv_dt

            if chosen_amt > 0:
                transactions.append({
                    "date": chosen_dt,
                    "amount": round(chosen_amt, 2),
                    "org_id": inv.org_id,
                    "type": "invoice",
                    "id": inv.id
                })

        for p in all_paid_payments:
            if p.id not in accounted_payment_ids:
                p_amt = float(p.final_amount or p.amount or 0.0)
                if p_amt > 0:
                    transactions.append({
                        "date": p.created_at or now,
                        "amount": round(p_amt, 2),
                        "org_id": p.org_id,
                        "type": "payment",
                        "id": p.id
                    })

        refund_sum = 0.0
        try:
            ref_q = db.session.query(func.sum(SubscriptionRefund.amount)).filter(
                SubscriptionRefund.created_at >= start_date,
                SubscriptionRefund.created_at <= end_date
            )
            if org_id:
                ref_q = ref_q.filter(SubscriptionRefund.org_id == org_id)
            refund_sum = float(ref_q.scalar() or 0.0)
        except Exception:
            refund_sum = 0.0

        all_time_revenue = max(0.0, round(sum(t["amount"] for t in transactions), 2))

        period_transactions = [
            t for t in transactions if start_date <= t["date"] <= end_date
        ]
        period_revenue = max(0.0, round(sum(t["amount"] for t in period_transactions) - refund_sum, 2))

        # Default total_revenue representation:
        # If All Time, or default overview load where all-time cumulative gross revenue is represented, use all_time_revenue
        if date_range_name in ('All', 'All Time', 'ALL', 'all_time', 'all') or (date_range_name in ('Last 30 Days', None, '') and all_time_revenue > 0 and period_revenue < all_time_revenue):
            total_revenue = all_time_revenue
        else:
            total_revenue = period_revenue

        # 2. Monthly Cash Collected (Strictly Completed Paid Revenue in Current Calendar Month)
        month_transactions = [
            t for t in transactions if t["date"] >= month_start
        ]
        monthly_cash_collected = max(0.0, round(sum(t["amount"] for t in month_transactions), 2))

        # 3. Taxes Collected (GST/Tax sum in period)
        taxes_collected = 0.0
        for inv in all_paid_invoices:
            inv_dt = inv.invoice_date or inv.created_at or now
            if start_date <= inv_dt <= end_date:
                taxes_collected += float(inv.gst_amount or 0.0)
        for p in all_paid_payments:
            p_dt = p.created_at or now
            if start_date <= p_dt <= end_date:
                taxes_collected += float(p.gst_amount or 0.0)
        taxes_collected = round(taxes_collected, 2)

        # 4. Invoices Metrics
        inv_base = SubscriptionInvoice.query
        if org_id:
            inv_base = inv_base.filter_by(org_id=org_id)
        if platform_org_ids:
            inv_base = inv_base.filter(~SubscriptionInvoice.org_id.in_(platform_org_ids))

        paid_invoices_count = inv_base.filter(
            SubscriptionInvoice.invoice_status.in_(['Paid', 'PAID', 'Completed'])
        ).count()

        unpaid_invoices_q = inv_base.filter(
            SubscriptionInvoice.invoice_status.in_(['Sent', 'SENT', 'Overdue', 'OVERDUE', 'Issued'])
        )
        unpaid_invoices_count = unpaid_invoices_q.count()

        out_q = db.session.query(func.sum(SubscriptionInvoice.total_amount)).filter(
            SubscriptionInvoice.invoice_status.in_(['Sent', 'SENT', 'Overdue', 'OVERDUE', 'Issued'])
        )
        if org_id:
            out_q = out_q.filter(SubscriptionInvoice.org_id == org_id)
        if platform_org_ids:
            out_q = out_q.filter(~SubscriptionInvoice.org_id.in_(platform_org_ids))
        outstanding_due = round(float(out_q.scalar() or 0.0), 2)

        total_issued = paid_invoices_count + unpaid_invoices_count
        collection_rate = round((paid_invoices_count / float(total_issued)) * 100.0, 1) if total_issued > 0 else 100.0

        # 5. MRR & ARR Calculations (Strictly Active Paying Subscriptions)
        sub_q = Subscription.query.filter(
            Subscription.subscription_status.in_(['Active', 'ACTIVE'])
        )
        if org_id:
            sub_q = sub_q.filter_by(org_id=org_id)
        if platform_org_ids:
            sub_q = sub_q.filter(~Subscription.org_id.in_(platform_org_ids))

        mrr_val = 0.0
        upgrade_revenue = 0.0
        renewal_revenue = 0.0

        from app.domain.services.payg_billing_service import PaygBillingService

        for s in sub_q.all():
            bcycle = (s.billing_cycle or 'Monthly').lower()
            months = 12 if ('year' in bcycle or 'annual' in bcycle) else (3 if 'quarter' in bcycle else 1)

            is_payg = (
                'pay_as_you_go' in (s.pricing_model or '').lower() or
                'metered' in (s.pricing_model or '').lower() or
                'pay-as-you-go' in (s.plan_name or '').lower() or
                'pay_as_you_go' in (s.plan_name or '').lower() or
                'metered' in (s.plan_name or '').lower()
            )
            if is_payg:
                latest_paid_inv = SubscriptionInvoice.query.filter(
                    SubscriptionInvoice.org_id == s.org_id,
                    SubscriptionInvoice.invoice_status.in_(['Paid', 'PAID', 'Completed'])
                ).order_by(SubscriptionInvoice.created_at.desc()).first()

                if latest_paid_inv and float(latest_paid_inv.total_amount or 0.0) > 0:
                    payg_amt = float(latest_paid_inv.total_amount)
                else:
                    try:
                        brk = PaygBillingService.calculate_payg_bill_breakdown(s.org_id)
                        payg_amt = float(brk.get('total_amount', 0.0))
                    except Exception:
                        payg_amt = 0.0
                mrr_val += payg_amt
                renewal_revenue += payg_amt
            else:
                amt = float((s.final_amount if s.final_amount is not None else 0.0))
                # Prioritize SaaSPlan configured pricing if s.final_amount is 0.0
                if amt == 0.0 and s.plan_name and s.plan_name.strip().lower() not in ('trial', 'trialing', 'default trial plan', ''):
                    sp = SaaSPlan.query.filter(
                        or_(
                            func.lower(func.trim(SaaSPlan.name)) == s.plan_name.strip().lower(),
                            func.lower(func.trim(SaaSPlan.code)) == s.plan_name.strip().lower()
                        )
                    ).first()
                    if sp:
                        pricing = SaaSPlanPricing.query.filter_by(plan_id=sp.id, is_active=True).first()
                        if pricing and pricing.price:
                            amt = float(pricing.price)
                            cycle_name = (pricing.billing_cycle or bcycle).lower()
                            months = 12 if ('year' in cycle_name or 'annual' in cycle_name) else (3 if 'quarter' in cycle_name else 1)

                # Fallback to payments or invoices only if plan has no configured pricing
                if amt == 0.0 and s.plan_name and s.plan_name.strip().lower() not in ('trial', 'trialing', 'default trial plan', ''):
                    latest_pmt = SubscriptionPayment.query.filter(
                        SubscriptionPayment.org_id == s.org_id,
                        SubscriptionPayment.payment_status.in_(['Completed', 'Paid', 'SUCCESS'])
                    ).order_by(SubscriptionPayment.created_at.desc()).first()
                    latest_inv = SubscriptionInvoice.query.filter_by(org_id=s.org_id).order_by(SubscriptionInvoice.created_at.desc()).first()
                    if latest_pmt and (latest_pmt.final_amount or latest_pmt.amount):
                        amt = float(latest_pmt.final_amount or latest_pmt.amount)
                    elif latest_inv and latest_inv.total_amount:
                        amt = float(latest_inv.total_amount)

                bprice = float((s.base_price if s.base_price is not None else 0.0))
                if bprice == 0.0:
                    bprice = amt
                mrr_val += amt / months
                if amt > bprice and bprice > 0:
                    upgrade_revenue += (amt - bprice)
                renewal_revenue += amt

        # Also account for customer organizations with active paid plans that may not have a Subscription row yet
        customer_orgs = Organization.query.filter(
            Organization.is_deleted == False,
            Organization.is_platform_org == False
        )
        if org_id:
            customer_orgs = customer_orgs.filter_by(id=org_id)
        existing_sub_org_ids = set(s.org_id for s in sub_q.all() if s.org_id)
        
        for org_item in customer_orgs.all():
            if org_item.id not in existing_sub_org_ids and org_item.subscription_status in ('Active', 'ACTIVE'):
                p_name = (org_item.subscription_plan or '').strip()
                if p_name and p_name.lower() not in ('trial', 'trialing', 'default trial plan', ''):
                    sp = SaaSPlan.query.filter(
                        or_(
                            func.lower(func.trim(SaaSPlan.name)) == p_name.lower(),
                            func.lower(func.trim(SaaSPlan.code)) == p_name.lower()
                        )
                    ).first()
                    if sp:
                        pricing = SaaSPlanPricing.query.filter_by(plan_id=sp.id, is_active=True).first()
                        if pricing and pricing.price:
                            p_amt = float(pricing.price)
                            cycle_name = (pricing.billing_cycle or 'Monthly').lower()
                            months = 12 if ('year' in cycle_name or 'annual' in cycle_name) else (3 if 'quarter' in cycle_name else 1)
                            mrr_val += p_amt / months

        mrr = round(mrr_val, 2)
        arr = round(mrr * 12, 2)

        # 6. Dynamic Trends Construction based on Date Range
        bucket_data = {}
        delta_days = (end_date - start_date).total_seconds() / 86400.0

        # Case A: Intraday (Today, Yesterday, or <= 1.5 days)
        if delta_days <= 1.5:
            cur = start_date.replace(minute=0, second=0, microsecond=0)
            while cur <= end_date:
                lbl = cur.strftime('%I %p')
                bucket_data[lbl] = 0.0
                cur += timedelta(hours=3)
            
            for t in period_transactions:
                dt = t["date"]
                hour_slot = (dt.hour // 3) * 3
                slot_lbl = dt.replace(hour=hour_slot, minute=0, second=0).strftime('%I %p')
                if slot_lbl in bucket_data:
                    bucket_data[slot_lbl] += t["amount"]

        # Case B: Short / Medium range (2 to 45 days, e.g. Last 7 Days, Last 30 Days, This Month, Last Month)
        elif delta_days <= 45:
            cur = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
            target_end = end_date.replace(hour=23, minute=59, second=59)
            while cur <= target_end:
                lbl = cur.strftime('%d %b')
                bucket_data[lbl] = 0.0
                cur += timedelta(days=1)
            
            for t in period_transactions:
                lbl = t["date"].strftime('%d %b')
                if lbl in bucket_data:
                    bucket_data[lbl] += t["amount"]

        # Case C: Quarter / 90 Days (46 to 120 days)
        elif delta_days <= 120:
            cur = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
            while cur <= end_date:
                lbl = cur.strftime('%d %b')
                bucket_data[lbl] = 0.0
                cur += timedelta(days=7)
            
            for t in period_transactions:
                closest_lbl = None
                min_diff = 999999999
                for b_str in bucket_data.keys():
                    try:
                        b_dt = datetime.strptime(f"{b_str} {t['date'].year}", "%d %b %Y")
                        diff = abs((t["date"] - b_dt).total_seconds())
                        if diff < min_diff:
                            min_diff = diff
                            closest_lbl = b_str
                    except Exception:
                        pass
                if closest_lbl:
                    bucket_data[closest_lbl] += t["amount"]

        # Case D: Long Range (> 120 days, e.g. Year to Date, Last 12 Months, All)
        else:
            cur = start_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            while cur <= end_date:
                lbl = cur.strftime('%b %Y')
                bucket_data[lbl] = 0.0
                cur = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
            
            tx_to_plot = transactions if (date_range_name in ('All', 'All Time', 'ALL', 'all_time')) else period_transactions
            for t in tx_to_plot:
                lbl = t["date"].strftime('%b %Y')
                if lbl in bucket_data:
                    bucket_data[lbl] += t["amount"]

        trend_labels = list(bucket_data.keys())
        trend_values = [round(v, 2) for v in bucket_data.values()]

        # 6b. True Calendar Month-by-Month Historical Trends (Past 6 Calendar Months)
        # Dedicated for "Monthly Revenue Trends" charts - strictly real-time collected ledger amounts
        hist_months = []
        for i in range(5, -1, -1):
            m_dt = (now.replace(day=28) - timedelta(days=31 * i)).replace(day=1)
            hist_months.append(m_dt.strftime('%b %Y'))

        hist_rev = {m: 0.0 for m in hist_months}
        for t in transactions:
            m_str = t["date"].strftime('%b %Y')
            if m_str in hist_rev:
                hist_rev[m_str] += t["amount"]

        monthly_trend_labels = list(hist_rev.keys())
        monthly_trend_values = [round(v, 2) for v in hist_rev.values()]

        # 7. 3-Month Revenue Forecasting Engine
        # Projects expected total monthly revenue for the next 3 consecutive calendar months
        # based on active contracted MRR
        forecast_labels = []
        forecast_values = []

        for i in range(1, 4):
            nxt_month = (now.replace(day=28) + timedelta(days=31 * i)).replace(day=1)
            forecast_labels.append(nxt_month.strftime('%b %Y'))

        if mrr > 0:
            forecast_values = [round(mrr, 2), round(mrr, 2), round(mrr, 2)]
        else:
            forecast_values = [0.0, 0.0, 0.0]

        return {
            "total_revenue": total_revenue,
            "period_revenue": period_revenue,
            "all_time_revenue": all_time_revenue,
            "mrr": mrr,
            "arr": arr,
            "monthly_cash_collected": monthly_cash_collected,
            "outstanding_due": outstanding_due,
            "unpaid_invoices_count": unpaid_invoices_count,
            "paid_invoices_count": paid_invoices_count,
            "taxes_collected": taxes_collected,
            "collection_rate": collection_rate,
            "upgrades": round(upgrade_revenue, 2),
            "renewals": round(renewal_revenue, 2),
            "trends": {"labels": trend_labels, "values": trend_values},
            "monthly_trends": {"labels": monthly_trend_labels, "values": monthly_trend_values},
            "forecast": {"labels": forecast_labels, "values": forecast_values}
        }
