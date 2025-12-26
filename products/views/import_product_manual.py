from decimal import Decimal
import uuid
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required

from products.models import Category, Supplier
from .helpers import _D, _stage, _remove_row, _clear_all, _commit_to_database

@login_required
def import_product_manual(request):
    """นำเข้าสินค้าแบบกรอกเอง"""
    
    categories = Category.objects.order_by("name")
    suppliers = Supplier.objects.order_by("name")
    stage = _stage(request.session)
    
    if request.method == "GET":
        edit_data = None
        edit_index = request.GET.get("edit")
        
        if edit_index is not None:
            try:
                idx = int(edit_index)
                if 0 <= idx < len(stage):
                    edit_data = stage[idx]
                    stage.pop(idx)
                    request.session.modified = True
            except:
                pass
        
        return render(request, "products/stock/import_manual.html", {
            "categories": categories,
            "suppliers": suppliers,
            "stage": stage,
            "total_rows": len(stage),
            "edit_data": edit_data,
        })
    
    action = request.POST.get("action")
    
    if action == "add_row":
        return _add_row_manual(request, stage)
    elif action == "remove_row":
        return _remove_row(request, stage, "import_product_manual")
    elif action == "clear_all":
        return _clear_all(request, "import_product_manual")
    elif action == "commit":
        return _commit_to_database(request, stage, "import_product_manual")
    
    return redirect("import_product_manual")


def _add_row_manual(request, stage):
    """ฟังก์ชันย่อย: รับค่าจากฟอร์มลง Session"""
    try:
        category_id = request.POST.get("category")
        raw_sku = (request.POST.get("sku") or "").strip().upper()
        if raw_sku:
            sku = raw_sku
        else:
            # ✅ ถ้าไม่ได้กรอก ให้ Gen รหัสใหม่ทันที (P-XXXXXXXX)
            random_code = str(uuid.uuid4())[:8].upper()
            sku = f"P-{random_code}"
        name = (request.POST.get("name") or "").strip()
        
        cost_price = _D(request.POST.get("cost_price"))
        selling_price = _D(request.POST.get("selling_price"))
        wholesale_price = _D(request.POST.get("wholesale_price"))
        
        # ✅ แก้: ใช้ quantity และ unit เท่านั้น
        quantity = _D(request.POST.get("quantity"))
        unit = request.POST.get("unit") or "ชิ้น"
        
        compatible_models = (request.POST.get("compatible_models") or "").strip()
        created_by = (request.POST.get("created_by") or request.user.username).strip()
        reference = (request.POST.get("reference") or "").strip()
        supplier_id = request.POST.get("supplier") or None
        
        if not category_id or not name or quantity <= 0:
            messages.error(request, "❌ กรุณากรอก: หมวดหมู่, ชื่อสินค้า, และจำนวน")
            return redirect("import_product_manual")
        
        category_name = "-"
        if category_id:
            try:
                category_name = Category.objects.get(id=category_id).name
            except:
                pass

        item = {
            "category_id": int(category_id),
            "category_name": category_name,
            "sku": raw_sku,
            "name": name,
            "compatible_models": compatible_models,
            "cost_price": str(cost_price),
            "selling_price": str(selling_price),
            "wholesale_price": str(wholesale_price),
            "quantity": str(quantity),
            "unit": unit,
            "created_by": created_by,
            "reference": reference,
            "supplier_id": int(supplier_id) if supplier_id else None,
        }
        
        stage.append(item)
        request.session.modified = True
        messages.success(request, f"✅ ลงรายการ: {name}")
        
    except Exception as e:
        messages.error(request, f"❌ เกิดข้อผิดพลาด: {e}")
        
    return redirect("import_product_manual")