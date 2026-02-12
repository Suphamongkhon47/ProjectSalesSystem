"""
"""

from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count, Avg, F, ExpressionWrapper, DecimalField
from django.utils import timezone
from datetime import datetime, time, timedelta
from decimal import Decimal

from products.models import Transaction, TransactionItem, Product, Payment


@login_required
def dashboard(request):
    """
    Dashboard - Clean & Secure Logic
    """
    # ===== 1. Setup Dates =====
    actual_today = timezone.localdate()
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    
    # Default: วันนี้
    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        except ValueError:
            start_date = actual_today
    else:
        start_date = actual_today
    
    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except ValueError:
            end_date = actual_today
    else:
        end_date = actual_today
    
    if end_date < start_date: end_date = start_date

    # Helper Dates
    date_7_days_ago = actual_today - timedelta(days=6)
    date_30_days_ago = actual_today - timedelta(days=29)
    first_day_of_month = actual_today.replace(day=1)
    date_diff_days = (end_date - start_date).days + 1

    # Query Range
    query_min = timezone.make_aware(datetime.combine(start_date, time.min))
    query_max = timezone.make_aware(datetime.combine(end_date, time.max))
    
    user = request.user
    is_owner = user.is_superuser
    
    # ===== 2. Base QuerySets (กรอง Role ที่นี่ทีเดียว) =====
    # บิลขาย
    sale_qs = Transaction.objects.filter(
        transaction_date__range=(query_min, query_max),
        doc_type='SALE',
        status='POSTED'
    )
    # บิลคืน
    return_qs = Transaction.objects.filter(transaction_date__range=(query_min, query_max),doc_type='RETURN',status='POSTED')
    
    # 🔒 STAFF: เห็นแค่ของตัวเอง
    if not is_owner:
        sale_qs = sale_qs.filter(created_by=user)
        return_qs = return_qs.filter(created_by=user)

    # ===== 3. Calculate Stats (ตัวเลขหลัก) =====
    total_sales = sale_qs.aggregate(t=Sum('grand_total'))['t'] or Decimal('0')
    total_returns = abs(return_qs.aggregate(t=Sum('grand_total'))['t'] or Decimal('0'))
    
    net_sales = total_sales - total_returns # ยอดขายสุทธิ
    total_bills = sale_qs.count() # จำนวนบิล
    avg_bill = 0
    if total_bills > 0:
        avg_bill = net_sales / total_bills
    # จำนวนชิ้น (Items)
    sale_items_qs = TransactionItem.objects.filter(transaction__in=sale_qs)
    return_items_qs = TransactionItem.objects.filter(transaction__in=return_qs)
    
    sold_qty = sale_items_qs.aggregate(q=Sum('quantity'))['q'] or 0
    returned_qty = return_items_qs.aggregate(q=Sum('quantity'))['q'] or 0
    net_items_count = sold_qty - returned_qty

    # ===== 4. Profit & Margin (เฉพาะ Owner) =====
    net_profit = Decimal('0')
    net_profit_margin = 0

    if is_owner:
        # กำไรจากบิลขาย
        profit_sales = sale_items_qs.aggregate(
            p=Sum(
                ExpressionWrapper(
                    (F('unit_price') - F('cost_price')) * F('quantity'),
                    output_field=DecimalField(max_digits=12, decimal_places=2)
                )
            )
        )['p'] or Decimal('0')
        
        # กำไร(ขาดทุน)จากรับคืน
        profit_returns = return_items_qs.aggregate(
            p=Sum(ExpressionWrapper((F('unit_price') - F('cost_price')) * F('quantity'),output_field=DecimalField(max_digits=12, decimal_places=2))))['p'] or Decimal('0')

        net_profit = profit_sales - profit_returns
        
        # % Margin
        if net_sales > 0:
            net_profit_margin = float(net_profit / net_sales * 100)

    # ===== 5. Trend & Comparison (เทียบช่วงก่อนหน้า) =====
    prev_start = start_date - timedelta(days=date_diff_days)
    prev_end = start_date - timedelta(days=1)
    prev_min = timezone.make_aware(datetime.combine(prev_start, time.min))
    prev_max = timezone.make_aware(datetime.combine(prev_end, time.max))
    
    prev_sales_qs = Transaction.objects.filter(transaction_date__range=(prev_min, prev_max), doc_type='SALE', status='POSTED')
    prev_returns_qs = Transaction.objects.filter(transaction_date__range=(prev_min, prev_max), doc_type='RETURN', status='POSTED')
    
    if not is_owner:
        prev_sales_qs = prev_sales_qs.filter(created_by=user)
        prev_returns_qs = prev_returns_qs.filter(created_by=user)
        
    prev_total = prev_sales_qs.aggregate(t=Sum('grand_total'))['t'] or Decimal('0')
    prev_return = abs(prev_returns_qs.aggregate(t=Sum('grand_total'))['t'] or Decimal('0'))
    prev_net_sales = prev_total - prev_return
    
    # คำนวณ % เปลี่ยนแปลง
    current_val = net_sales
    prev_val = prev_net_sales
    
    if prev_val > 0:
        change_percent = float((current_val - prev_val) / prev_val * 100)
    else:
        change_percent = 100.0 if current_val > 0 else 0.0

    # ===== 6. Chart Data (7 Days) - แสดง 7 วันเสมอ =====
    last_7_days = []
    for i in range(6, -1, -1):
        day = actual_today - timedelta(days=i)  # ใช้ actual_today แทน end_date
        d_start = timezone.make_aware(datetime.combine(day, time.min))
        d_end = timezone.make_aware(datetime.combine(day, time.max))
        
        d_qs = Transaction.objects.filter(transaction_date__range=(d_start, d_end), doc_type='SALE', status='POSTED')
        d_ret_qs = Transaction.objects.filter(transaction_date__range=(d_start, d_end), doc_type='RETURN', status='POSTED')
        
        if not is_owner:
            d_qs = d_qs.filter(created_by=user)
            d_ret_qs = d_ret_qs.filter(created_by=user)
            
        d_sales = d_qs.aggregate(v=Sum('grand_total'))['v'] or 0
        d_ret = abs(d_ret_qs.aggregate(v=Sum('grand_total'))['v'] or 0)
        
        # Staff เห็นจำนวนบิล, Admin เห็นยอดเงิน
        val = d_qs.count() if not is_owner else float(d_sales - d_ret)
        
        last_7_days.append({
            'day_name': day.strftime('%a'), # Mon, Tue
            'total': val
        })

    # ===== 7. Top Products & Payments =====
    top_products_today = sale_items_qs.values('product__name', 'product__sku').annotate(
        total_qty=Sum('quantity'),
        total_amount=Sum('line_total'),
    ).order_by('-total_qty')[:5]

    recent_payments_qs = Payment.objects.filter(
        transaction__status='POSTED',
        transaction__transaction_date__range=(query_min, query_max)
    ).select_related('transaction__created_by').order_by('-created_at')
    
    if not is_owner:
        recent_payments_qs = recent_payments_qs.filter(transaction__created_by=user)
    
    recent_payments = recent_payments_qs[:10]

    # ===== 8. Inventory (เฉพาะ Owner) =====
    low_stock_products = []
    low_stock_count = 0
    out_of_stock_count = 0
    inventory_value = 0
    
    if is_owner:
        products = Product.objects.filter(is_active=True)
        out_of_stock_count = products.filter(quantity=0).count()
        low_stock_qs = products.filter(quantity__lte=10, quantity__gt=0)
        low_stock_count = low_stock_qs.count()
        low_stock_products = low_stock_qs.order_by('quantity')[:5]
        
        inventory_value = products.aggregate(
            val=Sum(F('quantity') * F('cost_price'))
        )['val'] or 0

    context = {
        'is_owner': is_owner,
        'actual_today': actual_today,
        'start_date': start_date,
        'end_date': end_date,
        'date_diff_days': date_diff_days,
        
        # Quick Dates
        'date_7_days_ago': date_7_days_ago,
        'date_30_days_ago': date_30_days_ago,
        'first_day_of_month': first_day_of_month,
        
        # Stats
        'net_sales': net_sales,
        'total_bills': total_bills,
        'avg_bill': avg_bill,
        'net_items_count': net_items_count,
        'net_profit': net_profit,
        'net_profit_margin': net_profit_margin,
        'change_percent': change_percent,
        'is_increase': change_percent >= 0,
        
        # Lists
        'last_7_days': last_7_days,
        'top_products': top_products_today,
        'recent_payments': recent_payments,
        
        # Inventory
        'low_stock_products': low_stock_products,
        'low_stock_count': low_stock_count,
        'out_of_stock_count': out_of_stock_count,
        'inventory_value': inventory_value,
    }
    
    return render(request, 'products/dashboards/dashboard.html', context)