"""
Views สำหรับรายงานการนำเข้าสินค้า (Purchase Report)
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Sum, Count, F
from datetime import datetime, timedelta
from decimal import Decimal

from products.models import Purchase, PurchaseItem, Supplier


def purchase_report(request):
    """
    หน้ารายงานการนำเข้าสินค้า
    
    Features:
    - แสดงรายการ Purchase ทั้งหมด
    - กรองตาม: วันที่, ซัพพลายเออร์, สถานะ
    - แสดงสถิติภาพรวม
    - Pagination
    """
    
    # ===== รับค่าจาก GET =====
    search = request.GET.get('search', '').strip()
    supplier_id = request.GET.get('supplier', '')
    status = request.GET.get('status', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    
    # ===== Query Purchase =====
    purchases = Purchase.objects.select_related('supplier', 'created_by').prefetch_related('items')
    
    # กรองตามเงื่อนไข
    if search:
        purchases = purchases.filter(
            Q(doc_no__icontains=search) |
            Q(supplier__name__icontains=search) |
            Q(remark__icontains=search)
        )
    
    if supplier_id:
        purchases = purchases.filter(supplier_id=supplier_id)
    
    if status:
        purchases = purchases.filter(status=status)
    
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d')
            purchases = purchases.filter(purchase_date__gte=date_from_obj)
        except:
            pass
    
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d')
            # เพิ่ม 1 วันเพื่อรวมวันสุดท้าย
            date_to_obj = date_to_obj + timedelta(days=1)
            purchases = purchases.filter(purchase_date__lt=date_to_obj)
        except:
            pass
    
    # เรียงลำดับ
    purchases = purchases.order_by('-purchase_date', '-id')
    
    # ===== คำนวณสถิติ =====
    stats = purchases.aggregate(
        total_purchases=Count('id'),
        total_items=Sum('items__quantity'),
        total_amount=Sum(F('items__quantity') * F('items__unit_cost'))
    )
    
    # ป้องกัน None
    if stats['total_amount'] is None:
        stats['total_amount'] = Decimal('0')
    if stats['total_items'] is None:
        stats['total_items'] = Decimal('0')
    
    # ===== Pagination =====
    paginator = Paginator(purchases, 20)  # 20 รายการต่อหน้า
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    # ===== ดึงข้อมูลเพิ่มเติม =====
    suppliers = Supplier.objects.order_by('name')
    
    # ✨ ไฮไลท์บิลล่าสุด (ถ้ามี)
    last_purchase_id = request.session.pop('last_purchase_id', None)
    
    return render(request, 'products/reports/purchase_report.html', {
        'page_obj': page_obj,
        'suppliers': suppliers,
        'search': search,
        'supplier_id': supplier_id,
        'status': status,
        'date_from': date_from,
        'date_to': date_to,
        'stats': stats,
        'last_purchase_id': last_purchase_id,
    })


def purchase_detail(request, id):
    """
    หน้ารายละเอียดบิลนำเข้า
    
    Features:
    - แสดงข้อมูลหัวบิล
    - แสดงตารางรายการสินค้า
    - คำนวณสต็อกจริง (quantity × pieces_per_unit)
    - ปุ่มพิมพ์, ยกเลิก
    """

    purchase = get_object_or_404(Purchase.objects.select_related('supplier', 'created_by').prefetch_related('items__product__category'), id=id)

    # ดึงรายการสินค้า
    items = purchase.items.select_related('product__category').order_by('id')
    
    # คำนวณยอดรวมและสต็อกจริง
    total_amount = Decimal('0')
    for item in items:
        item.actual_stock = item.quantity
        total_amount += item.line_total
    
    return render(request, 'products/reports/purchase_detail.html', {
        'purchase': purchase,
        'items': items,
        'total_amount': total_amount,
    })


def cancel_purchase(request, id):
    """
    ยกเลิกเอกสารรับเข้า (เฉพาะ DRAFT)
    
    - เปลี่ยนสถานะเป็น CANCELLED
    - ไม่สามารถยกเลิกเอกสาร POSTED ได้
    """
    
    if request.method != 'POST':
        return redirect('purchase_report')
    
    purchase = get_object_or_404(Purchase, id=id)
    
    if purchase.status == 'POSTED':
        messages.error(request, "❌ ไม่สามารถยกเลิกเอกสารที่ยืนยันแล้ว (POSTED)")
        return redirect('purchase_detail', id=id)
    
    if purchase.status == 'CANCELLED':
        messages.warning(request, "⚠️ เอกสารนี้ยกเลิกแล้ว")
        return redirect('purchase_detail', id=id)
    
    # ยกเลิก
    purchase.status = 'CANCELLED'
    purchase.save(update_fields=['status'])
    
    messages.success(request, f"✅ ยกเลิกเอกสาร {purchase.doc_no} เรียบร้อยแล้ว")
    return redirect('purchase_report')