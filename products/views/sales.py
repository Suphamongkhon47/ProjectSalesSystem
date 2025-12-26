"""
Views: Sales (ขายสินค้า)
รองรับ: Smart Search, ราคาขายส่ง/ปลีก, Payment Methods
(Clean Version: สำหรับขายอย่างเดียว ตัดส่วนคืนสินค้าออกแล้ว)
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.db.models import Q, F, Sum, Count
from django.db import transaction
from django.views.decorators.http import require_http_methods
from decimal import Decimal
from datetime import datetime
import json
from django.urls import reverse
from django.views.decorators.clickjacking import xframe_options_exempt

from products.models import (Product, Sale, SaleItem)
from products.Services.sale_service import (
    create_sale_transaction, 
    post_sale, 
    cancel_sale as service_cancel_sale,
    create_payment
)


# ===================================
# 1. หน้าหลักขาย (POS)
# ===================================
@login_required
def sales(request):
    """หน้าขายสินค้าหลัก"""
    today = datetime.now()
    doc_prefix = f"SALE-{today.strftime('%Y%m%d')}"
    
    today_sales_count = Sale.objects.filter(doc_no__startswith=doc_prefix).count()
    next_number = str(today_sales_count + 1).zfill(4)
    doc_no = f"{doc_prefix}-{next_number}"
    
    context = {'doc_no': doc_no, 'today': today}
    return render(request, 'products/sales/sale_create.html', context)


# ===================================
# 2. ค้นหาสินค้า (AJAX) - Smart Search
# ===================================
@login_required
@require_http_methods(["GET"])
def search_products_ajax(request):
    """ค้นหาสินค้าอัจฉริยะ"""
    
    query = request.GET.get('q', '').strip()
    
    if len(query) < 1:
        return JsonResponse({'products': []})
    
    # Priority: SKU ตรง → SKU คล้าย → ชื่อ → รุ่นรถ
    exact_sku = list(Product.objects.filter(sku__iexact=query, is_active=True).select_related('category')[:5])
    excluded_ids = [p.id for p in exact_sku]
    
    similar_sku = list(Product.objects.filter(sku__icontains=query, is_active=True).exclude(id__in=excluded_ids).select_related('category')[:10])
    excluded_ids.extend([p.id for p in similar_sku])
    
    name_products = list(Product.objects.filter(name__icontains=query, is_active=True).exclude(id__in=excluded_ids).select_related('category')[:8])
    excluded_ids.extend([p.id for p in name_products])
    
    car_products = list(Product.objects.filter(compatible_models__icontains=query, is_active=True).exclude(id__in=excluded_ids).select_related('category')[:7])
    
    # รวมผลลัพธ์
    products = (exact_sku + similar_sku + name_products + car_products)[:20]
    
    # สร้าง JSON
    results = []
    for p in products:
        # สต็อก = หน่วยตรงๆ
        stock_qty = p.quantity if p.quantity else 0
        
        # ระบุ Match Type
        match_type = 'sku'
        if p in exact_sku: match_type = 'exact_sku'
        elif p in name_products: match_type = 'name'
        elif p in car_products: match_type = 'car'
        
        results.append({
            'id': p.id,
            'sku': p.sku,
            'name': p.name,
            'category': p.category.name if p.category else '-',
            'compatible_models': p.compatible_models or '',
            'unit': p.unit,
            'cost_price': float(p.cost_price),
            'selling_price': float(p.selling_price),
            'wholesale_price': float(p.wholesale_price),
            'stock_units': float(stock_qty),
            'has_stock': stock_qty > 0,
            'match_type': match_type,
        })
    
    return JsonResponse({
        'products': results,
        'count': len(results)
    })


# ===================================
# 3. บันทึกบิลขาย (AJAX) - (Clean: ตัดส่วนรับคืนออกแล้ว)
# ===================================
@login_required
@require_http_methods(["POST"])
def create_sale(request):
    """
    บันทึกบิลขาย (SALE Only)
    รองรับการ "พักบิล" (HOLD) โดยการรับสถานะและไม่ตัดสต็อก
    """
    try:
        data = json.loads(request.body)
        sale_id = data.get('sale_id')
        doc_no = data.get('doc_no')
        items = data.get('items', [])
        
        # Payment Info
        price_type = data.get('price_type', 'retail')
        payment_method = data.get('payment_method', 'cash')
        
        # ✅ 1. แปลงค่าเงินเป็น Decimal ให้ปลอดภัย
        try:
            # ใช้ 0 ถ้าไม่มีค่าส่งมา
            payment_received = Decimal(str(data.get('payment_received', 0) or 0))
        except:
            payment_received = Decimal('0.00')

        # payment_change ไม่ต้องรับจาก Frontend เราจะคำนวณเอง
        
        try:
            discount_amount = Decimal(str(data.get('discount_amount', 0) or 0))
        except:
            discount_amount = Decimal('0.00')
            
        remark = data.get('remark', '')
        
        # ✅ รับค่า Config และ Status
        auto_post = data.get('auto_post', True)
        status = data.get('status', 'DRAFT') 
        
        if not items:
            return JsonResponse({'success': False, 'error': 'ไม่มีรายการสินค้า'}, status=400)
        
        # เช็คเลขที่ซ้ำ (เฉพาะสร้างใหม่)
        if doc_no and not sale_id and Sale.objects.filter(doc_no=doc_no).exists():
            return JsonResponse({'success': False, 'error': f'เลขที่บิล {doc_no} มีอยู่แล้ว'}, status=400)
        
        # ✅ 2. เรียกใช้ Service: สร้างบิลและรายการสินค้า
        # เพื่อให้ได้ยอด grand_total ที่ถูกต้องจากการคำนวณใน model
        sale = create_sale_transaction(
            user=request.user,
            sale_id=sale_id,
            items_data=items,
            price_type=price_type,
            discount_amount=discount_amount,
            remark=remark,
            doc_no=doc_no,
            doc_type='SALE',
            status=status 
        )
        
        # ✅ 3. ตรวจสอบและคำนวณยอดเงิน (เฉพาะสถานะที่จะจบการขาย ไม่ใช่ HOLD)
        payment_change = Decimal('0.00')
        
        if status != 'HOLD':
            if payment_method == 'cash':
                # ตรวจสอบยอดเงินรับ
                if payment_received < sale.grand_total:
                    # ถ้ายอดเงินไม่พอ ต้องยกเลิกบิลที่เพิ่งสร้างและแจ้งเตือน
                    # หมายเหตุ: ในทางปฏิบัติอาจจะแค่ไม่บันทึก Payment หรือแจ้ง Error เลย
                    # แต่เนื่องจาก sale สร้างไปแล้วใน transaction นี้ ถ้า error ตรงนี้ transaction ทั้งหมดใน view นี้น่าจะ rollback ไม่ได้อัตโนมัติถ้าไม่ได้ใส่ atomic ไว้ที่ view
                    # ดังนั้นเราลบบิลทิ้งเลยจะง่ายกว่า
                    sale.delete() 
                    return JsonResponse({
                        'success': False, 
                        'error': f'ยอดเงินที่รับมาไม่เพียงพอ (ขาด {sale.grand_total - payment_received:,.2f} บาท)'
                    }, status=400)
                
                # คำนวณเงินทอน
                payment_change = payment_received - sale.grand_total
            else:
                # กรณี QR/Transfer ถือว่ารับยอดเท่ากับยอดขายเสมอ
                payment_received = sale.grand_total
        
        # ✅ 4. บันทึก Payment
        # บันทึก Note เงินทอนลงไปด้วยเพื่อความชัดเจน
        payment_note = f"เงินทอน: {payment_change:,.2f}" if payment_method == 'cash' and status != 'HOLD' else ""
        
        create_payment(
            sale=sale,
            method=payment_method,
            received=payment_received,
            note=payment_note
        )
        
        # ✅ 5. เงื่อนไขการตัดสต็อก (Post)
        if auto_post and status == 'POSTED': # ตรวจสอบ status ที่ส่งมาว่าเป็น POSTED หรือไม่ (จาก frontend มักจะส่ง DRAFT มาถ้ายังไม่จบ แต่ถ้ากดจบการขายควรส่ง POSTED หรือ flag อะไรสักอย่าง)
             # *แก้ไข*: โค้ดเดิมใช้ `if auto_post and status != 'HOLD':` ซึ่งโอเคแล้วถ้า logic คือ "ถ้าไม่พักบิล คือจบขาย"
             # แต่ต้องระวัง status เริ่มต้นที่ส่งมา create_sale_transaction ถ้าเป็น DRAFT แต่เราอยาก POST เลย
             # ใน create_sale_transaction รับ status ไปบันทึก
             # ดังนั้นถ้าจะ Post ต้องมั่นใจว่า sale.status ถูกเปลี่ยนเป็น POSTED หรือ service post_sale จะเปลี่ยนให้
             
             # เรียก post_sale เพื่อตัดสต็อกและเปลี่ยนสถานะเป็น POSTED
             post_sale(sale)
        
        return JsonResponse({
            'success': True,
            'sale_id': sale.id,
            'doc_no': sale.doc_no,
            'grand_total': float(sale.grand_total),
            'payment_change': float(payment_change), # ส่งเงินทอนกลับไป Frontend
            'status': sale.status,
            'redirect_url': reverse('print_receipt', kwargs={'sale_id': sale.id})
        })
        
    except ValueError as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)
        
    except Exception as e:
        # ลบบิลทิ้งกรณีเกิด error อื่นๆ หลังสร้างบิลไปแล้วแต่ยังไม่จบ
        # if 'sale' in locals(): sale.delete() 
        return JsonResponse({'success': False, 'error': f'เกิดข้อผิดพลาด: {str(e)}'}, status=500)

# ===================================
# 4. รายละเอียดบิล
# ===================================
@login_required
def sale_detail(request, sale_id):
    """ดูรายละเอียดบิล"""
    sale = get_object_or_404(Sale, id=sale_id)
    items = sale.items.select_related('product', 'product__category')
    
    context = {
        'sale': sale,
        'items': items,
    }
    return render(request, 'products/sales/sale_detail.html', context)


# ===================================
# 5. พิมพ์ใบเสร็จ
# ===================================
@login_required
@xframe_options_exempt
def print_receipt(request, sale_id):
    """พิมพ์ใบเสร็จ"""
    sale = get_object_or_404(Sale, id=sale_id)
    items = sale.items.select_related('product')
    
    # เช็คว่ามี Payment หรือไม่
    payment_method_display = ''
    if hasattr(sale, 'payment') and sale.payment:
        payment_method_map = {
            'cash': '💵 เงินสด',
            'qr': '📱 QR Code',
            'transfer': '🏦 โอนเงิน',
        }
        payment_method_display = payment_method_map.get(sale.payment.method, sale.payment.method)
        
    is_from_report = request.GET.get('source') == 'report'
    
    context = {
        'sale': sale,
        'items': items,
        'payment_method_display': payment_method_display,
        'print_date': datetime.now(),
        'is_from_report': is_from_report,
    }
    return render(request, 'products/sales/receipt.html', context)


# ===================================
# 6. ยกเลิกบิล
# ===================================
@login_required
@require_http_methods(["POST"])
def cancel_sale(request, sale_id):
    """ยกเลิกบิลขาย - คืนสต็อก"""
    try:
        sale = get_object_or_404(Sale, id=sale_id)
        
        # เรียกใช้ Service: ยกเลิกบิล
        service_cancel_sale(sale)
        
        return JsonResponse({'success': True, 'message': 'ยกเลิกบิลสำเร็จ'})
        
    except ValueError as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# ===================================
# 7. รายการบิลขายทั้งหมด
# ===================================
@login_required
def sale_list(request):
    """รายการบิลขายทั้งหมด พร้อมค้นหาและกรอง"""
    
    status = request.GET.get('status', '')
    payment_method = request.GET.get('payment_method', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    search = request.GET.get('search', '')
    
    sales = Sale.objects.select_related('created_by', 'payment')
    
    if status: sales = sales.filter(status=status)
    if payment_method: sales = sales.filter(payment__method=payment_method)
    if date_from: sales = sales.filter(sale_date__date__gte=date_from)
    if date_to: sales = sales.filter(sale_date__date__lte=date_to)
    
    if search:
        sales = sales.filter(
            Q(doc_no__icontains=search) |
            Q(remark__icontains=search)
        )
    
    sales = sales.order_by('-sale_date', '-id')[:100]
    
    summary = Sale.objects.filter(status='POSTED').aggregate(
        total_sales=Sum('grand_total'),
        count=Count('id')
    )
    
    payment_summary = Sale.objects.filter(status='POSTED').values('payment__method').annotate(
        total=Sum('grand_total'),
        count=Count('id')
    ).order_by('-total')
    
    context = {
        'sales': sales,
        'summary': summary,
        'payment_summary': payment_summary,
        'status': status,
        'payment_method': payment_method,
        'date_from': date_from,
        'date_to': date_to,
        'search': search,
    }
    return render(request, 'products/sales/sale_list.html', context)


@login_required
@require_http_methods(["POST"])
def generate_qr_code(request):
    """สร้าง QR Code PromptPay"""
    try:
        from django.conf import settings
        from products.Services.payment_service import generate_promptpay_qr
        
        data = json.loads(request.body)
        amount = data.get('amount')
        reference = data.get('reference', '')
        
        if not amount or float(amount) <= 0:
            return JsonResponse({'success': False, 'error': 'ยอดเงินไม่ถูกต้อง'}, status=400)
        
        PROMPTPAY_NUMBER = getattr(settings, 'PROMPTPAY_PHONE', '0652577703')
        
        qr_image = generate_promptpay_qr(
            phone_number=PROMPTPAY_NUMBER,
            amount=float(amount),
            reference=reference
        )
        
        return JsonResponse({'success': True, 'qr_image': qr_image})
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': f'เกิดข้อผิดพลาด: {str(e)}'}, status=500)
    
@login_required
@require_http_methods(["GET"])
def get_held_bills_api(request):
    """ดึงรายการบิลที่พักไว้ (HOLD) ของผู้ใช้คนนี้"""
    try:
        held_bills = Sale.objects.filter(
            status='HOLD',
            created_by=request.user
        ).order_by('-updated_at')

        data = []
        for bill in held_bills:
            data.append({
                'id': bill.id,
                'doc_no': bill.doc_no,
                'date': bill.created_at.strftime('%H:%M'),
                'remark': bill.remark or '-',
                'total': float(bill.grand_total),
                'items_count': bill.items.count()
            })

        return JsonResponse({'success': True, 'bills': data})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

# ===================================
# 9. API: ดึงข้อมูลบิลกลับมาทำต่อ (Resume)
# ===================================
@login_required
def get_sale_details_api(request, sale_id):
    """ดึงข้อมูลบิลเพื่อเอามาใส่ตะกร้า"""
    try:
        sale = Sale.objects.get(id=sale_id, status='HOLD')
        
        items = []
        for item in sale.items.all():
            items.append({
                'id': item.product.id,
                'sku': item.product.sku,
                'name': item.product.name,
                'price': float(item.unit_price),
                'quantity': float(item.quantity),
                'stock_units': float(item.product.quantity), 
                'has_stock': item.product.quantity > 0,
                'compatible_models': item.product.compatible_models,
                'unit': item.product.unit,
                'original_price': float(item.product.selling_price),
                'wholesale_price': float(item.product.wholesale_price),
                'selling_price': float(item.product.selling_price),
            })
            
        return JsonResponse({
            'success': True,
            'sale': {
                'doc_no': sale.doc_no,
                'discount': float(sale.discount_amount),
                'remark': sale.remark,
                'items': items
            }
        })
    except Sale.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'ไม่พบข้อมูลบิล'}, status=404)
    
# ===================================
# 10. API: ยกเลิกบิลที่พักไว้ (Discard Hold)
# ===================================
@login_required
@require_http_methods(["POST"])
def discard_held_bill(request, sale_id):
    """ยกเลิกบิลที่พักไว้ (เปลี่ยนสถานะเป็น CANCELLED)"""
    try:
        # หาบิลที่เป็น HOLD เท่านั้น (กันพลาดไปลบบิลจริง)
        sale = get_object_or_404(Sale, id=sale_id, status='HOLD')
        
        # เปลี่ยนสถานะเป็นยกเลิก
        sale.status = 'CANCELLED'
        sale.save(update_fields=['status'])
        
        return JsonResponse({'success': True, 'message': 'ยกเลิกรายการพักบิลแล้ว'})
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)