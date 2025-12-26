"""
URLs สำหรับ products app
"""

from django import views
from django.urls import path
from products.views.returns import reports as return_rpt

from .views import (
    dashboard,
    import_product_manual, 
    import_product_file, 
    report_views, 
    product_manage_views, 
    purchase_report_views,
    sales,sales_report,return_view
)


urlpatterns = [
    # ========== นำเข้าสินค้า ==========
    path('import/', import_product_manual, name='import_product'),
    path('import/manual/', import_product_manual, name='import_product_manual'),
    path('import/file/', import_product_file, name='import_product_file'),
    
    # ========== รายงานการซื้อ ==========
    path('purchases/', purchase_report_views.purchase_report, name='purchase_report'),
    path('purchases/<int:id>/', purchase_report_views.purchase_detail, name='purchase_detail'),
    path('purchases/<int:id>/cancel/', purchase_report_views.cancel_purchase, name='cancel_purchase'),
    
    # ========== รายงานการนำเข้า ==========
    path('reports/import/', report_views.import_report, name='import_report'),
    path('reports/import/<int:movement_id>/', report_views.import_detail, name='import_detail'),
    path('reports/sales/', sales_report.sales_report, name='sales_report'),
        # ✅ เพิ่ม: รายงาน
    path('', dashboard.dashboard, name='home_dashboard'),
    path('dashboard/top-products/', dashboard.daily_top_products, name='daily_top_products'),
    path('dashboard/sales-summary/', dashboard.sales_summary, name='sales_summary'),
    
    # ========== จัดการสินค้า ==========
    path('manage/', product_manage_views.manage_products, name='manage_products'),
    path('manage/edit/<int:product_id>/', product_manage_views.edit_product, name='edit_product'),
    path('manage/delete/<int:product_id>/', product_manage_views.delete_product, name='delete_product'),
    path('manage/history/<int:product_id>/', product_manage_views.product_history, name='product_history'),
    path('manage/bulk-delete/', product_manage_views.bulk_delete_products, name='bulk_delete_products'),
    
    # ========== ขายสินค้า (Sales) ========== ✅
    path('sales/', sales.sales, name='sales'),
    path('sales/list/', sales.sale_list, name='sale_list'),
    path('sales/<int:sale_id>/', sales.sale_detail, name='sale_detail'),
    path('sales/<int:sale_id>/print/', sales.print_receipt, name='print_receipt'),

    path('returns/',return_view.returns, name='return_home'),
    path('returns/search/', return_view.search_sale_for_return, name='search_sale_for_return'),
    path('returns/create/', return_view.create_return, name='create_return'),
    
    path('returns/list/', return_rpt.return_list, name='return_list'),
    path('returns/<int:return_id>/', return_rpt.return_detail, name='return_detail'),
    path('returns/<int:return_id>/cancel/', return_view.cancel_return, name='cancel_return'),
    path('returns/stats/', return_rpt.return_statistics, name='return_statistics'),


    # API
    path('sales/api/search/', sales.search_products_ajax, name='search_products_ajax'),
    path('sales/api/create/', sales.create_sale, name='create_sale'),
    path('sales/api/<int:sale_id>/cancel/', sales.cancel_sale, name='cancel_sale'),
    path('sales/generate-qr/', sales.generate_qr_code, name='generate_qr_code'),
    path('sales/api/held-bills/', sales.get_held_bills_api, name='get_held_bills_api'),
    path('sales/api/resume/<int:sale_id>/', sales.get_sale_details_api, name='get_sale_details_api'),
    path('sales/api/discard/<int:sale_id>/', sales.discard_held_bill, name='discard_held_bill'), # 🗑️ ปุ่มยกเลิก
    path('returns/api/check-history/<int:sale_id>/', return_rpt.check_returned_items, name='check_returned_items'),
]

