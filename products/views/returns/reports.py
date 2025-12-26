"""
Reports & Statistics for Returns
จัดการการแสดงผลข้อมูล: รายการคืน, รายละเอียด, และสถิติ
"""

from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.db.models import Q, Sum, Count, F
from django.views.decorators.http import require_http_methods
from decimal import Decimal
from datetime import datetime, timedelta
from django.core.paginator import Paginator
from django.db.models.functions import TruncDate
from collections import Counter
from django.views.decorators.clickjacking import xframe_options_exempt

from products.models import Sale, SaleItem, Product

# ===================================
# 1. หน้าประวัติการรับคืนสินค้า (List)
# ===================================
@login_required
def return_list(request):
    """
    แสดงรายการบิลรับคืนทั้งหมด 
    พร้อมระบบค้นหา (Search), กรอง (Filter), และแบ่งหน้า (Pagination)
    """
    
    # รับค่า Filter จาก URL
    status = request.GET.get('status', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    search = request.GET.get('search', '')
    reason = request.GET.get('reason', '')
    
    # 1. Query เริ่มต้น: เอาเฉพาะบิลประเภท 'RETURN'
    returns = Sale.objects.filter(
        doc_type='RETURN'
    ).select_related('created_by', 'payment').order_by('-created_at')
    
    # 2. กรองข้อมูล
    if status:
        returns = returns.filter(status=status)
    
    if date_from:
        returns = returns.filter(sale_date__date__gte=date_from)
    
    if date_to:
        returns = returns.filter(sale_date__date__lte=date_to)
    
    if search:
        returns = returns.filter(
            Q(doc_no__icontains=search) |
            Q(ref_doc_no__icontains=search) |
            Q(remark__icontains=search)
        )
    
    # (ถ้ามี field return_reason ใน model ให้เปิดใช้)
    # if reason:
    #     returns = returns.filter(return_reason=reason)

    # 3. สรุปยอดรวม (Summary) ของข้อมูลที่กรองมา
    summary = returns.filter(status='POSTED').aggregate(
        total_amount=Sum('grand_total'),
        count=Count('id')
    )
    
    posted_returns = returns.filter(status='POSTED')

    summary = posted_returns.aggregate(
        total_amount=Sum('grand_total'),
        total_discount=Sum('discount_amount'),
        count=Count('id')
    )

    # คำนวณ total_quantity จาก SaleItem
    from products.models import SaleItem

    total_quantity = SaleItem.objects.filter(
        sale__in=posted_returns
    ).aggregate(
        total=Sum('quantity')
    )['total'] or 0

    summary['total_quantity'] = total_quantity
    
    # 4. แบ่งหน้า (Pagination) - 20 รายการต่อหน้า
    paginator = Paginator(returns, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'returns': page_obj,      # ส่ง object ที่แบ่งหน้าแล้วไปวนลูป
        'summary': summary,       # ยอดรวม
        # ส่งค่า filter กลับไปแสดงใน Input เดิม
        'status': status,
        'date_from': date_from,
        'date_to': date_to,
        'search': search,
        'reason': reason,
    }
    
    return render(request, 'products/returns/return_list.html', context)


# ===================================
# 2. หน้ารายละเอียดการคืน (Detail)
# ===================================
@xframe_options_exempt
@login_required
def return_detail(request, return_id):
    """
    แสดงรายละเอียดของบิลรับคืน 1 ใบ
    """
    # ดึงข้อมูลบิลคืน
    return_sale = get_object_or_404(
        Sale, 
        id=return_id, 
        doc_type='RETURN'
    )
    
    # ดึงรายการสินค้าในบิลคืน
    items = return_sale.items.select_related('product', 'product__category').all()
    
    # พยายามดึงข้อมูลบิลต้นฉบับ (Original Sale) เพื่อทำ Link กลับไปดู
    original_sale = None
    if return_sale.ref_doc_no:
        original_sale = Sale.objects.filter(
            doc_no=return_sale.ref_doc_no,
            doc_type='SALE'
        ).first()
    
    context = {
        'sale': return_sale,        # ใช้ชื่อ sale เพื่อให้ template ใช้ร่วมกับ sale_detail ปกติได้ง่าย
        'items': items,
        'original_sale': original_sale,
    }
    
    return render(request, 'products/returns/return_detail.html', context)


# ===================================
# 3. API: เช็คประวัติการคืนของบิลขาย (Check History)
# ===================================
@login_required
@require_http_methods(["GET"])
def check_returned_items(request, sale_id):
    """
    API สำหรับตรวจสอบว่าบิลขายใบนี้ (Original Sale)
    เคยมีการคืนสินค้าชิ้นไหนไปแล้วบ้าง และจำนวนเท่าไหร่
    (ใช้ป้องกันการคืนซ้ำเกินจำนวนที่ซื้อ)
    """
    try:
        # หาบิลขายต้นฉบับ
        original_sale = get_object_or_404(Sale, id=sale_id, doc_type='SALE')
        
        # หาบิลคืนทั้งหมด ที่อ้างอิงถึงบิลนี้ และสถานะสำเร็จ (POSTED)
        returns = Sale.objects.filter(
            doc_type='RETURN',
            ref_doc_no=original_sale.doc_no,
            status='POSTED'
        )
        
        # คำนวณยอดรวมการคืนแยกตามสินค้า
        returned_map = {}
        
        for ret in returns:
            for item in ret.items.all():
                pid = item.product_id
                if pid not in returned_map:
                    returned_map[pid] = {
                        'product_id': pid,
                        'total_returned': 0,
                        'history': [] # (Optional) เก็บประวัติย่อยๆ ว่าคืนวันไหน
                    }
                
                # บวกจำนวนที่เคยคืน
                returned_map[pid]['total_returned'] += float(item.quantity)
                
                # (Optional) เก็บ Log เล็กๆ
                returned_map[pid]['history'].append({
                    'date': ret.sale_date.strftime('%d/%m/%Y'),
                    'qty': float(item.quantity),
                    'doc_no': ret.doc_no
                })
        
        return JsonResponse({
            'success': True,
            'returned_items': list(returned_map.values())
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# ===================================
# 4. หน้าแดชบอร์ดสถิติการคืน (Statistics)
# ===================================
@login_required
def return_statistics(request):
    """
    แสดงกราฟและตัวเลขสถิติการคืนสินค้า (Dashboard)
    """
    # ช่วงเวลา (Default: 30 วันย้อนหลัง)
    days = int(request.GET.get('days', 30))
    start_date = datetime.now() - timedelta(days=days)
    
    # Query ข้อมูลคืนทั้งหมดในช่วงเวลา
    returns = Sale.objects.filter(
        doc_type='RETURN',
        status='POSTED',
        sale_date__gte=start_date
    )
    
    # 1. สรุปยอดรายวัน (สำหรับทำ Graph)
    # Group by วันที่ -> Count, Sum
    daily_stats = returns.annotate(
        date=TruncDate('sale_date')
    ).values('date').annotate(
        count=Count('id'),
        total=Sum('grand_total')
    ).order_by('date')
    
    # 2. สินค้าที่ถูกคืนบ่อยที่สุด (Top 5 Products)
    product_counter = Counter()
    reason_counter = Counter() # ถ้ามี field reason
    
    for ret in returns:
        # นับเหตุผล (ถ้าเก็บไว้ใน remark หรือ field แยก)
        # reason_counter[ret.remark or 'ไม่ระบุ'] += 1
        
        for item in ret.items.select_related('product'):
            # นับจำนวนชิ้นที่ถูกคืน
            product_counter[item.product] += float(item.quantity)
            
    # จัด Format Top 5 สินค้า
    top_products = []
    for product, qty in product_counter.most_common(5):
        top_products.append({
            'sku': product.sku,
            'name': product.name,
            'qty': qty,
            'amount': qty * float(product.selling_price) # มูลค่าคร่าวๆ
        })

    # 3. ตัวเลข Key Metrics
    total_return_amount = returns.aggregate(Sum('grand_total'))['grand_total__sum'] or 0
    total_return_count = returns.count()
    
    context = {
        'days': days,
        'daily_stats': list(daily_stats), # แปลงเป็น list ให้ JSON ใช้ได้ง่ายใน template
        'top_products': top_products,
        'total_amount': total_return_amount,
        'total_count': total_return_count,
    }
    
    return render(request, 'products/returns/return_statistics.html', context)