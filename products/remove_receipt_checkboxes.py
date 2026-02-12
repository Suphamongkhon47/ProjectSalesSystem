import os
import django
import sys

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pos_system.settings')
django.setup()

from products.models import SystemSetting

def main():
    print("🗑️ กำลังลบการตั้งค่า show_sku และ show_unit_price...")
    print("-" * 50)
    
    deleted_count = 0
    keys_to_remove = ['show_sku', 'show_unit_price']
    
    for key in keys_to_remove:
        try:
            obj = SystemSetting.objects.get(key=key)
            obj.delete()
            print(f"✅ ลบ '{key}' สำเร็จ (ค่าเดิม: {obj.value})")
            deleted_count += 1
        except SystemSetting.DoesNotExist:
            print(f"⚠️ ไม่พบ '{key}' ในฐานข้อมูล (ข้ามไป)")
    
    print("-" * 50)
    print(f"🎉 สำเร็จ! ลบทั้งหมด {deleted_count} รายการ")
    print("\n📝 หมายเหตุ: SKU และราคาต่อหน่วยจะแสดงบนบิลเสมอตั้งแต่นี้")

if __name__ == '__main__':
    main()