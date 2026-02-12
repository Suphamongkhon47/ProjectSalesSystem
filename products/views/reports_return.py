"""
Reports & Statistics for Returns (แก้ไขแล้ว - แยกสิทธิ์)
จัดการการแสดงผลข้อมูล: รายการคืน, รายละเอียด, และสถิติ
"""

import calendar
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.db.models import Q, Sum, Count
from django.views.decorators.http import require_http_methods

from datetime import datetime, time, timedelta
from django.core.paginator import Paginator
from django.db.models.functions import TruncDate
from django.contrib.auth.models import User
from django.views.decorators.clickjacking import xframe_options_exempt
from django.utils import timezone

from products.models import Transaction, TransactionItem


# ===================================
# 1. หน้าประวัติการรับคืนสินค้า (List) - แก้ไขแล้ว
# ===================================
@login_required
def return_list(request):
    """
    แสดงรายการบิลรับคืนทั้งหมด พร้อมระบบกรองข้อมูลพนักงานและวันที่ (Default: เดือนปัจจุบัน)
    """
    current_user = request.user
    is_owner = current_user.is_superuser
    
    # 1. รับค่า Filter จาก URL
    status = request.GET.get('status', '')
    search = request.GET.get('search', '')
    user_filter = request.GET.get('user_id', '')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')

    # 2. กำหนดค่าเริ่มต้นเป็น "วันที่ 1" ถึง "วันสุดท้าย" ของเดือนปัจจุบัน หากยังไม่ได้เลือกวันที่
    if not date_from or not date_to:
        today = timezone.now()
        year = today.year
        month = today.month
        
        # หาวันสุดท้ายของเดือนนั้นๆ
        last_day = calendar.monthrange(year, month)[1]
        
        # สร้าง String วันที่ในรูปแบบ YYYY-MM-DD เพื่อส่งให้ HTML Input
        date_from = f"{year}-{month:02d}-01"
        date_to = f"{year}-{month:02d}-{last_day}"
    start_date_obj = datetime.strptime(date_from, "%Y-%m-%d").date()
    end_date_obj = datetime.strptime(date_to, "%Y-%m-%d").date()
    start_aware = timezone.make_aware(datetime.combine(start_date_obj, time.min))
    end_aware = timezone.make_aware(datetime.combine(end_date_obj, time.max))
    # 3. Query พื้นฐาน (เฉพาะใบคืนสินค้า)
    returns = Transaction.objects.filter(doc_type='RETURN').select_related('created_by').order_by('-transaction_date')
    
    # 4. เริ่มการกรองข้อมูล (Filtering)
    
    # กรองตามช่วงวันที่ (ครอบคลุมทั้งวัน)
    # ✅ แก้ไข: ใช้ __date__gte + __date__lte แทน __range
    returns = returns.filter(transaction_date__range=(start_aware, end_aware))

    # กรองตามสิทธิ์และพนักงาน
    if not is_owner:
        returns = returns.filter(created_by=current_user)
    elif user_filter:
        returns = returns.filter(created_by_id=user_filter)
        
    # กรองสถานะ
    if status:
        returns = returns.filter(status=status)
            
    # กรองคำค้นหา
    if search:
        returns = returns.filter(
            Q(doc_no__icontains=search) |
            Q(ref_doc_no__icontains=search) |
            Q(created_by__username__icontains=search)
        )

    # ดึงรายชื่อพนักงานสำหรับ Dropdown (เฉพาะเจ้าของร้าน)
    all_staff = User.objects.filter(is_active=True).order_by('username') if is_owner else None

    # 5. คำนวณ Metrics (Aggregate)
    metrics = returns.aggregate(
        total_amount=Sum('grand_total'),
        total_discount=Sum('discount_amount'),
        total_count=Count('id')
    )
    
    # คำนวณจำนวนชิ้นสินค้าคืนรวม
    qty_data = TransactionItem.objects.filter(transaction__in=returns).aggregate(
        total_qty=Sum('quantity')
    )
    metrics['total_quantity'] = qty_data['total_qty'] or 0

    # 6. Pagination (แสดงหน้าละ 20 รายการ)
    paginator = Paginator(returns, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # 7. ส่งค่าทุกอย่างกลับไปที่หน้าเว็บ
    context = {
        'returns': page_obj,
        'metrics': metrics,
        'all_staff': all_staff,
        'user_filter': user_filter,
        'status': status,
        'date_from': date_from,
        'date_to': date_to,
        'search': search,
    }
    
    return render(request, 'products/returns/return_list.html', context)
# ===================================
# 2. หน้ารายละเอียดการคืน (Detail) - แก้ไขแล้ว
# ===================================
@xframe_options_exempt
@login_required
def return_detail(request, return_id):
    """
    แสดงรายละเอียดของบิลรับคืน 1 ใบ
    ✅ แยกสิทธิ์: Staff ดูได้เฉพาะบิลของตัวเอง
    """
    from products.models import SystemSetting
    
    user = request.user
    is_owner = user.is_superuser
    
    # ดึงข้อมูลบิลคืน
    sale = get_object_or_404(Transaction, id=return_id, doc_type='RETURN')

    # ✅ ตรวจสอบสิทธิ์: Staff ดูได้เฉพาะของตัวเอง
    if not is_owner and sale.created_by != user:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("คุณไม่มีสิทธิ์เข้าถึงบิลนี้")
    
    # ดึงรายการสินค้า
    items = sale.items.select_related('product', 'product__category').all()
    payment_method_display = 'ไม่ระบุ'
    if hasattr(sale, 'payment') and sale.payment:
        if sale.payment.method == 'cash':
            payment_method_display = '💵 เงินสด'
        elif sale.payment.method == 'transfer':
            payment_method_display = '🏦 โอนเงิน'
        elif sale.payment.method == 'credit':
            payment_method_display = '💳 บัตรเครดิต'
        else:
            payment_method_display = sale.payment.method
            
    # คำนวณจำนวนรวม
    total_quantity = items.aggregate(total=Sum('quantity'))['total'] or 0
    sale.total_quantity = total_quantity
    
    # หาบิลต้นฉบับ
    original_return = None
    if sale.ref_doc_no:
        original_return = Transaction.objects.filter(doc_no=sale.ref_doc_no, doc_type='SALE').first()
    
    # ✅ ดึง settings
    settings = SystemSetting.get_all()
    
    context = {
        'sale': sale,
        'items': items,
        'original_return': original_return,
        'print_date': timezone.now(),
        'payment_method_display': payment_method_display,
        'settings': settings,  # ✅ ส่ง settings ไปให้ template
    }
    
    return render(request, 'products/returns/return_detail.html', context)


# ===================================
# 3. API: เช็คประวัติการคืนของบิลขาย (Check History)
# ===================================
@login_required
@require_http_methods(["GET"])
def check_returned_items(request, sale_id):
    """
    API สำหรับตรวจสอบว่าบิลขายใบนี้เคยมีการคืนสินค้าหรือไม่
    """
    try:
        original_Transaction = get_object_or_404(Transaction, id=sale_id, doc_type='SALE')
        
        # หาบิลคืนที่อ้างอิง
        returns = Transaction.objects.filter(
            doc_type='RETURN',
            ref_doc_no=original_Transaction.doc_no,
            status='POSTED'
        )
        
        # ✅ คำนวณยอดคืนโดยใช้ Aggregate
        returned_items = TransactionItem.objects.filter(
            transaction__in=returns
        ).values('product_id').annotate(
            total_returned=Sum('quantity')
        )
        
        returned_map = {}
        for item in returned_items:
            returned_map[item['product_id']] = {
                'product_id': item['product_id'],
                'total_returned': float(item['total_returned'])
            }
        
        return JsonResponse({
            'success': True,
            'returned_items': list(returned_map.values())
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


