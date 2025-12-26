from django.contrib import admin
from .models import (Category, Supplier, Product, StockMovement, Payment, Purchase, PurchaseItem,Sale, SaleItem)


# ------------------------
# Category Admin
# ------------------------
@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'description']
    search_fields = ['name']


# ------------------------
# Supplier Admin
# ------------------------
@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'phone', 'address', 'created_at', 'updated_at']
    search_fields = ['name', 'phone']
    list_filter = ['created_at']


# ------------------------
# Product Admin
# ------------------------
@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'sku', 'name', 'category', 'primary_supplier',
        'unit', 'cost_price', 'selling_price',
        'wholesale_price', 'compatible_models','quantity','is_active',
        'created_at', 'updated_at'
    ]
    list_filter = ['is_active', 'category', 'created_at']
    search_fields = ['sku', 'name', 'compatible_models']




# ------------------------
# StockMovement Admin
# ------------------------
@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'product', 'movement_type', 'quantity',
        'cost', 'balance_after', 'reference', 'created_at','note'
    ]
    list_filter = ['movement_type', 'created_at']
    search_fields = ['product__name', 'product__sku', 'reference']


# ------------------------
# Payment Admin
# ------------------------
@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ['id', 'sale', 'method', 'amount', 'status', 'created_at']
    list_filter = ['method', 'status', 'created_at']
    search_fields = ['sale__doc_no']


# ------------------------
# PurchaseItem Inline
# ------------------------
class PurchaseItemInline(admin.TabularInline):
    model = PurchaseItem
    extra = 0
    fields = ['product', 'quantity', 'unit_cost', 'line_total']
    readonly_fields = ['line_total']


# ------------------------
# Purchase Admin
# ------------------------
@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'doc_no', 'supplier', 'purchase_date',
        'status', 'grand_total', 'remark', 'created_by', 'created_at'
    ]
    list_filter = ['status', 'purchase_date', 'created_at']
    search_fields = ['doc_no', 'supplier__name']
    inlines = [PurchaseItemInline]


# ------------------------
# PurchaseItem Admin
# ------------------------
@admin.register(PurchaseItem)
class PurchaseItemAdmin(admin.ModelAdmin):
    list_display = ['id', 'purchase', 'product', 'quantity', 'unit_cost', 'line_total']
    search_fields = ['purchase__doc_no', 'product__name']


# ------------------------
# SaleItem Inline
# ------------------------
class SaleItemInline(admin.TabularInline):
    model = SaleItem
    extra = 0
    fields = ['product', 'quantity', 'unit_price', 'cost_price', 'line_total']
    readonly_fields = ['line_total']


# ------------------------
# Sale Admin
# ------------------------
@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'doc_no',
        'doc_type',
        'ref_doc_no',
        'sale_date',
        'total_amount',
        'discount_amount',
        'grand_total',
        'status',
        'remark',
        'created_by',
        'created_at',
        'updated_at',
    ]
    list_filter = ['status', 'sale_date', 'created_at']
    search_fields = ['doc_no', 'remark']
    readonly_fields = ['doc_no', 'created_at', 'updated_at']
    
    inlines = [SaleItemInline]


# ------------------------
# SaleItem Admin
# ------------------------
@admin.register(SaleItem)
class SaleItemAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'sale',
        'product',
        'quantity',
        'unit_price',
        'cost_price',
        'line_total',
    ]
    search_fields = ['sale__doc_no', 'product__name', 'product__sku']
    list_filter = ['sale__status', 'sale__sale_date']
    readonly_fields = ['line_total']