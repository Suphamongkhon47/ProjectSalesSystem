from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from decimal import Decimal
from datetime import datetime
import json
from django.urls import reverse
from django.views.decorators.clickjacking import xframe_options_exempt
# Models
from products.models import Product, Transaction, SystemSetting
from products.Services.product_service import ProductService
# Services
from products.Services.payment_service import PaymentService
from django.conf import settings
from products.Services.payment_service import generate_promptpay_qr
from products.Services.sale_service import (
    create_sale_transaction, 
    post_sale, 
    cancel_sale as service_cancel_sale,
)


# ===================================
# 1. หน้าหลักขาย (POS)
# ===================================
@login_required
def sales(request):
    """หน้าขายสินค้าหลัก"""
    today = datetime.now()
    doc_prefix = f"SALE-{today.strftime('%Y%m%d')}"
    
    # ✅ แก้ไข Logic 1: หาเลขท้ายสุด + 1 (ปลอดภัยกว่าการนับ count)
    last_sale = Transaction.objects.filter(
        doc_no__startswith=doc_prefix, 
        doc_type='SALE'
    ).order_by('doc_no').last()

    if last_sale:
        try:
            # ตัดเอา 4 ตัวท้ายมาบวก 1
            last_run_no = int(last_sale.doc_no.split('-')[-1])
            next_number = str(last_run_no + 1).zfill(4)
        except ValueError:
            next_number = '0001'
    else:
        next_number = '0001'

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
        stock_status = ProductService.get_stock_status(p)
        stock_qty = stock_status['quantity']
        
        match_type = 'sku'
        if p in exact_sku: match_type = 'exact_sku'
        elif p in name_products: match_type = 'name'
        elif p in car_products: match_type = 'car'
        
        # หาสินค้าคู่/ชุด (ถ้ามี)
        pair_products = []
        if p.bundle_group:
            siblings = Product.objects.filter(
                bundle_group=p.bundle_group,
                is_active=True
            ).exclude(id=p.id).values('id', 'sku', 'name', 'quantity', 'selling_price')
            pair_products = list(siblings)
        
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
            'bundle_type': p.bundle_type,
            'bundle_group': p.bundle_group,
            'has_pair': len(pair_products) > 0,
            'pair_products': pair_products,
        })

    return JsonResponse({
        'products': results,
        'count': len(results)
    })

# ===================================
# 2.1 หาสินค้าคู่/ชุด (AJAX)
# ===================================
@login_required
@require_http_methods(["GET"])
def get_pair_products(request):
    product_id = request.GET.get('product_id')
    
    if not product_id:
        return JsonResponse({'success': False, 'error': 'Missing product_id'}, status=400)
    
    try:
        product = Product.objects.get(id=product_id, is_active=True)
    except Product.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Product not found'}, status=404)
    
    if not product.bundle_group:
        return JsonResponse({'success': True, 'has_pair': False, 'pairs': []})
    
    pairs = Product.objects.filter(
        bundle_group=product.bundle_group,
        is_active=True
    ).exclude(id=product.id).values(
        'id', 'sku', 'name', 'selling_price', 
        'wholesale_price', 'quantity', 'unit'
    )
    
    pairs_list = list(pairs)
    
    return JsonResponse({
        'success': True,
        'has_pair': len(pairs_list) > 0,
        'bundle_group': product.bundle_group,
        'bundle_type': product.bundle_type,
        'pairs': pairs_list
    })
    
# ===================================
# 3. บันทึกบิลขาย (AJAX)
# ===================================
@login_required
@require_http_methods(["POST"])
def create_sale(request):
    try:
        data = json.loads(request.body)
        sale_id = data.get('sale_id')
        doc_no = data.get('doc_no')
        items = data.get('items', [])
        
        # Payment Info
        price_type = data.get('price_type', 'retail')
        payment_method = data.get('payment_method', 'cash')
        
        try:
            payment_received = Decimal(str(data.get('payment_received', 0) or 0))
        except:
            payment_received = Decimal('0.00')

        try:
            discount_amount = Decimal(str(data.get('discount_amount', 0) or 0))
        except:
            discount_amount = Decimal('0.00')
            
        remark = data.get('remark', '')
        auto_post = data.get('auto_post', True)
        status = data.get('status', 'DRAFT') 
        
        if not items:
            return JsonResponse({'success': False, 'error': 'ไม่มีรายการสินค้า'}, status=400)
        
        # ✅ Auto-Fix เลขที่บิลซ้ำ (กันตาย)
        if doc_no and not sale_id and Transaction.objects.filter(doc_no=doc_no).exists():
            today = datetime.now()
            doc_prefix = f"SALE-{today.strftime('%Y%m%d')}"
            last_sale = Transaction.objects.filter(doc_no__startswith=doc_prefix).order_by('doc_no').last()
            if last_sale:
                try:
                    new_run_no = int(last_sale.doc_no.split('-')[-1]) + 1
                    doc_no = f"{doc_prefix}-{str(new_run_no).zfill(4)}"
                except:
                    import uuid
                    doc_no = f"{doc_prefix}-{str(uuid.uuid4())[:4]}"
            else:
                doc_no = f"{doc_prefix}-0001"
        
        # สร้างบิล (เรียก SaleService)
        sale = create_sale_transaction(
            user=request.user,
            sale_id=sale_id,
            items_data=items,
            price_type=price_type,
            discount_amount=discount_amount,
            remark=remark,
            doc_no=doc_no,
            doc_type='SALE',
            status='DRAFT' 
        )
        
        payment_change = Decimal('0.00')
        
        # ✅ เช็คเงินก่อน (ก่อนตัดสต็อก)
        if status != 'HOLD' and auto_post:
            if payment_method == 'cash':
                if payment_received < sale.grand_total:
                    sale.delete()
                    return JsonResponse({
                        'success': False,
                        'error': f'ยอดเงินที่รับมาไม่เพียงพอ (ขาด {sale.grand_total - payment_received:,.2f} บาท)'
                    }, status=400)
                payment_change = payment_received - sale.grand_total
            else:
                payment_received = sale.grand_total
            
            # ✅ เงินพอแล้ว → ค่อยตัดสต็อก
            post_sale(sale)
        
        # บันทึก Payment
        payment_note = f"เงินทอน: {payment_change:,.2f}" if payment_method == 'cash' and status != 'HOLD' else ""
        
        PaymentService.create_payment(
            sale=sale,
            method=payment_method,
            received=payment_received,
            note=payment_note
        )
        
        return JsonResponse({
            'success': True,
            'sale_id': sale.id,
            'doc_no': sale.doc_no,
            'grand_total': float(sale.grand_total),
            'payment_change': float(payment_change),
            'status': sale.status,
            'redirect_url': reverse('print_receipt', kwargs={'sale_id': sale.id})
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': f'เกิดข้อผิดพลาด: {str(e)}'}, status=500)


# ===================================
# 5. พิมพ์ใบเสร็จ
# ===================================
@login_required
@xframe_options_exempt
def print_receipt(request, sale_id):

    
    sale = get_object_or_404(Transaction, id=sale_id, doc_type='SALE')
    items = sale.items.select_related('product')
    
    payment_method_display = ''
    if hasattr(sale, 'payment') and sale.payment:
        payment_method_map = {
            'cash': '💵 เงินสด',
            'qr': '📱 QR Code',
            'transfer': '🏦 โอนเงิน',
        }
        payment_method_display = payment_method_map.get(sale.payment.method, sale.payment.method)
    
    # ✅ ดึง settings
    settings = SystemSetting.get_all()
    
    is_from_report = request.GET.get('source') == 'report'
    
    context = {
        'sale': sale,
        'items': items,
        'payment_method_display': payment_method_display,
        'print_date': datetime.now(),
        'is_from_report': is_from_report,
        'settings': settings,  # ✅ ส่ง settings ไปให้ template
    }
    return render(request, 'products/sales/receipt.html', context)


@login_required
@require_http_methods(["POST"])
def generate_qr_code(request):
    try:
     
        data = json.loads(request.body)
        amount = data.get('amount')
        reference = data.get('reference', '')
        
        if not amount or float(amount) <= 0:
            return JsonResponse({'success': False, 'error': 'ยอดเงินไม่ถูกต้อง'}, status=400)
        
        # ✅ แก้ไข: ใช้เบอร์เดียวกันกับ payment_service.py
        PROMPTPAY_NUMBER = getattr(settings, 'PROMPTPAY_PHONE', '0834755649')
        
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
    try:
        held_bills = Transaction.objects.filter(
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

@login_required
def get_sale_details_api(request, sale_id):
    try:
        sale = Transaction.objects.get(id=sale_id, status='HOLD', doc_type='SALE')
        stock_status = ProductService.get_stock_status(item.product)
        items = []
        for item in sale.items.all():
            items.append({
                'id': item.product.id,
                'sku': item.product.sku,
                'name': item.product.name,
                'price': float(item.unit_price),
                'quantity': float(item.quantity),
                'stock_units': float(stock_status['quantity']), 
                'has_stock': stock_status['quantity'] > 0,
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
    except Transaction.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'ไม่พบข้อมูลบิล'}, status=404)
    
@login_required
@require_http_methods(["POST"])
def discard_held_bill(request, sale_id):
    try:
        sale = get_object_or_404(Transaction, id=sale_id, status='HOLD', doc_type='SALE')
        sale.status = 'CANCELLED'
        sale.save(update_fields=['status'])
        return JsonResponse({'success': True, 'message': 'ยกเลิกรายการพักบิลแล้ว'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# ===================================
# 6. ยกเลิกบิล
# ===================================
@login_required
@require_http_methods(["POST"])
def cancel_sale(request, sale_id):
    try:
        sale = get_object_or_404(Transaction, id=sale_id, doc_type='SALE')
        service_cancel_sale(sale)
        return JsonResponse({'success': True, 'message': 'ยกเลิกบิลสำเร็จ'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
    
@login_required
@require_http_methods(["GET"])
def product_detail_api(request, product_id):
    try:
        product = Product.objects.get(id=product_id, is_active=True)
        stock_status = ProductService.get_stock_status(product)
        has_pair = False
        if product.bundle_group:
             has_pair = Product.objects.filter(
                bundle_group=product.bundle_group,
                is_active=True
            ).exclude(id=product.id).exists()
        return JsonResponse({
            'success': True,
            'id': product.id,
            'sku': product.sku,
            'name': product.name,
            'category': product.category.name if product.category else '-',
            'compatible_models': product.compatible_models or '',
            'unit': product.unit,
            'selling_price': float(product.selling_price),
            'wholesale_price': float(product.wholesale_price),
            'cost_price': float(product.cost_price),
            'stock_units': float(stock_status['quantity']),
            'has_stock': stock_status['quantity'] > 0,
            'bundle_type': product.bundle_type,
            'bundle_group': product.bundle_group,
            'has_pair': has_pair,
        })
    except Product.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'ไม่พบสินค้า'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)