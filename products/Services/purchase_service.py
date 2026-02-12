"""
products/Services/purchase_service.py
ฉบับแก้ไข: 
1. ระบุชื่อคนนำเข้าใน Note (เพื่อให้รายงานแยกคนได้)
2. หารต้นทุนสินค้าชุดถูกต้อง (ไม่เบิ้ลราคา)
"""
from django.db import transaction
from decimal import Decimal
from products.models import Purchase, StockMovement, Product

def post_purchase(purchase_obj, user=None):
    """
    อนุมัติใบรับสินค้า (Approved/Posted)
    """
    # 1. ป้องกันการกดซ้ำ
    if purchase_obj.status == 'POSTED':
        return True
    
    try:
        with transaction.atomic():
            # ✅ ดึงชื่อคนทำรายการ (ถ้าไม่มีให้ใช้ System)
            importer_name = purchase_obj.created_by.username if purchase_obj.created_by else "System"

            for item in purchase_obj.items.all():
                product = item.product
                
                # 1. คำนวณจำนวนสต็อกจริง (Convert Unit)
                qty_bought = item.quantity
                multiplier = max(1, int(product.items_per_purchase_unit or 1))
                stock_qty_to_add = qty_bought * multiplier
                
                # คำนวณต้นทุนต่อหน่วยสต็อก (Per Unit/Set)
                unit_cost_stock = 0
                if stock_qty_to_add > 0:
                    unit_cost_stock = item.line_total / stock_qty_to_add

                # ====================================================
                # 📦 2. กรณีสินค้าชุด (Bundle) -> กระจายเข้าลูก
                # ====================================================
                if product.is_bundle:
                    # 1. สร้าง StockMovement ให้ "ตัวแม่" (เพื่อโชว์ประวัติ)
                    # หมายเหตุ: balance_after ใส่ 0 หรือค่าสมมติ เพราะแม่ไม่มีสต็อกจริง
                    StockMovement.objects.create(
                        product=product,
                        movement_type='IN',
                        quantity=stock_qty_to_add,     # จำนวนชุด (เช่น +10)
                        unit_cost=unit_cost_stock,     # ต้นทุนต่อชุด (เช่น 1500)
                        balance_after=0,               # แม่ไม่มีสต็อกจริง ให้เป็น 0
                        reference=purchase_obj.doc_no,
                        note=f"Import Bundle Set (โดย {importer_name})"
                    )

                    # 2. จัดการลูกๆ (เหมือนเดิม)
                    children = product.bundle_components.all()
                    if children.exists():
                        child_count = children.count()
                        child_unit_cost = unit_cost_stock / child_count if child_count > 0 else 0

                        for child in children:
                            # ... (Logic คำนวณ Weighted Average ของลูก เหมือนเดิม) ...
                            old_qty = Decimal(str(child.quantity or 0))
                            old_cost = Decimal(str(child.cost_price or 0))
                            new_qty = Decimal(str(stock_qty_to_add)) # ลูกเพิ่มเท่าแม่ (1:1)

                            total_qty = old_qty + new_qty
                            if total_qty > 0 and child_unit_cost > 0:
                                child.cost_price = (old_qty * old_cost + new_qty * child_unit_cost) / total_qty

                            child.quantity = total_qty
                            child.save(update_fields=['quantity', 'cost_price'])
                            
                            StockMovement.objects.create(
                                product=child,
                                movement_type='IN',
                                quantity=stock_qty_to_add,
                                unit_cost=child_unit_cost,
                                balance_after=child.quantity,
                                reference=purchase_obj.doc_no,
                                note=f"Component of {product.sku} (โดย {importer_name})"
                            )
                # ====================================================
                # 📦 3. กรณีสินค้าปกติ -> เข้าตัวมันเอง
                # ====================================================
                else:
                    old_qty = Decimal(str(product.quantity or 0))
                    old_cost = Decimal(str(product.cost_price or 0))
                    new_qty = Decimal(str(stock_qty_to_add))

                    # ⭐ Weighted Average Cost
                    total_qty = old_qty + new_qty
                    if total_qty > 0 and unit_cost_stock > 0:
                        product.cost_price = (old_qty * old_cost + new_qty * unit_cost_stock) / total_qty

                    product.quantity = total_qty
                    product.save(update_fields=['quantity', 'cost_price'])
                    
                    StockMovement.objects.create(
                        product=product,
                        movement_type='IN',
                        quantity=stock_qty_to_add,
                        unit_cost=unit_cost_stock,
                        balance_after=product.quantity,
                        reference=purchase_obj.doc_no,
                        # ✅ แก้ไข: เพิ่ม (โดย ชื่อคนนำเข้า)
                        note=f"Import File (โดย {importer_name})"
                    )

            # Finalize
            purchase_obj.status = 'POSTED'
            purchase_obj.save(update_fields=['status'])
            
            return True

    except Exception as e:
        print(f"Error in post_purchase: {e}")
        return False

def cancel_purchase(purchase_obj, user=None):
    """
    ยกเลิกใบรับสินค้า (Void)
    """
    if purchase_obj.status == 'CANCELLED':
        return True 
        
    if purchase_obj.status != 'POSTED':
        purchase_obj.status = 'CANCELLED'
        purchase_obj.save(update_fields=['status'])
        return True

    try:
        with transaction.atomic():
            # ✅ ดึงชื่อคนยกเลิก
            canceler_name = user.username if user else (purchase_obj.created_by.username if purchase_obj.created_by else "System")

            for item in purchase_obj.items.all():
                product = item.product
                qty = item.quantity
                items_per_unit = max(1, int(product.items_per_purchase_unit or 1))
                
                if product.is_bundle:
                    children = product.bundle_components.all()
                    if not children.exists(): continue

                    total_qty_to_remove = qty * items_per_unit

                    for child in children:
                        child.quantity = (child.quantity or 0) - total_qty_to_remove
                        child.save(update_fields=['quantity'])
                        
                        StockMovement.objects.create(
                            product=child,
                            movement_type='OUT', 
                            quantity=total_qty_to_remove,
                            unit_cost=child.cost_price,
                            balance_after=child.quantity,
                            reference=f"CANCEL-{purchase_obj.doc_no}",
                            # ✅ เพิ่มชื่อคนยกเลิกด้วย
                            note=f"ยกเลิกรับเข้า {purchase_obj.doc_no} (ชุด {product.sku}) โดย {canceler_name}"
                        )
                
                else:
                    stock_qty_to_remove = qty * items_per_unit
                    
                    product.quantity = (product.quantity or 0) - stock_qty_to_remove
                    product.save(update_fields=['quantity'])
                    
                    StockMovement.objects.create(
                        product=product,
                        movement_type='OUT',
                        quantity=stock_qty_to_remove,
                        unit_cost=product.cost_price,
                        balance_after=product.quantity,
                        reference=f"CANCEL-{purchase_obj.doc_no}",
                        # ✅ เพิ่มชื่อคนยกเลิกด้วย
                        note=f"ยกเลิกรับเข้า {purchase_obj.doc_no} โดย {canceler_name}"
                    )

            purchase_obj.status = 'CANCELLED'
            purchase_obj.save(update_fields=['status'])
            
            return True

    except Exception as e:
        raise ValueError(f"ไม่สามารถยกเลิกใบรับสินค้าได้: {str(e)}")