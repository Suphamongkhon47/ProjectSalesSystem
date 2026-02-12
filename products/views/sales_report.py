import calendar
from datetime import datetime, time # ✅ ต้องเพิ่มตรงนี้

from django.forms import DecimalField
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count, F, ExpressionWrapper, DecimalField
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.utils import timezone
from django.db.models import Q

from products.models import Transaction, TransactionItem
from products.models.catalog import Category # ตรวจสอบ path ให้ถูกนะครับ
from django.contrib.auth.models import User

@login_required
def sales_report(request):
    # 1. รับค่าจาก URL
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    payment_method = request.GET.get('payment_method', '')
    search_doc_no = request.GET.get('search_doc_no', '').strip()
    status = request.GET.get('status', '')
    user_id = request.GET.get('user_id', '')
    search = request.GET.get('search', '').strip()
    category_id = request.GET.get('category', '')

    # 2. เตรียมช่วงเวลา (Timezone Aware) - ✅ แก้ไขส่วนนี้
    today = timezone.localdate() # ใช้วันที่ปัจจุบันตาม Timezone เครื่อง
    
    if not date_from or not date_to:
        today = timezone.now()
        year = today.year
        month = today.month
        last_day = calendar.monthrange(year, month)[1]
        date_from = f"{year}-{month:02d}-01"
        date_to = f"{year}-{month:02d}-{last_day}"

    # --- 🔥 จุดสำคัญ: แปลง String เป็น Timezone Aware Datetime ---
    # แปลง Text เป็น Date Object
    start_date_obj = datetime.strptime(date_from, "%Y-%m-%d").date()
    end_date_obj = datetime.strptime(date_to, "%Y-%m-%d").date()

    # รวมเวลา (00:00 - 23:59) และใส่ Timezone (Asia/Bangkok)
    start_aware = timezone.make_aware(datetime.combine(start_date_obj, time.min))
    end_aware = timezone.make_aware(datetime.combine(end_date_obj, time.max))
    # --------------------------------------------------------

    # 3. Query ข้อมูล (Base Query)
    # ✅ ใช้ transaction_date__range กับตัวแปรที่แปลง Timezone แล้ว
    sales = Transaction.objects.filter(
        transaction_date__range=(start_aware, end_aware), 
        doc_type='SALE'
    ).select_related('created_by').prefetch_related('payment')
    
    categories = Category.objects.annotate(product_count=Count('product')).order_by('name')
    all_categories = list(categories)
    
    if category_id:
        sales = sales.filter(items__product__category_id=category_id).distinct()

    # กรองตามสิทธิ์
    if request.user.is_superuser:
        users = User.objects.all()
        if user_id:
            sales = sales.filter(created_by_id=user_id)
    else:
        sales = sales.filter(created_by=request.user)
        users = []

    # กรองสถานะ
    if status:
        sales = sales.filter(status=status)
    else:
        sales = sales.filter(status='POSTED') # Default

    # กรองวิธีชำระเงิน
    if payment_method:
        sales = sales.filter(payment__method=payment_method)

    # ค้นหารหัสบิล
    if search_doc_no:
        sales = sales.filter(doc_no__icontains=search_doc_no)

    # 4. คำนวณสรุปยอด (Aggregate) ก่อนจะมีการ order_by หรือ annotate เพิ่มเติม
    summary = sales.aggregate(
        total_bills=Count('id'),
        total_amount=Sum('total_amount'),
        total_discount=Sum('discount_amount'),
        total_grand=Sum('grand_total'), 
    )

    if search:
        categories = categories.filter(
            Q(name__icontains=search) |
            Q(description__icontains=search)
        )

    # =========================================================
    # 🔥 คำนวณกำไรขั้นต้น (Gross Profit)
    # =========================================================
    # ดึงรายการสินค้ามาคำนวณกำไรรวมทั้งหมด (Total Profit Stat)
    sale_items = TransactionItem.objects.filter(transaction__in=sales)
    
    profit_stats = sale_items.aggregate(
        total_profit=Sum(
            ExpressionWrapper(
                (F('unit_price') - F('cost_price')) * F('quantity'),
                output_field=DecimalField()
            )
        )
    )
    summary['total_profit'] = profit_stats['total_profit'] or 0

    # Annotate กำไรต่อบิล (Bill Profit) เพื่อใช้แสดงในตาราง
    sales = sales.annotate(
        bill_profit=Sum(
            ExpressionWrapper(
                (F('items__unit_price') - F('items__cost_price')) * F('items__quantity'),
                output_field=DecimalField()
            )
        )
    )

    # ✅ Order by ครั้งเดียวพอ (เอาไว้ท้ายสุดก่อน Pagination)
    sales = sales.order_by('-transaction_date') 

    # แปลง None เป็น 0 ใน Summary
    for key in summary:
        if summary[key] is None: summary[key] = 0

    # 5. แบ่งหน้า (Pagination)
    paginator = Paginator(sales, 20)
    page = request.GET.get('page')
    try:
        page_obj = paginator.get_page(page)
    except PageNotAnInteger:
        page_obj = paginator.get_page(1)
    except EmptyPage:
        page_obj = paginator.get_page(paginator.num_pages)

    # 6. จับคู่บิลคืน (Map Returns)
    # ใช้ page_obj แทน sales เพื่อลด Query (ดึงเฉพาะหน้าปัจจุบัน)
    sale_doc_nos = [sale.doc_no for sale in page_obj]
    
    related_returns = Transaction.objects.filter(
        doc_type='RETURN',
        ref_doc_no__in=sale_doc_nos,
        status='POSTED'
    ).values('ref_doc_no', 'doc_no', 'grand_total')
    
    returns_map = {}
    for ret in related_returns:
        ref = ret['ref_doc_no']
        if ref not in returns_map:
            returns_map[ref] = []
            
        returns_map[ref].append({
            'doc_no': ret['doc_no'],
            'amount': abs(ret['grand_total'])
        })
        
    # 7. เตรียมข้อมูลลงตาราง
    sales_data = []
    for sale in page_obj:
        # ใช้ getattr ป้องกัน error กรณีไม่มี payment
        payment = getattr(sale, 'payment', None) 
        
        # payment_method = payment.first().method if payment.exists() else '-' 
        # (หมายเหตุ: ถ้า one-to-one หรือ many-to-one เช็ค structure Model ดีๆครับ)
        
        return_list = returns_map.get(sale.doc_no, [])
        total_refunded = sum(r['amount'] for r in return_list)
        
        net_total = sale.grand_total - total_refunded
        profit = sale.bill_profit or 0

        sales_data.append({
            'sale': sale,
            'payment': payment,
            'return': return_list,
            'has_return': len(return_list) > 0,
            'refund_total': total_refunded,
            'net_total': net_total,
            'profit': profit,
        })

    payment_methods = [
        {'value': 'cash', 'label': '💵 เงินสด'},
        {'value': 'qr', 'label': '📱 QR Code'},
        {'value': 'transfer', 'label': '🏦 โอนเงิน'},
    ]

    context = {
        'sales': sales_data,
        'page_obj': page_obj,
        'summary': summary,
        'date_from': date_from,
        'date_to': date_to,
        'payment_method': payment_method,
        'status': status,
        'search_doc_no': search_doc_no,
        'payment_methods': payment_methods,
        'users': users,
        'selected_user_id': user_id,
        'categories': all_categories,
        'search': search,
        'category_id': category_id,
        'is_owner': request.user.is_superuser,
    }

    return render(request, 'products/reports/sales_report.html', context)