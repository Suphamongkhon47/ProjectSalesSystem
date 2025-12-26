from weakref import ref
from django.forms import DecimalField
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count, F, ExpressionWrapper , DecimalField
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.utils import timezone
from datetime import datetime, timedelta, time # ต้องมี time ด้วย
from products.models import Sale
from django.contrib.auth.models import User

from products.models.sale import SaleItem


@login_required
def sales_report(request):
    # 1. รับค่าจาก URL
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    payment_method = request.GET.get('payment_method', '')
    search_doc_no = request.GET.get('search_doc_no', '').strip()
    status = request.GET.get('status', '')
    user_id = request.GET.get('user_id', '')

    # 2. เตรียมช่วงเวลา (Timezone Aware)
    today = timezone.localdate()
    
    if start_date_str:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
    else:
        start_date = today - timedelta(days=30)

    if end_date_str:
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    else:
        end_date = today

    start_dt = timezone.make_aware(datetime.combine(start_date, time.min))
    end_dt = timezone.make_aware(datetime.combine(end_date, time.max))

    # 3. Query ข้อมูล (Base Query)
    # กรองเฉพาะบิลขาย (SALE) เพื่อไม่ให้สับสนกับบิลคืนในตารางหลัก
    sales = Sale.objects.filter(
        sale_date__range=(start_dt, end_dt),
        doc_type='SALE' 
    ).select_related('created_by').prefetch_related('payment')
    
    # กรองตามสิทธิ์ (Admin เห็นหมด, พนักงานเห็นแค่ตัวเอง)
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
        # Default: ดูเฉพาะที่ขายสำเร็จ
        sales = sales.filter(status='POSTED')

    # กรองวิธีชำระเงิน
    if payment_method:
        sales = sales.filter(payment__method=payment_method)

    # ค้นหารหัสบิล
    if search_doc_no:
        sales = sales.filter(doc_no__icontains=search_doc_no)

    # เรียงลำดับล่าสุดก่อน
    sales = sales.order_by('-sale_date')

    # 4. คำนวณสรุปยอด (Aggregate)
    summary = sales.aggregate(
        total_bills=Count('id'),
        total_amount=Sum('total_amount'),
        total_discount=Sum('discount_amount'),
        total_grand=Sum('grand_total'),  # 👈 เพิ่มบรรทัดนี้
    )

    # =========================================================
    # 🔥 เพิ่ม: คำนวณกำไรขั้นต้น (Gross Profit)
    # =========================================================
    # ต้องดึงรายการสินค้า (SaleItem) ที่อยู่ในบิลเหล่านี้มาคำนวณ
    sale_items = SaleItem.objects.filter(sale__in=sales)
    
    # สูตร: (ราคาขาย - ทุน) * จำนวน
    profit_stats = sale_items.aggregate(
        total_profit=Sum(
            ExpressionWrapper(
                (F('unit_price') - F('cost_price')) * F('quantity'),
                output_field=DecimalField()
            )
        )
    )
    
    # เพิ่มค่ากำไรเข้าไปใน summary
    summary['total_profit'] = profit_stats['total_profit'] or 0
    # =========================================================

    # แปลง None เป็น 0
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
    sale_doc_nos = [sale.doc_no for sale in page_obj]
    
    related_returns = Sale.objects.filter(
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
            'amount': abs(ret['grand_total']) # แปลงเป็นบวกเพื่อให้ดูง่าย
        })
        
    # 7. เตรียมข้อมูลลงตาราง
    sales_data = []
    for sale in page_obj:
        payment = getattr(sale, 'payment', None)
        
        # ข้อมูลการคืน
        return_list = returns_map.get(sale.doc_no, [])
        total_refunded = sum(r['amount'] for r in return_list)
        
        # ✅ คำนวณยอดสุทธิ (Net Total) = ยอดขาย - ยอดคืน
        net_total = sale.grand_total - total_refunded

        sales_data.append({
            'sale': sale,
            'payment': payment,
            'return': return_list,
            'has_return': len(return_list) > 0,
            'refund_total': total_refunded,
            'net_total': net_total, # ส่งยอดสุทธิไปด้วย
        })

    # ตัวเลือก Dropdown
    payment_methods = [
        {'value': 'cash', 'label': '💵 เงินสด'},
        {'value': 'qr', 'label': '📱 QR Code'},
        {'value': 'transfer', 'label': '🏦 โอนเงิน'},
    ]

    context = {
        'sales': sales_data,
        'page_obj': page_obj,
        'summary': summary,
        'start_date': start_date,
        'end_date': end_date,
        'payment_method': payment_method,
        'status': status,
        'search_doc_no': search_doc_no,
        'payment_methods': payment_methods,
        'users': users,
        'selected_user_id': user_id,
    }

    return render(request, 'products/reports/sales_report.html', context)