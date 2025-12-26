
from django.db import models
from decimal import Decimal
import uuid




# ------------------------
# 1. Category
# ------------------------
class Category(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="ชื่อหมวดหมู่")
    description = models.TextField(blank=True, verbose_name="รายละเอียด")

    class Meta:
        db_table = "categories"
        verbose_name = "categorie"

    def __str__(self):
        return self.name


# ------------------------
# 2. Supplier
# ------------------------
class Supplier(models.Model):
    name = models.CharField(max_length=200, verbose_name="ชื่อร้านค้า/บริษัท")
    phone = models.CharField(max_length=20, blank=True, verbose_name="เบอร์โทร")
    address = models.TextField(blank=True, verbose_name="ที่อยู่")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "suppliers"

    def __str__(self):
        return self.name




# ------------------------
# 4. Product
# ------------------------
class Product(models.Model):
    # FK เชื่อมโยง
    category = models.ForeignKey('Category', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="หมวดหมู่")
    primary_supplier = models.ForeignKey('Supplier', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="ซัพพลายเออร์")

    # ข้อมูลหลัก
    sku = models.CharField(max_length=50, unique=True, blank=True, verbose_name="รหัสสินค้า (SKU)")
    name = models.CharField(max_length=200, db_index=True, verbose_name="ชื่อสินค้า")
    description = models.TextField(blank=True, verbose_name="รายละเอียด")
    
    # หน่วยนับ
    unit = models.CharField(max_length=50, default="ชิ้น", verbose_name="หน่วยนับ")

    
    # ราคา
    cost_price = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="ราคาทุนปัจจุบัน")
    selling_price = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="ราคาขาย")
    wholesale_price = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="ราคาขายส่ง")
    
    # การค้นหา
    compatible_models = models.CharField(max_length=255, blank=True, verbose_name="รุ่นรถที่ใช้ได้")
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="คงเหลือ")
    
    # สถานะ
    is_active = models.BooleanField(default=True, verbose_name="เปิดขาย")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "products"

    def save(self, *args, **kwargs):
        # Logic: ถ้า SKU ว่าง ให้ Gen รหัสอัตโนมัติ (P-XXXXXXXX)
        if not self.sku:
            random_code = str(uuid.uuid4())[:8].upper()
            self.sku = f"P-{random_code}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.sku} - {self.name}"



