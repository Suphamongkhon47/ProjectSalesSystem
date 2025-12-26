"""
Views: Return (รับคืนสินค้า)
รองรับ: ค้นหาบิล, เลือกสินค้าคืน, บันทึกเหตุผล, คืนเงิน
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.db.models import Q, Sum, Count, F
from django.views.decorators.http import require_http_methods
from decimal import Decimal
from datetime import datetime, timedelta
import json
from django.core.paginator import Paginator

from products.Services.payment_service import PaymentService
from products.models import Sale, SaleItem, Product, Supplier # เพิ่ม model ที่ต้องใช้
from products.Services.return_service import (
    create_return_transaction,
    post_return,
    validate_return_eligibility,
    cancel_return as service_cancel_return # import เพิ่ม
)


# ===================================
# 1. หน้าหลักรับคืนสินค้า
# ===================================
@login_required
def returns(request):
    """หน้ารับคืนสินค้าหลัก"""
    
    today = datetime.now()
    doc_prefix = f"RET-{today.strftime('%Y%m%d')}"
    
    # นับบิลรับคืนวันนี้
    today_returns_count = Sale.objects.filter(
        doc_no__startswith=doc_prefix,
        doc_type='RETURN'
    ).count()
    
    next_number = str(today_returns_count + 1).zfill(4)
    doc_no = f"{doc_prefix}-{next_number}"
    
    context = {
        'doc_no': doc_no,
        'today': today,
    }
    
    return render(request, 'products/returns/return_product.html', context)


# ===================================
# 2. ค้นหาบิลเดิม (AJAX) - Smart Search
# ===================================
@login_required
@require_http_methods(["GET"])
def search_sale_for_return(request):
    """
    ค้นหาบิลเดิมสำหรับรับคืน
    รองรับ: เลขบิล, เบอร์โทร, ทะเบียนรถ
    """
    
    query = request.GET.get('q', '').strip()
    
    if len(query) < 3:
        return JsonResponse({
            'success': False,
            'error': 'กรุณากรอกอย่างน้อย 3 ตัวอักษร'
        }, status=400)
    
    try:
        # Priority 1: ค้นหาเลขบิล (SALE-xxx)
        sale = Sale.objects.filter(
            doc_no__icontains=query,
            doc_type='SALE',
            status='POSTED'
        ).select_related('created_by', 'payment').first()
        
        # Priority 2: ค้นหาเบอร์โทร (ถ้ามี customer_phone field)
        # if not sale and hasattr(Sale, 'customer_phone'):
        #     sale = Sale.objects.filter(
        #         customer_phone=query,
        #         doc_type='SALE',
        #         status='POSTED'
        #     ).select_related('created_by', 'payment').order_by('-sale_date').first()
        
        # Priority 3: ค้นหาทะเบียนรถ (ถ้ามี car_plate field)
        # if not sale and hasattr(Sale, 'car_plate'):
        #     sale = Sale.objects.filter(
        #         car_plate__icontains=query,
        #         doc_type='SALE',
        #         status='POSTED'
        #     ).select_related('created_by', 'payment').order_by('-sale_date').first()
        
        if not sale:
            return JsonResponse({
                'success': False,
                'error': 'ไม่พบบิลที่ค้นหา'
            }, status=404)
        
        # ✅ Validate: ตรวจสอบความพร้อมในการคืน
        try:
            validate_return_eligibility(sale)
        except ValueError as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=400)
        
        # ดึงรายการสินค้า
        items = sale.items.select_related('product', 'product__category').all()
        
        # คำนวณจำนวนที่คืนไปแล้ว
        returned_items = {}
        returns = Sale.objects.filter(
            doc_type='RETURN',
            ref_doc_no=sale.doc_no,
            status='POSTED'
        )
        
        for ret in returns:
            for ret_item in ret.items.all():
                product_id = ret_item.product_id
                returned_items[product_id] = returned_items.get(product_id, 0) + ret_item.quantity
        
        # สร้าง JSON รายการสินค้า
        items_data = []
        for item in items:
            # จำนวนที่คืนไปแล้ว
            already_returned = returned_items.get(item.product_id, 0)
            # จำนวนที่เหลือให้คืนได้
            remaining = item.quantity - already_returned
            
            if remaining > 0:
                items_data.append({
                    'id': item.id,
                    'product_id': item.product.id,
                    'sku': item.product.sku,
                    'name': item.product.name,
                    'category': item.product.category.name if item.product.category else '-',
                    'compatible_models': item.product.compatible_models or '',
                    'unit': item.product.unit,
                    'original_quantity': float(item.quantity),
                    'already_returned': float(already_returned),
                    'remaining_quantity': float(remaining),
                    'unit_price': float(item.unit_price),
                    'cost_price': float(item.cost_price),
                })
        
        # ข้อมูลบิล
        sale_data = {
            'id': sale.id,
            'doc_no': sale.doc_no,
            'sale_date': sale.sale_date.strftime('%d/%m/%Y %H:%M'),
            'total_amount': float(sale.total_amount),
            'discount_amount': float(sale.discount_amount),
            'grand_total': float(sale.grand_total),
            'created_by': sale.created_by.get_full_name() or sale.created_by.username,
            'payment_method': sale.payment.method if hasattr(sale, 'payment') else None,
            'items': items_data,
            'items_count': len(items_data),
        }
        
        return JsonResponse({
            'success': True,
            'sale': sale_data
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'เกิดข้อผิดพลาด: {str(e)}'
        }, status=500)


# ===================================
# 3. บันทึกบิลรับคืน (AJAX)
# ===================================
@login_required
@require_http_methods(["POST"])
def create_return(request):
    """
    บันทึกบิลรับคืนสินค้า
    
    รับข้อมูล:
    - doc_no: เลขที่บิลรับคืน
    - ref_doc_no: เลขที่บิลเดิม
    - items: รายการสินค้าที่คืน [{product_id, quantity}, ...]
    - return_reason: เหตุผล
    - return_note: หมายเหตุ
    - refund_method: วิธีคืนเงิน
    - discount_return: ส่วนลดที่คืน
    """
    
    try:
        data = json.loads(request.body)
        
        doc_no = data.get('doc_no')
        ref_doc_no = data.get('ref_doc_no')
        items = data.get('items', [])
        
        # ข้อมูลเหตุผล
        return_reason = data.get('return_reason', 'other')
        return_note = data.get('return_note', '')
        
        # ข้อมูลการคืนเงิน
        refund_method = data.get('refund_method', 'cash')
        refund_bank = data.get('refund_bank', '')
        refund_account = data.get('refund_account', '')
        refund_name = data.get('refund_name', '')
        
        # ส่วนลด
        discount_return = Decimal(str(data.get('discount_return', 0)))
        
        # Validate
        if not ref_doc_no:
            return JsonResponse({'success': False, 'error': 'ไม่พบเลขที่บิลเดิม'}, status=400)
        
        if not items:
            return JsonResponse({'success': False, 'error': 'ไม่มีรายการสินค้าที่คืน'}, status=400)
        
        # ✅ เช็คเลขที่ซ้ำ (ถ้าระบบไม่ได้ Auto Gen ให้ใหม่ใน JS)
        if Sale.objects.filter(doc_no=doc_no).exists():
             # สร้างเลขใหม่ถ้าซ้ำ
             today_str = datetime.now().strftime('%Y%m%d')
             prefix = f"RET-{today_str}"
             last = Sale.objects.filter(doc_no__startswith=prefix).count()
             doc_no = f"{prefix}-{str(last + 1).zfill(4)}"
        
        # ✅ ค้นหาบิลเดิม
        original_sale = get_object_or_404(
            Sale,
            doc_no=ref_doc_no,
            doc_type='SALE',
            status='POSTED'
        )
        
        # ✅ Validate: ความพร้อมในการคืน
        validate_return_eligibility(original_sale)
        
        # ✅ เรียก Service: สร้าง Return Transaction
        return_sale = create_return_transaction(
            user=request.user,
            ref_doc_no=ref_doc_no,
            items_data=items,
            return_reason=return_reason,
            return_note=return_note,
            discount_amount=discount_return,
            doc_no=doc_no
        )
        
        # ✅ เรียก Service: สร้าง Payment (คืนเงิน)
        # ยอดคืนเป็นลบ (เพราะคืนเงิน)
        refund_amount = -abs(return_sale.grand_total)
        
        PaymentService.create_payment(
            sale=return_sale,
            method=refund_method,
            received=refund_amount,
            note=f"คืนเงิน: {return_reason}\n{return_note}"
        )
        
        # ✅ ถ้าโอนเงิน บันทึกข้อมูลบัญชี
        if refund_method == 'transfer' and hasattr(return_sale.payment, 'refund_bank'):
            return_sale.payment.refund_bank = refund_bank
            return_sale.payment.refund_account = refund_account
            return_sale.payment.refund_name = refund_name
            return_sale.payment.save()
        
        # ✅ เรียก Service: ยืนยันบิลรับคืน (คืนสต็อก)
        post_return(return_sale)
        
        return JsonResponse({
            'success': True,
            'sale_id': return_sale.id,
            'doc_no': return_sale.doc_no,
            'grand_total': float(return_sale.grand_total),
            'status': return_sale.status,
            'redirect_url': f'/sales/{return_sale.id}/print/?source=return'
        })
        
    except ValueError as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': f'เกิดข้อผิดพลาด: {str(e)}'}, status=500)

# ===================================
# 6. ยกเลิกบิลรับคืน (ไม่แนะนำ!)
# ===================================
@login_required
@require_http_methods(["POST"])
def cancel_return(request, return_id):
    """
    ยกเลิกบิลรับคืน (ไม่แนะนำให้ใช้!)
    """
    
    try:
        return_sale = get_object_or_404(
            Sale,
            id=return_id,
            doc_type='RETURN'
        )
        
        if return_sale.status == 'CANCELLED':
            return JsonResponse({
                'success': True,
                'message': 'บิลนี้ถูกยกเลิกแล้ว'
            })
        
        if return_sale.status != 'POSTED':
            return JsonResponse({
                'success': False,
                'error': 'สามารถยกเลิกได้เฉพาะบิลที่ยืนยันแล้ว'
            }, status=400)
        
        # ⚠️ ยกเลิกบิลรับคืน = ตัดสต็อกอีกครั้ง
        service_cancel_return(return_sale)
        
        return JsonResponse({
            'success': True,
            'message': 'ยกเลิกบิลรับคืนสำเร็จ'
        })
        
    except ValueError as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'เกิดข้อผิดพลาด: {str(e)}'
        }, status=500)


