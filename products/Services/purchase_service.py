"""
products/Services/purchase_service.py
Service สำหรับจัดการการรับสินค้าเข้า
"""

from django.db import transaction
from decimal import Decimal
from products.models import Purchase,StockMovement, purchase


def post_purchase(purchase):
    """
    ยืนยันการรับสินค้าเข้า (DRAFT → POSTED)
    
    ทำงาน:
    1. เช็คว่าเอกสารเป็น DRAFT และมีรายการสินค้า
    2. เพิ่มสต็อกเข้า Inventory
    3. บันทึก StockMovement (ประวัติการเคลื่อนไหว)
    4. อัปเดตราคาทุนใน Product
    5. เปลี่ยนสถานะเป็น POSTED
    
    Args:
        purchase: Purchase object
        
    Returns:
        bool: True ถ้าสำเร็จ, False ถ้าล้มเหลว
    """
    
    # 🔍 เช็คเงื่อนไข
    if purchase.status != 'DRAFT':
        return False
    
    if not purchase.items.exists():
        return False
    
    try:
        with transaction.atomic():
            grand_total = Decimal('0')
            
            for item in purchase.items.all():
                product = item.product
                qty = item.quantity
                cost = item.unit_cost
                
                line_total = qty * cost
                grand_total += line_total
                
                # 1️⃣ [แก้ใหม่] อัปเดต Product โดยตรง
                # บวกของใหม่เข้าไปในของเดิม
                product.quantity = (product.quantity or Decimal('0')) + qty
                product.cost_price = cost  # อัปเดตทุนล่าสุด
                product.save()
                
                # 2️⃣ บันทึก StockMovement
                StockMovement.objects.create(
                    product=product,
                    movement_type='IN',
                    quantity=qty,
                    cost=cost,
                    balance_after=product.quantity, # ✅ ใช้ยอดคงเหลือจาก Product ได้เลย
                    reference=purchase.doc_no
                )
            
            # 3️⃣ จบงาน (อัปเดตสถานะบิล)
            purchase.grand_total = grand_total
            purchase.status = 'POSTED'
            purchase.save()
            
            return True
            
    except Exception as e:
        return False