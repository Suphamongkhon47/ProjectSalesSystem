"""
สคริปต์แก้ปัญหา Migration - รันครั้งเดียว

วิธีใช้:
    python fix_category_migration.py
"""

import os
import sys
import django

# Setup Django
sys.path.append('D:\\Pos-Project')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myproject.settings')
django.setup()

from products.models import Category

print("🔧 กำลังแก้ปัญหา Migration...")
print("="*60)

# 1. ลบข้อมูล Category เก่าทั้งหมด
count = Category.objects.count()
print(f"\n📊 พบ Category เก่า: {count} รายการ")

if count > 0:
    confirm = input("❓ ต้องการลบทั้งหมดไหม? (yes/no): ")
    if confirm.lower() == 'yes':
        Category.objects.all().delete()
        print("✅ ลบเสร็จแล้ว!")
    else:
        print("❌ ยกเลิก")
        sys.exit(0)

print("\n✅ เสร็จสิ้น! ตอนนี้รันได้:")
print("   1. python manage.py migrate")
print("   2. python manage.py seed_categories")
