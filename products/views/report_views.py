from decimal import Decimal
from django.shortcuts import render
from django.db.models import Sum, Count, Q
from django.db.models.functions import TruncDate
from datetime import datetime, timedelta

from products.models import StockMovement


def import_report(request):
    """รายงานการนำเข้าสินค้า"""
    
    # ===== รับค่า Filter =====
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    created_by = request.GET.get('created_by', '').strip()
    search = request.GET.get('search', '').strip()
    
    # Default: 30 วันล่าสุด
    if not end_date:
        end_date = datetime.now().date()
    else:
        end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
    
    if not start_date:
        start_date = end_date - timedelta(days=30)
    else:
        start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
    
    # ===== Query รายการนำเข้า (IN) =====
    movements = StockMovement.objects.filter(
        movement_type='IN',
        created_at__date__gte=start_date,
        created_at__date__lte=end_date
    ).select_related('product', 'product__category').order_by('-created_at')
    
    # ✅ Filter ผู้นำเข้า (แก้แล้ว - ค้นหาในฟิลด์ note เท่านั้น)
    if created_by:
        movements = movements.filter(note__icontains=created_by)
    
    # ค้นหาสินค้า
    if search:
        movements = movements.filter(
            Q(product__sku__icontains=search) |
            Q(product__name__icontains=search)
        )
    
    # ===== สรุปภาพรวม =====
    total_items = movements.count()
    total_quantity = movements.aggregate(Sum('quantity'))['quantity__sum'] or 0
    
    # ✅ คำนวณมูลค่ารวม (แก้แล้ว - ป้องกัน None)
    total_value = Decimal('0')
    for m in movements:
        if m.product and m.product.cost_price:
            total_value += m.quantity * m.product.cost_price
    
    # ===== สรุปตามผู้นำเข้า =====
    importers = []
    
    # ✅ ดึงรายชื่อผู้นำเข้าจาก note (แก้แล้ว - ป้องกัน None)
    importer_notes = movements.exclude(note__isnull=True).exclude(note='').values_list('note', flat=True).distinct()
    importer_names = set()
    
    for note in importer_notes:
        if note and 'โดย' in note:
            # แยกชื่อจาก "นำเข้าครั้งแรก 5 ชิ้น (โดย John)"
            try:
                parts = note.split('โดย')
                if len(parts) > 1:
                    name = parts[1].strip().rstrip(')')
                    if name and name != '-':
                        importer_names.add(name)
            except Exception:
                continue
    
    # สรุปแต่ละคน
    for name in importer_names:
        person_movements = movements.filter(note__icontains=f'โดย {name}')
        person_items = person_movements.count()
        person_quantity = person_movements.aggregate(Sum('quantity'))['quantity__sum'] or 0
        
        # คำนวณมูลค่า
        person_value = Decimal('0')
        for m in person_movements:
            if m.product and m.product.cost_price:
                person_value += m.quantity * m.product.cost_price
        
        importers.append({
            'name': name,
            'items': person_items,
            'quantity': person_quantity,
            'value': person_value,
        })
    
    # เรียงตามมูลค่า
    importers = sorted(importers, key=lambda x: x['value'], reverse=True)
    
    # ===== สรุปตามวัน =====
    daily_summary = movements.annotate(
        date=TruncDate('created_at')
    ).values('date').annotate(
        count=Count('id'),
        total_qty=Sum('quantity')
    ).order_by('-date')[:10]  # 10 วันล่าสุด
    
    # คำนวณมูลค่าแต่ละวัน
    for day in daily_summary:
        day_movements = movements.filter(created_at__date=day['date'])
        day_value = Decimal('0')
        for m in day_movements:
            if m.product and m.product.cost_price:
                day_value += m.quantity * m.product.cost_price
        day['value'] = day_value
    
    # ===== Context =====
    context = {
        'movements': movements[:100],  # จำกัด 100 รายการ
        'total_items': total_items,
        'total_quantity': total_quantity,
        'total_value': total_value,
        'importers': importers,
        'daily_summary': daily_summary,
        'start_date': start_date,
        'end_date': end_date,
        'created_by': created_by,
        'search': search,
    }
    
    return render(request, 'products/reports/import_report.html', context)


def import_detail(request, movement_id):
    """รายละเอียดการนำเข้าแต่ละรายการ"""
    
    movement = StockMovement.objects.select_related(
        'product', 
        'product__category'
    ).get(id=movement_id)
    
    # ประวัติการนำเข้าสินค้านี้
    history = StockMovement.objects.filter(
        product=movement.product,
        movement_type='IN'
    ).order_by('-created_at')[:20]
    
    context = {
        'movement': movement,
        'history': history,
    }
    
    return render(request, 'products/reports/import_detail.html', context)