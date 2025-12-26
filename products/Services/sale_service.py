"""
Sale Service: Business Logic สำหรับการขาย

แยก Logic ออกจาก Views และ Models เพื่อ:
- ง่ายต่อการทดสอบ (Testing)
- ง่ายต่อการนำกลับมาใช้ (Reusable)
- ง่ายต่อการบำรุงรักษา (Maintainable)
"""
from django.utils import timezone
from django.db import transaction
from decimal import Decimal
from products.models import (
    Sale, SaleItem,Product, StockMovement
)
from products.Services.payment_service import PaymentService

# ===================================
# 1. สร้างบิลขาย (Transaction) - แก้ไขรองรับ Return
# ===================================
def create_sale_transaction(user, items_data, price_type='retail', discount_amount=0, remark='', doc_no=None, doc_type='SALE', ref_doc_no='', status='DRAFT', sale_id=None):
    """
    สร้างบิลขายหรือบิลคืน พร้อมรายการสินค้า
    ✅ เพิ่ม parameter: doc_type, ref_doc_no, status, sale_id
    """
    
    if not items_data:
        raise ValueError("ไม่มีรายการสินค้า")
    
    try:
        with transaction.atomic():
            
            # ----------------------------------------------------
            # 1. สร้างหรือแก้ไขหัวบิล (Sale Header)
            # ----------------------------------------------------
            if sale_id:
                # กรณีแก้ไขบิลเดิม (เช่น ดึงบิลพักมาทำต่อ)
                try:
                    sale = Sale.objects.get(id=sale_id)
                    # ลบรายการสินค้าเก่าทิ้งก่อน (เดี๋ยวบันทึกใหม่จากตะกร้า)
                    sale.items.all().delete()
                    
                    # อัปเดตข้อมูล
                    sale.doc_type = doc_type
                    sale.ref_doc_no = ref_doc_no
                    sale.status = status
                    sale.discount_amount = Decimal(str(discount_amount))
                    sale.remark = remark
                    sale.save()
                    
                except Sale.DoesNotExist:
                    raise ValueError("ไม่พบข้อมูลบิลที่ต้องการแก้ไข")
            else:
                # กรณีสร้างใหม่
                sale = Sale.objects.create(
                    doc_no=doc_no,
                    doc_type=doc_type,       # ✅ บันทึกประเภท (SALE/RETURN)
                    ref_doc_no=ref_doc_no,   # ✅ บันทึกอ้างอิง
                    status=status,           # ✅ บันทึกสถานะ (DRAFT/HOLD)
                    discount_amount=Decimal(str(discount_amount)),
                    remark=remark,
                    created_by=user,
                )
            
            # ----------------------------------------------------
            # 2. เพิ่มรายการสินค้า (Sale Items)
            # ----------------------------------------------------
            for item_data in items_data:
                
                # ดึงสินค้า
                try:
                    product = Product.objects.select_related('category').get(
                        id=item_data['product_id'],
                        is_active=True
                    )
                except Product.DoesNotExist:
                    raise ValueError(f"ไม่พบสินค้า ID {item_data['product_id']}")
                
                # แปลงจำนวน
                quantity = Decimal(str(item_data['quantity']))
                
                if quantity <= 0:
                    raise ValueError(f"จำนวนสินค้า {product.name} ไม่ถูกต้อง")
                
                # กำหนดราคา
                if 'custom_price' in item_data and item_data['custom_price'] is not None:
                    unit_price = Decimal(str(item_data['custom_price']))
                else:
                    unit_price = product.wholesale_price if price_type == 'wholesale' else product.selling_price
                
                # ----------------------------------------------------
                # ✅ Logic เช็คสต็อก (สำคัญ!)
                # ----------------------------------------------------
                # เช็คเฉพาะตอน "ขาย (SALE)" เท่านั้น
                # ถ้าเป็น "คืน (RETURN)" ไม่ต้องเช็ค เพราะเรากำลังเอาของมาคืนใส่สต็อก
                if doc_type == 'SALE':
                    current_stock = product.quantity or 0
                    if current_stock < quantity:
                        raise ValueError(
                            f"สินค้า {product.name} มีสต็อกไม่พอ\n"
                            f"ต้องการ: {quantity} {product.unit}\n"
                            f"เหลือ: {current_stock} {product.unit}"
                        )
                
                # บันทึกรายการ
                SaleItem.objects.create(
                    sale=sale,
                    product=product,
                    quantity=quantity,
                    unit_price=unit_price,
                    cost_price=product.cost_price,
                )
            
            # คำนวณยอดรวมสุทธิอัปเดตกลับไปที่หัวบิล
            sale.calculate_totals()
            
            return sale
            
    except Exception as e:
        raise ValueError(f"เกิดข้อผิดพลาด: {str(e)}")


# ===================================
# 2. ยืนยันบิลขาย (ตัดสต็อก)
# ===================================
def post_sale(sale):
    """
    ยืนยันบิลขาย → ตัดสต็อก
    
    Args:
        sale: Sale object
    
    Returns:
        True
    """
    
    if sale.status == 'POSTED':
        return True
    
    if sale.status == 'CANCELLED':
        raise ValueError("ไม่สามารถยืนยันบิลที่ยกเลิกแล้ว")
    
    try:
        with transaction.atomic():
            
            # ✅ ตัดสต็อก (ง่ายขึ้น!)
            for item in sale.items.select_related('product').all():
                
                # ดึง Inventory (Lock Row)
                product = Product.objects.select_for_update().get(id=item.product.id)
                
                # ✅ Validate สต็อก
                if product.quantity < item.quantity:
                    raise ValueError(
                        f"สินค้า {item.product.name} มีสต็อกไม่พอ\n"
                        f"ต้องการ: {item.quantity} {item.product.unit}\n"
                        f"เหลือ: {product.quantity} {item.product.unit}"
                    )
                
                # ✅ ตัดสต็อก (ใช้ quantity ตรงๆ)
                product.quantity -= item.quantity
                product.save(update_fields=['quantity'])
                
                # บันทึก Stock Movement
                StockMovement.objects.create(
                    product=item.product,
                    movement_type='OUT',
                    quantity=item.quantity,
                    cost=item.cost_price,
                    balance_after=product.quantity,
                    reference=sale.doc_no,
                )
            
            # เปลี่ยนสถานะ
            sale.status = 'POSTED'
            sale.sale_date = timezone.now()
            sale.save(update_fields=['status', 'sale_date'])
            
            return True
            
    except Exception as e:
        raise ValueError(f"ไม่สามารถยืนยันบิลได้: {str(e)}")


# ===================================
# 3. ยกเลิกบิลขาย (คืนสต็อก)
# ===================================
def cancel_sale(sale):
    """
    ยกเลิกบิลขาย → คืนสต็อก
    
    Args:
        sale: Sale object
    
    Returns:
        True
    """
    
    if sale.status == 'CANCELLED':
        return True
    
    if sale.status != 'POSTED':
        raise ValueError("สามารถยกเลิกได้เฉพาะบิลที่ยืนยันแล้วเท่านั้น")
    
    try:
        with transaction.atomic():
            
            # ✅ คืนสต็อก
            for item in sale.items.all():
                
                # ดึง Inventory (Lock Row)
                product = Product.objects.select_for_update().get(id=item.product.id)
                
                # ✅ คืนสต็อก (ใช้ quantity ตรงๆ)
                product.quantity += item.quantity
                product.save(update_fields=['quantity'])
                
                # บันทึก Stock Movement
                StockMovement.objects.create(
                    product=item.product,
                    movement_type='IN',
                    quantity=item.quantity,
                    cost=item.cost_price,
                    balance_after=product.quantity,
                    reference=f'CANCEL-{sale.doc_no}',
                )
            
            # เปลี่ยนสถานะ
            sale.status = 'CANCELLED'
            sale.save(update_fields=['status'])
            
            # ยกเลิก Payment
            if hasattr(sale, 'payment'):
                sale.payment.status = 'void'
                sale.payment.save(update_fields=['status'])
            
            return True
            
    except Exception as e:
        raise ValueError(f"ไม่สามารถยกเลิกบิลได้: {str(e)}")



# ===================================
# 5. ฟังก์ชันเสริม
# ===================================
def get_sale_summary(sale):
    """
    สรุปข้อมูลบิลขาย
    
    Args:
        sale: Sale object
    
    Returns:
        dict: สรุปข้อมูล
    """
    
    items = sale.items.select_related('product').all()
    
    total_items = items.count()
    total_quantity = sum(item.quantity for item in items)
    total_cost = sum(item.cost_price * item.quantity for item in items)
    
    profit = sale.grand_total - total_cost
    
    return {
        'doc_no': sale.doc_no,
        'sale_date': sale.sale_date,
        'status': sale.get_status_display(),
        'total_items': total_items,
        'total_quantity': float(total_quantity),
        'total_amount': float(sale.total_amount),
        'discount_amount': float(sale.discount_amount),
        'grand_total': float(sale.grand_total),
        'total_cost': float(total_cost),
        'profit': float(profit),
        'profit_margin': float((profit / sale.grand_total * 100) if sale.grand_total > 0 else 0),
    }

# ===================================
# 4. สร้างการชำระเงิน (ใช้ PaymentService)
# ===================================
def create_payment(sale, method='cash', received=None, note=''):
    """
    สร้างการชำระเงิน
    
    Args:
        sale: Sale object
        method: 'cash', 'qr', 'transfer'
        received: เงินที่รับ (สำหรับเงินสด)
        note: หมายเหตุ
    
    Returns:
        Payment object
    """
    # ✅ ใช้ PaymentService แทน
    return PaymentService.create_payment(
        sale=sale,
        method=method,
        received=received,
        note=note
    )


def validate_sale_items(items_data):
    """
    ตรวจสอบรายการสินค้าก่อนสร้างบิล
    
    Args:
        items_data: list of dict
    
    Returns:
        tuple: (is_valid, errors)
    """
    
    errors = []
    
    if not items_data:
        errors.append("ไม่มีรายการสินค้า")
        return False, errors
    
    for i, item in enumerate(items_data):
        
        # ตรวจสอบ product_id
        if 'product_id' not in item:
            errors.append(f"รายการที่ {i+1}: ไม่มี product_id")
            continue
        
        # ตรวจสอบว่ามีสินค้าหรือไม่
        try:
            product = Product.objects.get(id=item['product_id'], is_active=True)
        except Product.DoesNotExist:
            errors.append(f"รายการที่ {i+1}: ไม่พบสินค้า ID {item['product_id']}")
            continue
        
        # ตรวจสอบจำนวน
        if 'quantity' not in item or float(item['quantity']) <= 0:
            errors.append(f"รายการที่ {i+1} ({product.name}): จำนวนไม่ถูกต้อง")
        
        # ตรวจสอบราคา
        if 'custom_price' in item:
            try:
                price = Decimal(str(item['custom_price']))
                if price < 0:
                    errors.append(f"รายการที่ {i+1} ({product.name}): ราคาต้องไม่ติดลบ")
            except:
                errors.append(f"รายการที่ {i+1} ({product.name}): ราคาไม่ถูกต้อง")
    
    return len(errors) == 0, errors