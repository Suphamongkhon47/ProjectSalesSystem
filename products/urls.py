"""
URLs สำหรับ products app
"""

from django.urls import path
from products.views import reports_return as return_rpt
from products.views import retail_sales_report

from .views import (
    dashboard,
    import_product_manual,
    import_product_file,
    product_manage_views,
    product_report_views,
    purchase_report_views,
    stock_views,
    sales, sales_report, return_view,
    supplier_view, category_views,
    receipt_settings_views,
)


urlpatterns = [
    
    # ========================================
    # 📊 Dashboard (หน้าหลัก)
    # ========================================
    path('', dashboard.dashboard, name='home_dashboard'),

    
    
    # ========================================
    # 📦 นำเข้าสินค้า (Import Products)
    # ========================================
    path('import/manual/', import_product_manual.import_manual, name='import_product_manual'),
    path('import/file/', import_product_file.import_product_file, name='import_product_file'),
    
    
    # ========================================
    # 📚 จัดการสินค้า (Product Management)
    # ========================================
    path('manage/', product_manage_views.manage_products, name='manage_products'),
    path('manage/edit/<int:product_id>/', product_manage_views.edit_product, name='edit_product'),
    path('manage/delete/<int:product_id>/', product_manage_views.delete_product, name='delete_product'),
    path('manage/history/<int:product_id>/', product_manage_views.product_history, name='product_history'),
    path('manage/bulk-delete/', product_manage_views.bulk_delete_products, name='bulk_delete_products'),
    
    
    # ========================================
    # 🛒 ขายสินค้า (Sales / POS)
    # ========================================
    ## หน้าหลัก
    path('sales/', sales.sales, name='sales'),
    path('sales/<int:sale_id>/print/', sales.print_receipt, name='print_receipt'),
    
    ## API
    path('sales/api/search/', sales.search_products_ajax, name='search_products_ajax'),
    path('api/get-pair-products/', sales.get_pair_products, name='get_pair_products'),
    path('sales/api/create/', sales.create_sale, name='create_sale'),
    path('sales/generate-qr/', sales.generate_qr_code, name='generate_qr_code'),
    path('sales/api/held-bills/', sales.get_held_bills_api, name='get_held_bills_api'),
    path('sales/api/resume/<int:sale_id>/', sales.get_sale_details_api, name='get_sale_details_api'),
    path('sales/api/discard/<int:sale_id>/', sales.discard_held_bill, name='discard_held_bill'),
    
    
    # ========================================
    # ↩️ คืนสินค้า (Returns)
    # ========================================
    ## หน้าหลัก
    path('returns/', return_view.returns, name='return_home'),
    path('returns/search/', return_view.search_sale_for_return, name='search_sale_for_return'),
    path('returns/create/', return_view.create_return, name='create_return'),
    
    ## รายงาน
    path('returns/list/', return_rpt.return_list, name='return_list'),
    path('returns/<int:return_id>/', return_rpt.return_detail, name='return_detail'),

    
    
    
    ## API
    path('returns/api/check-history/<int:sale_id>/', return_rpt.check_returned_items, name='check_returned_items'),
    
    
    # ========================================
    # 📋 รายงาน (Reports)
    # ========================================
    ## รายงานการขาย
    path('reports/sales/', sales_report.sales_report, name='sales_report'),
    path('sales/api/<int:sale_id>/cancel/', sales.cancel_sale, name='cancel_sale'),
    
    
    ## รายงานการนำเข้า
    path('purchases/', purchase_report_views.purchase_report, name='purchase_report'),
    path('purchases/<int:id>/', purchase_report_views.purchase_detail, name='purchase_detail'),
    path('purchases/<int:id>/cancel/', purchase_report_views.cancel_purchase, name='cancel_purchase'),
    path('reports/products/', product_report_views.product_sales_report, name='product_sales_report'),
    path('reports/retail/', retail_sales_report.sales_type_report, name='retail_sales_report'),
    
    
    # ========================================
    # 🔍 ตรวจสอบสต็อก (Stock Inquiry)
    # ========================================
    path('stock/inquiry/', stock_views.stock_inquiry, name='stock_inquiry'),
    
    ## API
    path('api/stock/search/', stock_views.stock_search_api, name='stock_search_api'),
    path('api/popular-models/', stock_views.popular_models_api, name='popular_models_api'),
    
    
    # ========================================
    # 📂 หมวดหมู่สินค้า (Categories)
    # ========================================
    path('categories/', category_views.category_list, name='category_list'),
    path('categories/create/', category_views.category_create, name='category_create'),
    path('categories/<int:category_id>/edit/', category_views.category_edit, name='category_edit'),
    path('categories/<int:category_id>/delete/', category_views.category_delete, name='category_delete'),
    
    
    # ========================================
    # 🏢 ตัวแทนจำหน่าย (Suppliers)
    # ========================================
    path('supplier/', supplier_view.supplier_list, name='supplier_list'),
    path('supplier/create/', supplier_view.supplier_create, name='supplier_create'),
    path('supplier/<int:supplier_id>/edit/', supplier_view.supplier_edit, name='supplier_edit'),
    path('supplier/<int:supplier_id>/delete/', supplier_view.supplier_delete, name='supplier_delete'),
    
    
    # ========================================
    # ⚙️ ตั้งค่าบิล/ใบเสร็จ (Receipt Settings)
    # ========================================
    path('settings/receipt/', receipt_settings_views.receipt_settings, name='receipt_settings'),


    # ========================================
    # 🔌 API Endpoints (ทั่วไป)
    # ========================================
    path('api/products/<int:product_id>/', sales.product_detail_api, name='product_detail_api'),
    
]
