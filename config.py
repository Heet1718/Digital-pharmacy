"""
Configuration file for Medical Store Management System
"""
import os

class Config:
    """Base configuration"""
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'medical-store-secret-key-2026'
    
    # MySQL Database Configuration
    DB_HOST = 'localhost'
    DB_USER = 'root'
    DB_PASSWORD = ''  # Change this to your MySQL password
    DB_NAME = 'medical_store2'
    
    # Session Configuration
    SESSION_PERMANENT = False
    SESSION_TYPE = 'filesystem'
    
    # Application Settings
    APP_NAME = 'MediStore Pro'
    APP_VERSION = '1.0.0'
    
    # Pagination
    ITEMS_PER_PAGE = 50
    
    # GST Configuration
    GST_RATE = 12.0  # 12% GST
    
    # Low Stock Threshold
    LOW_STOCK_THRESHOLD = 15
    
    # Invoice Settings
    INVOICE_PREFIX = 'INV'
    
    # Color Theme (Minimal & Professional)
    PRIMARY_COLOR = '#4f46e5'  # Indigo
    ACCENT_COLOR = '#10b981'   # Emerald Green
    DANGER_COLOR = '#ef4444'   # Red
    WARNING_COLOR = '#f59e0b'  # Amber
