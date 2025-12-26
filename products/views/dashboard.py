"""
Views: Reports (รายงาน)
"""

from django.forms import DecimalField
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count, Avg, F, ExpressionWrapper, DecimalField
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger    
from django.http import JsonResponse
from django.utils import timezone
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from products.models import Sale, SaleItem, Product, Payment


# ===================================
# 1. Dashboard (หน้าแรก)
# ===================================
    
@login_required
def dashboard(request):
    """Dashboard - แยกมุมมองตามสิทธิ์ (Owner vs Staff)"""
    
    # --- 1. จัดการเรื่องวันที่ (Date Logic) ---
    actual_today = timezone.localdate()  # วันนี้จริงๆ (เอาไว้เทียบ หรือปุ่ม "วันนี้")
    
    # รับค่าจาก URL (เช่น ?date=2023-12-25)
    date_str = request.GET.get('date')
    
    if date_str:
        try:
            report_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            report_date = actual_today
    else:
        report_date = actual_today
        
    # ปุ่มเลื่อนวัน (Prev/Next)
    prev_date = report_date - timedelta(days=1)
    next_date = report_date + timedelta(days=1)
    
    # สร้างช่วงเวลาเริ่ม-จบของ "report_date"
    query_min = timezone.make_aware(datetime.combine(report_date, time.min))
    query_max = timezone.make_aware(datetime.combine(report_date, time.max))
    
    user = request.user
    is_owner = user.is_superuser
    
    # ===================================
    # 2. เตรียม QuerySet (แยก ขาย vs คืน)
    # ===================================
    
    # 2.1 บิลขาย (SALE) ที่สำเร็จแล้ว
    sale_qs = Sale.objects.filter(
        sale_date__range=(query_min, query_max),
        doc_type='SALE',
        status='POSTED'
    )
    
    # 2.2 บิลรับคืน (RETURN) ที่สำเร็จแล้ว
    return_qs = Sale.objects.filter(
        sale_date__range=(query_min, query_max),
        doc_type='RETURN',
        status='POSTED'
    )
    
    # กรองตามสิทธิ์ (พนักงานเห็นแค่ของตัวเอง)
    if not is_owner:
        sale_qs = sale_qs.filter(created_by=user)
        return_qs = return_qs.filter(created_by=user)

    # ===================================
    # 3. คำนวณยอดเงิน (Financials)
    # ===================================
    
    # ยอดขายรวม (Gross Sales)
    total_sales = sale_qs.aggregate(total=Sum('grand_total'))['total'] or 0
    total_bills = sale_qs.count()
    
    # ยอดรับคืนรวม (Total Returns) - แปลงเป็นบวกเสมอเพื่อให้แสดงผลถูกต้อง
    total_returns = return_qs.aggregate(total=Sum('grand_total'))['total'] or 0
    total_returns = abs(total_returns)
    
    # ยอดขายสุทธิ (Net Sales) = ขาย - คืน
    net_sales = total_sales - total_returns
    
    # ===================================
    # 4. คำนวณจำนวนชิ้น (Items Count)
    # ===================================
    
    # ดึงรายการสินค้าทั้งหมดที่เกี่ยวข้อง
    sale_items_qs = SaleItem.objects.filter(sale__in=sale_qs)
    return_items_qs = SaleItem.objects.filter(sale__in=return_qs)

    sold_qty = sale_items_qs.aggregate(qty=Sum('quantity'))['qty'] or 0
    returned_qty = return_items_qs.aggregate(qty=Sum('quantity'))['qty'] or 0
    
    # จำนวนชิ้นสุทธิ (Net Items)
    net_items_count = sold_qty - returned_qty

    # ===================================
    # 5. คำนวณกำไร (Profit) - เฉพาะ Owner
    # ===================================
    net_profit = 0
    net_profit_margin = 0

    if is_owner:
        # กำไรจากบิลขาย
        profit_sales = sale_items_qs.aggregate(
            profit=Sum(
                ExpressionWrapper(
                    (F('unit_price') - F('cost_price')) * F('quantity'),
                    # ✅ แก้ไข: ใส่ max_digits และ decimal_places ให้ครบ เพื่อป้องกัน Error
                    output_field=DecimalField(max_digits=12, decimal_places=2)
                )
            )
        )['profit'] or 0

        # กำไรที่หายไปจากการคืน (ต้องหักออก)
        profit_returns = return_items_qs.aggregate(
            profit=Sum(
                ExpressionWrapper(
                    (F('unit_price') - F('cost_price')) * F('quantity'),
                    # ✅ แก้ไข: ใส่ max_digits และ decimal_places ให้ครบ
                    output_field=DecimalField(max_digits=12, decimal_places=2)
                )
            )
        )['profit'] or 0

        # กำไรสุทธิ
        net_profit = profit_sales - profit_returns
        
        # Margin (%)
        if net_sales > 0:
            net_profit_margin = (net_profit / net_sales * 100)
        else:
            net_profit_margin = 0

    # ===================================
    # 6. รายการอื่นๆ (Top 5, Recent, Stock)
    # ===================================
    
    # Top 5 สินค้าขายดี (คิดจากยอดขายสุทธิ - ง่ายๆ คือดูจาก SaleItem ของบิลขาย)
    top_products_today = sale_items_qs.values(
        'product__name', 'product__sku'
    ).annotate(
        total_qty=Sum('quantity'),
        total_amount=Sum('line_total'),
    ).order_by('-total_qty')[:5]

    # กราฟย้อนหลัง 7 วัน
    last_7_days = []
    for i in range(6, -1, -1):
        day = report_date - timedelta(days=i)
        
        day_start = timezone.make_aware(datetime.combine(day, time.min))
        day_end = timezone.make_aware(datetime.combine(day, time.max))
        
        # คำนวณยอดสุทธิรายวัน
        d_sales = Sale.objects.filter(sale_date__range=(day_start, day_end), doc_type='SALE', status='POSTED')
        d_returns = Sale.objects.filter(sale_date__range=(day_start, day_end), doc_type='RETURN', status='POSTED')
        
        if not is_owner:
            d_sales = d_sales.filter(created_by=user)
            d_returns = d_returns.filter(created_by=user)
            
        val_sales = d_sales.aggregate(v=Sum('grand_total'))['v'] or 0
        val_returns = abs(d_returns.aggregate(v=Sum('grand_total'))['v'] or 0)
        
        if is_owner:
            # เจ้าของดูยอดเงินสุทธิ
            total_val = val_sales - val_returns
        else:
            # พนักงานดูจำนวนบิลขาย (ไม่หักคืน) หรือจะดูจำนวนชิ้นก็ได้
            total_val = d_sales.count()

        last_7_days.append({
            'day_name': day.strftime('%a'),
            'total': float(total_val)
        })

    # เปรียบเทียบกับเมื่อวาน
    yesterday = report_date - timedelta(days=1)
    y_min = timezone.make_aware(datetime.combine(yesterday, time.min))
    y_max = timezone.make_aware(datetime.combine(yesterday, time.max))
    
    y_sales = Sale.objects.filter(sale_date__range=(y_min, y_max), doc_type='SALE', status='POSTED')
    y_returns = Sale.objects.filter(sale_date__range=(y_min, y_max), doc_type='RETURN', status='POSTED')
    
    if not is_owner:
        y_sales = y_sales.filter(created_by=user)
        y_returns = y_returns.filter(created_by=user)
        
    y_val_sales = y_sales.aggregate(s=Sum('grand_total'))['s'] or 0
    y_val_returns = abs(y_returns.aggregate(s=Sum('grand_total'))['s'] or 0)
    y_net_sales = y_val_sales - y_val_returns
    y_bills = y_sales.count()

    # ตัวตั้งต้นสำหรับการเปรียบเทียบ
    current_compare = net_sales if is_owner else total_bills
    yesterday_compare = y_net_sales if is_owner else y_bills

    if yesterday_compare > 0:
        change_percent = ((current_compare - yesterday_compare) / yesterday_compare * 100)
    else:
        change_percent = 100 if current_compare > 0 else 0

    # รายการรับเงินล่าสุด (แสดงทั้งขายและคืน)
    recent_payments = Payment.objects.filter(
        sale__status='POSTED',
        sale__sale_date__range=(query_min, query_max)
    ).select_related('sale', 'sale__created_by').order_by('-created_at')[:20]
    
    if not is_owner:
        recent_payments = recent_payments.filter(sale__created_by=user)

    # สต็อกสินค้า (Stock Overview)
    low_stock_products = Product.objects.filter(
        is_active=True,
        quantity__lte=10,
        quantity__gt=0
    ).select_related('category').order_by('quantity')[:10]

    low_stock_count = low_stock_products.count()
    out_of_stock_count = Product.objects.filter(is_active=True, quantity=0).count()
    
    inventory_value = Product.objects.filter(is_active=True).aggregate(
        total_value=Sum(F('quantity') * F('cost_price'))
    )['total_value'] or 0
    
    total_products = Product.objects.filter(is_active=True).count()

    # ===================================
    # 7. Context (ส่งค่าไปหน้าเว็บ)
    # ===================================
    context = {
        'is_owner': is_owner,
        
        # วันที่
        'actual_today': actual_today,
        'report_date': report_date,
        'prev_date': prev_date,
        'next_date': next_date,
        
        # ✅ เพิ่มตัวแปรเหล่านี้
        'today_sales_money': net_sales,        # ยอดขายสุทธิ
        'today_bills': total_bills,            # จำนวนบิล
        'today_profit': net_profit,            # กำไร
        'today_profit_margin': net_profit_margin,  # % กำไร
        'today_items_count': net_items_count,  # จำนวนชิ้น
        
        # เก็บชื่อเดิมไว้ด้วย (เผื่อใช้ที่อื่น)
        'total_sales': total_sales,
        'total_returns': total_returns,
        'net_sales': net_sales,
        'net_profit': net_profit,
        'net_items_count': net_items_count,
        'total_bills': total_bills,
        
        # ตัวเลขอื่นๆ
        'net_profit_margin': net_profit_margin,
        'change_percent': change_percent,
        'is_increase': change_percent >= 0,
        
        # รายการ
        'top_products_today': top_products_today,
        'last_7_days': last_7_days,
        'recent_payments': recent_payments,
        
        # สต็อก
        'low_stock_products': low_stock_products,
        'low_stock_count': low_stock_count,
        'out_of_stock_count': out_of_stock_count,
        'inventory_value': inventory_value,
        'total_products': total_products,
    }
    
    return render(request, 'products/dashboards/dashboard.html', context)


# ===================================
# 2. รายงานสินค้าขายดี
# ===================================
@login_required
def daily_top_products(request):
    """รายงานสินค้าขายดีประจำวัน"""
    
    # เลือกวันที่
    selected_date = request.GET.get('date')
    if selected_date:
        try:
            report_date = datetime.strptime(selected_date, '%Y-%m-%d').date()
        except:
            report_date = date.today()
    else:
        report_date = date.today()
    
    # ดึงข้อมูลสินค้าขายดี
    top_products = SaleItem.objects.filter(
        sale__status='POSTED',
        sale__sale_date__date=report_date
    ).values(
        'product__id',
        'product__sku',
        'product__name',
        'product__unit',
        'product__category__name',
    ).annotate(
        total_quantity=Sum('quantity'),
        total_amount=Sum('line_total'),
        total_cost=Sum(F('cost_price') * F('quantity')),
        total_profit=Sum((F('unit_price') - F('cost_price')) * F('quantity')),
        bill_count=Count('sale__id', distinct=True),
    ).order_by('-total_quantity')[:20]
    
    # คำนวณเพิ่มเติม
    for item in top_products:
        if item['total_amount']:
            item['profit_margin'] = (item['total_profit'] / item['total_amount'] * 100)
        else:
            item['profit_margin'] = 0
        
        item['avg_per_bill'] = item['total_quantity'] / item['bill_count'] if item['bill_count'] else 0
    
    # สรุปภาพรวม
    summary = SaleItem.objects.filter(
        sale__status='POSTED',
        sale__sale_date__date=report_date
    ).aggregate(
        total_items=Count('product__id', distinct=True),
        total_quantity=Sum('quantity'),
        total_sales=Sum('line_total'),
        total_cost=Sum(F('cost_price') * F('quantity')),
        total_profit=Sum((F('unit_price') - F('cost_price')) * F('quantity')),
    )
    
    # จำนวนบิล
    bill_count = Sale.objects.filter(
        status='POSTED',
        sale_date__date=report_date
    ).count()
    
    # คำนวณ Profit Margin
    if summary['total_sales']:
        summary['profit_margin'] = (summary['total_profit'] / summary['total_sales'] * 100)
    else:
        summary['profit_margin'] = 0
    
    context = {
        'report_date': report_date,
        'top_products': top_products,
        'summary': summary,
        'bill_count': bill_count,
        'today': date.today(),
    }
    
    return render(request, 'products/dashboards/daily_top_products.html', context)


# ===================================
# 3. รายงานสรุปยอดขาย
# ===================================
@login_required
def sales_summary(request):
    """รายงานสรุปยอดขายตามช่วงเวลา"""
    
    # เลือกช่วงเวลา
    period = request.GET.get('period', 'today')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    
    start_date = date.today
    end_date = date.today()
    
    # กำหนดช่วงวันที่
    if date_from and date_to:
        try:
            start_date = datetime.strptime(date_from, '%Y-%m-%d').date()
            end_date = datetime.strptime(date_to, '%Y-%m-%d').date()
            period = 'custom'
        except:
            start_date = date.today()
            end_date = date.today()
            period = 'today'
    else:
        if period == 'today':
            start_date = date.today()
            end_date = date.today()
        elif period == 'week':
            end_date = date.today()
            start_date = end_date - timedelta(days=7)
        elif period == 'month':
            end_date = date.today()
            start_date = end_date - timedelta(days=30)
        else:
            start_date = date.today()
            end_date = date.today()
    
    # ดึงข้อมูลยอดขาย
    sales = Sale.objects.filter(
        status='POSTED',
        sale_date__date__range=[start_date, end_date]
    ).aggregate(
        total_bills=Count('id'),
        total_sales=Sum('grand_total'),
        total_discount=Sum('discount_amount'),
        avg_per_bill=Avg('grand_total'),
    )
    
    # คำนวณกำไร
    items = SaleItem.objects.filter(
        sale__status='POSTED',
        sale__sale_date__date__range=[start_date, end_date]
    ).aggregate(
        total_cost=Sum(F('cost_price') * F('quantity')),
        total_revenue=Sum('line_total')
    )
    
    profit = (items['total_revenue'] or 0) - (items['total_cost'] or 0)
    profit_margin = (profit / items['total_revenue'] * 100) if items['total_revenue'] else 0
    
    # สรุปตามวิธีชำระเงิน
    payment_summary = Payment.objects.filter(
        sale__status='POSTED',
        sale__sale_date__date__range=[start_date, end_date]
    ).values('method').annotate(
        count=Count('id'),
        total=Sum('amount')
    ).order_by('-total')
    
    # รายงานรายวัน (ถ้าช่วงไม่เกิน 31 วัน)
    daily_sales = []
    if (end_date - start_date).days <= 31:
        current_date = start_date
        while current_date <= end_date:
            day_data = Sale.objects.filter(
                status='POSTED',
                sale_date__date=current_date
            ).aggregate(
                bills=Count('id'),
                total=Sum('grand_total')
            )
            
            daily_sales.append({
                'date': current_date,
                'bills': day_data['bills'] or 0,
                'total': day_data['total'] or 0,
            })
            
            current_date += timedelta(days=1)
    
    context = {
        'period': period,
        'start_date': start_date,
        'end_date': end_date,
        'sales': sales,
        'profit': profit,
        'profit_margin': profit_margin,
        'payment_summary': payment_summary,
        'daily_sales': daily_sales,
        'today': date.today(),
    }
    
    return render(request, 'products/dashboards/sales_summary.html', context)