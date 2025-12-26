from decimal import Decimal
from django.shortcuts import redirect
from django.contrib import messages
from django.db import transaction
from django.utils import timezone
from datetime import datetime
from django.contrib.auth import get_user_model

# Import Models
from products.models import (
    Product, StockMovement,
    Supplier, Purchase, PurchaseItem,
    Category
)

# ✅ Import Service
from products.Services.purchase_service import post_purchase

User = get_user_model()

def _D(v, default=Decimal("0")):
    """แปลงค่าเป็น Decimal อย่างปลอดภัย"""
    try:
        if v is None or v == "":
            return default
        return Decimal(str(v))
    except:
        return default

def _stage(session):
    """ดึงข้อมูลตะกร้าสินค้าจาก Session"""
    return session.setdefault("import_stage", [])

def _remove_row(request, stage, redirect_to):
    """ลบแถวออกจากตารางชั่วคราว"""
    idx = int(request.POST.get("index", "-1"))
    if 0 <= idx < len(stage):
        stage.pop(idx)
        request.session.modified = True
        messages.success(request, "🗑️ ลบรายการเรียบร้อย")
    return redirect(redirect_to)

def _clear_all(request, redirect_to):
    """ล้างตารางทั้งหมด"""
    request.session["import_stage"] = []
    request.session.modified = True
    messages.success(request, "🗑️ ล้างข้อมูลทั้งหมดแล้ว")
    return redirect(redirect_to)

def _generate_purchase_doc_no():
    """สร้างเลขที่เอกสาร PO-YYYYMMDD-XXX"""
    today = datetime.now()
    prefix = f"PO-{today.strftime('%Y%m%d')}"
    
    last_purchase = Purchase.objects.filter(doc_no__startswith=prefix).order_by("-doc_no").first()
    
    if last_purchase:
        try:
            last_num = int(last_purchase.doc_no.split("-")[-1])
            new_num = last_num + 1
        except:
            new_num = 1
    else:
        new_num = 1
    
    return f"{prefix}-{new_num:03d}"

def _commit_to_database(request, stage, redirect_to):
    """
    บันทึกข้อมูลลงฐานข้อมูลจริง
    1. สร้าง Purchase (DRAFT)
    2. สร้าง/อัปเดต Product
    3. สร้าง PurchaseItem
    4. เรียก Service เพื่อยืนยัน (POST) และตัดสต็อก
    """
    if not stage:
        messages.error(request, "❌ ไม่มีข้อมูลในรายการ")
        return redirect(redirect_to)
    
    # 1. เตรียม User และ Supplier
    user = request.user if request.user.is_authenticated else User.objects.filter(is_superuser=True).first()
    
    # ดึง Supplier จากรายการแรก
    first_row = stage[0]
    supplier_id = first_row.get('supplier_id')
    supplier = None
    
    if supplier_id:
        supplier = Supplier.objects.filter(id=supplier_id).first()
        
    if not supplier:
        supplier, _ = Supplier.objects.get_or_create(
            name="General Supplier",
            defaults={"address": "-"}
        )

    created_count = 0
    updated_count = 0
    total_amount = Decimal("0")

    try:
        with transaction.atomic():
            # 2. สร้างหัวเอกสาร Purchase (DRAFT)
            doc_no = _generate_purchase_doc_no()
            purchase = Purchase.objects.create(
                doc_no=doc_no,
                supplier=supplier,
                purchase_date=timezone.now(),
                status='DRAFT',
                created_by=user,
                remark=f"Import Ref: {first_row.get('reference', '-')}"
            )

            # 3. วนลูปสินค้า
            for row in stage:
                sku = row.get('sku', '').strip()
                name = row.get('name', '').strip()
                
                # แปลงตัวเลข
                qty = _D(row.get('quantity'))
                cost = _D(row.get('cost_price'))
                price = _D(row.get('selling_price'))
                wholesale = _D(row.get('wholesale_price'))
                
                # เตรียมข้อมูล Product
                defaults = {
                    'name': name,
                    'category_id': row.get('category_id'),
                    'unit': row.get('unit', 'ชิ้น'),  # ✅ หน่วยขาย
                    'cost_price': cost,
                    'selling_price': price,
                    'wholesale_price': wholesale,
                    'compatible_models': row.get('compatible_models', ''),  # ✅ รุ่นรถ (Text)
                    'is_active': True,
                    'primary_supplier': supplier
                }

                # 3.1 สร้างหรืออัปเดต Product
                if sku:
                    product, created = Product.objects.update_or_create(
                        sku=sku,
                        defaults=defaults
                    )
                else:
                    product = Product.objects.create(**defaults)
                    created = True

                if created:
                    created_count += 1
                    # สร้าง Inventory
                else:
                    updated_count += 1

                # 3.2 สร้างรายการในบิล (PurchaseItem)
                line_total = qty * cost
                total_amount += line_total
                
                PurchaseItem.objects.create(
                    purchase=purchase,
                    product=product,
                    quantity=qty,
                    unit_cost=cost
                )

            # 4. ✅ เรียกใช้ Service เพื่อยืนยันและตัดสต็อก
            if post_purchase(purchase):
                messages.success(request, f"✅ บันทึกสำเร็จ! เอกสาร {doc_no} (ใหม่ {created_count}, เดิม {updated_count})")
            else:
                messages.warning(request, f"⚠️ บันทึกข้อมูลแล้ว แต่ยังไม่ได้ยืนยันสต็อก (สถานะ DRAFT)")

            # เคลียร์ Session
            request.session['import_stage'] = []
            request.session.modified = True
            
            # เก็บ ID บิลล่าสุด
            request.session['last_purchase_id'] = purchase.id

    except Exception as e:
        messages.error(request, f"❌ เกิดข้อผิดพลาด: {str(e)}")
        return redirect(redirect_to)

    return redirect('purchase_report')