"""
Medical Store Billing and Inventory Management System
Flask Application - Main Entry Point
"""

from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash, send_file
import mysql.connector
from datetime import datetime, timedelta
import hashlib
import csv
import io
import os
from werkzeug.utils import secure_filename
from config import Config
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib import colors
from reportlab.lib.units import inch, cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak, Image, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT, TA_JUSTIFY
from reportlab.pdfgen import canvas
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics import renderPDF
import uuid
# from flask_mail import Mail, Message
app = Flask(__name__)
app.config.from_object(Config)

# ============================================
# DATABASE CONNECTION
# ============================================
def get_db():
    """Create MySQL database connection"""
    try:
        conn = mysql.connector.connect(
            host=Config.DB_HOST,
            user=Config.DB_USER,
            password=Config.DB_PASSWORD,
            database=Config.DB_NAME
        )
        return conn
    except mysql.connector.Error as e:
        print(f"Database connection error: {e}")
        return None

# ============================================
# HELPER FUNCTIONS
# ============================================
def get_setting(key, default=None):
    """Get a single setting value from database"""
    db = get_db()
    if not db:
        return default
    
    try:
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT setting_value FROM settings WHERE setting_key = %s", (key,))
        result = cursor.fetchone()
        db.close()
        
        if result:
            return result['setting_value']
        return default
    except:
        return default


def get_all_settings():
    """Get all settings as a dictionary"""
    db = get_db()
    if not db:
        return {}
    
    try:
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT setting_key, setting_value FROM settings")
        results = cursor.fetchall()
        db.close()
        
        settings_dict = {}
        for row in results:
            settings_dict[row['setting_key']] = row['setting_value']
        return settings_dict
    except:
        return {}

def hash_password(password):
    """Hash password using SHA-256"""
    return hashlib.sha256(password.encode()).hexdigest()

def generate_bill_number():
    """Generate unique bill number"""
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    invoice_prefix = get_setting('invoice_prefix', 'INV')
    return f"{invoice_prefix}-{timestamp}"

def calculate_gst(amount):
    """Calculate GST amount using rate from settings"""
    gst_rate = float(get_setting('gst_rate', '12.0'))
    return round(amount * gst_rate / 100, 2)

def format_amount(amount):
    """Format amount for better readability (in Crores, Lakhs, or Thousands)"""
    amount = float(amount)
    if amount >= 10000000:  # 1 Crore+
        return f"₹{amount / 10000000:.2f} Cr"
    elif amount >= 100000:  # 1 Lakh+  
        return f"₹{amount / 100000:.2f} L"
    elif amount >= 1000:  # 1 Thousand+
        return f"₹{amount / 1000:.2f}K"
    return f"₹{amount:.2f}"

def get_quarter_info(date_obj=None):
    """Get quarter information for a given date"""
    if date_obj is None:
        date_obj = datetime.now()
    
    year = date_obj.year
    month = date_obj.month
    
    if month <= 3:
        quarter = 'Q4'
        fiscal_year = year - 1
    elif month <= 6:
        quarter = 'Q1'
        fiscal_year = year
    elif month <= 9:
        quarter = 'Q2'
        fiscal_year = year
    else:
        quarter = 'Q3'
        fiscal_year = year
    
    return {
        'quarter': quarter,
        'fiscal_year': fiscal_year,
        'display': f"{quarter} FY{str(fiscal_year)[-2:]}-{str(fiscal_year+1)[-2:]}"
    }

def get_quarter_date_range(quarter, fiscal_year):
    """Get start and end dates for a given quarter"""
    quarter_months = {
        'Q1': (4, 6),
        'Q2': (7, 9),
        'Q3': (10, 12),
        'Q4': (1, 3)
    }
    
    start_month, end_month = quarter_months[quarter]
    
    if quarter == 'Q4':
        year = fiscal_year + 1
    else:
        year = fiscal_year
    
    start_date = datetime(year, start_month, 1)
    
    if end_month == 12:
        end_date = datetime(year, 12, 31)
    elif end_month == 3:
        end_date = datetime(year, 3, 31)
    elif end_month == 6:
        end_date = datetime(year, 6, 30)
    else:  # end_month == 9
        end_date = datetime(year, 9, 30)
    
    return start_date, end_date

def get_last_n_quarters(n=6):
    """Get list of last N quarters"""
    quarters = []
    current = get_quarter_info()
    
    quarter_order = ['Q1', 'Q2', 'Q3', 'Q4']
    current_q_idx = quarter_order.index(current['quarter'])
    fiscal_year = current['fiscal_year']
    
    for i in range(n):
        q_idx = (current_q_idx - i) % 4
        if i > 0 and q_idx == 3:
            fiscal_year -= 1
        
        quarter = quarter_order[q_idx]
        quarters.append({
            'quarter': quarter,
            'fiscal_year': fiscal_year,
            'display': f"{quarter} FY{str(fiscal_year)[-2:]}-{str(fiscal_year+1)[-2:]}"
        })
    
    return quarters

def cleanup_old_data():
    """Remove data older than 6 quarters"""
    quarters = get_last_n_quarters(6)
    oldest_quarter = quarters[-1]
    start_date, _ = get_quarter_date_range(oldest_quarter['quarter'], oldest_quarter['fiscal_year'])
    
    db = get_db()
    if not db:
        return False
    
    try:
        cursor = db.cursor()
        
        # Delete old bills and related items
        cursor.execute("""
            DELETE bi FROM bill_items bi
            JOIN bills b ON bi.bill_id = b.id
            WHERE b.bill_date < %s
        """, (start_date,))
        
        cursor.execute("DELETE FROM bills WHERE bill_date < %s", (start_date,))
        
        db.commit()
        db.close()
        return True
    except Exception as e:
        print(f"Error cleaning old data: {e}")
        if db:
            db.close()
        return False

def generate_purchase_number():
    """Generate unique purchase order number"""
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    return f"PO-{timestamp}"

# ============================================
# AUTHENTICATION ROUTES
# ============================================
@app.route('/')
def index():
    """Landing page"""
    # if 'user_id' in session:
    #     if session.get('role') == 'owner':
    #         return redirect(url_for('dashboard'))
    #     return redirect(url_for('billing'))
    return render_template('landing.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    """User login"""
    # If user is already logged in, redirect to appropriate page
    if 'user_id' in session:
        if session.get('role') == 'owner':
            return redirect(url_for('dashboard'))
        else:
            return redirect(url_for('billing'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        hashed_password = hash_password(password)
        
        db = get_db()
        if db:
            cursor = db.cursor(dictionary=True)
            cursor.execute(
                "SELECT * FROM users WHERE username = %s AND password = %s",
                (username, hashed_password)
            )
            user = cursor.fetchone()
            db.close()
            
            if user:
                session['user_id'] = user['id']
                session['username'] = user['username']
                session['role'] = user['role']
                session['full_name'] = user['full_name']
                
                if user['role'] == 'owner':
                    return redirect(url_for('dashboard'))
                return redirect(url_for('billing'))
            
            flash('Invalid credentials!', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    """User logout"""
    session.clear()
    return redirect(url_for('index'))

# ============================================
# DASHBOARD ROUTES
# ============================================
@app.route('/dashboard')
def dashboard():
    """Owner dashboard with analytics"""
    if 'user_id' not in session or session.get('role') != 'owner':
        return redirect(url_for('login'))
    
    # Get selected year from request or use current year
    selected_year = request.args.get('year', type=int)
    current_year = selected_year if selected_year else datetime.now().year
    
    db = get_db()
    if not db:
        return "Database connection error", 500
    cursor = db.cursor(dictionary=True, buffered=True)
    
    
    # Get available years from bills table
    cursor.execute("""
        SELECT DISTINCT YEAR(bill_date) as year 
        FROM bills 
        WHERE bill_date IS NOT NULL
        ORDER BY year DESC
    """)
    years_data = cursor.fetchall()
    available_years = [row['year'] for row in years_data] if years_data else [current_year]
    
    # Ensure current year is in the list
    if current_year not in available_years:
        available_years.append(current_year)
        available_years.sort(reverse=True)
    
    # Date range for selected year
    start_date = datetime(current_year, 1, 1)
    end_date = datetime(current_year, 12, 31)
    
    # Total Revenue (for selected year)
    # Replace the Total Revenue block (around line 228) with this:
# Total Revenue (Selected Year) - Subtracted Returns for Accuracy
    cursor.execute("""
        SELECT (
            (SELECT COALESCE(SUM(total_amount), 0) FROM bills) - 
            (SELECT COALESCE(SUM(refund_amount), 0) FROM returns)
        ) as net_revenue
    """)
    total_revenue = float(cursor.fetchone()['net_revenue'])
    
    # Today's Sales
    cursor.execute("""
        SELECT (
            (SELECT COALESCE(SUM(total_amount), 0) FROM bills WHERE DATE(bill_date) = CURDATE()) - 
            (SELECT COALESCE(SUM(refund_amount), 0) FROM returns WHERE DATE(return_date) = CURDATE())
        ) as net_today_sales
    """)
    today_sales = float(cursor.fetchone()['net_today_sales'])
    
    # Total Products
    cursor.execute("SELECT COALESCE(SUM(total_purchase_value), 0) as pur FROM supplier_purchases WHERE received_count > 0")
    total_purchase_amount = float(cursor.fetchone()['pur'])
    
    # Low Stock Items
    cursor.execute("""
        SELECT COUNT(*) as low_stock_count 
        FROM products 
        WHERE stock_quantity < min_stock_level
    """)
    low_stock_count = cursor.fetchone()['low_stock_count']
    
    # Recent Bills
    cursor.execute("""
        SELECT * FROM bills 
        ORDER BY bill_date DESC 
        LIMIT 10
    """)
    recent_bills = cursor.fetchall()
    
    # Top Selling Products
    cursor.execute("""
        SELECT bi.medicine_name, SUM(bi.quantity) as total_sold, 
               SUM(bi.total_amount) as revenue
        FROM bill_items bi
        GROUP BY bi.medicine_name
        ORDER BY total_sold DESC
        LIMIT 5
    """)
    top_products = cursor.fetchall()
    
    # Sales Chart Data (Last 7 days)
    cursor.execute("""
        SELECT DATE(bill_date) as date, 
               COALESCE(SUM(total_amount), 0) as daily_sales
        FROM bills
        WHERE bill_date >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
        GROUP BY DATE(bill_date)
        ORDER BY date
    """)
    sales_chart = cursor.fetchall()
    
    # Monthly Sales Graph (Last 12 months)
    cursor.execute("""
        SELECT DATE_FORMAT(bill_date, '%Y-%m') as month,
               COALESCE(SUM(total_amount), 0) as monthly_sales
        FROM bills
        WHERE bill_date >= DATE_SUB(CURDATE(), INTERVAL 12 MONTH)
        GROUP BY DATE_FORMAT(bill_date, '%Y-%m')
        ORDER BY month
    """)
    monthly_sales = cursor.fetchall()
    
    # Company-wise Stock (aggregate from batches, not products.stock_quantity)
    cursor.execute("""
        SELECT p.manufacturer, 
               COUNT(DISTINCT p.id) as product_count,
               COALESCE(SUM(pb.quantity), 0) as total_stock,
               COALESCE(SUM(pb.quantity * p.price), 0) as stock_value
        FROM products p
        LEFT JOIN product_batches pb ON p.id = pb.product_id AND pb.quantity > 0
        WHERE p.manufacturer IS NOT NULL AND p.manufacturer != ''
        GROUP BY p.manufacturer
        ORDER BY total_stock DESC
        LIMIT 10
    """)
    company_stock = cursor.fetchall()
    
    # Top Selling Medicines (by revenue)
    cursor.execute("""
        SELECT bi.medicine_name, 
               SUM(bi.quantity) as total_sold,
               SUM(bi.total_amount) as revenue
        FROM bill_items bi
        GROUP BY bi.medicine_name
        ORDER BY revenue DESC
        LIMIT 10
    """)
    top_selling_medicines = cursor.fetchall()
    
    # Pending Supplier Orders (awaiting delivery)
    cursor.execute("""
        SELECT COUNT(*) as pending_orders_count
        FROM supplier_purchases
        WHERE status = 'ordered'
    """)
    pending_orders_count = cursor.fetchone()['pending_orders_count']
    
    # Pending Orders Details
    cursor.execute("""
        SELECT sp.id as purchase_id, sp.medicine_name, sp.quantity, sp.total_amount,
               sp.order_date, sp.expected_delivery_date, sp.supplier_id,
               s.name as supplier_name, s.company_name, s.phone
        FROM supplier_purchases sp
        JOIN suppliers s ON sp.supplier_id = s.id
        WHERE sp.status = 'ordered'
        ORDER BY sp.expected_delivery_date ASC
    """)
    pending_orders = cursor.fetchall()
    
    # ============================================
    # BUSINESS ANALYTICS & FINANCIAL METRICS
    # ============================================
    
    # Total Purchase Amount (received orders only)
    cursor.execute("""
        SELECT COALESCE(SUM(total_amount), 0) as total_purchase_amount
        FROM supplier_purchases
        WHERE status = 'received'
    """)
    total_purchase_amount = cursor.fetchone()['total_purchase_amount']
    
    # Current Inventory Value (total batch stock × selling price)
    cursor.execute("""
        SELECT COALESCE(SUM(pb.quantity * p.price), 0) as inventory_value
        FROM product_batches pb
        JOIN products p ON pb.product_id = p.id
        WHERE pb.quantity > 0
    """)
    inventory_value = cursor.fetchone()['inventory_value']
    
    # Convert Decimal to float for calculations

    inventory_value = float(inventory_value)
    today_sales = float(today_sales)
    
    # This calculation (around line 312) stays the same, 
# Convert to float to ensure no Decimal vs Float type errors
    total_revenue = float(total_revenue)
    total_purchase_amount = float(total_purchase_amount)

# Correct Gross Profit (Revenue - Cost of Goods Sold)
    gross_profit = total_revenue - total_purchase_amount
    profit_margin = (gross_profit / total_revenue * 100) if total_revenue > 0 else 0

# Correct GST Liability (Output GST - Input GST)
# This prevents paying tax on refunded money
    gst_collected = total_revenue * 0.18 / 1.18  # 18% GST example
    gst_paid = total_purchase_amount * 0.18 / 1.18
    net_gst_liability = gst_collected - gst_paid
    
    # Today's Purchase Amount
    cursor.execute("""
        SELECT COALESCE(SUM(total_amount), 0) as today_purchase
        FROM supplier_purchases
        WHERE DATE(received_date) = CURDATE() AND status = 'received'
    """)
    today_purchase = cursor.fetchone()['today_purchase']
    today_purchase = float(today_purchase)
    
    # Today's Profit
    today_profit = today_sales - today_purchase
    
    # Business KPIs
    inventory_turnover = (total_purchase_amount / inventory_value) if inventory_value > 0 else 0
    
    # Monthly Profit Trend (Last 12 months)
    cursor.execute("""
        SELECT DATE_FORMAT(bill_date, '%Y-%m') as month,
               COALESCE(SUM(total_amount), 0) as monthly_revenue
        FROM bills
        WHERE bill_date >= DATE_SUB(CURDATE(), INTERVAL 12 MONTH)
        GROUP BY DATE_FORMAT(bill_date, '%Y-%m')
        ORDER BY month
    """)
    monthly_revenue_data = cursor.fetchall()
    
    cursor.execute("""
        SELECT DATE_FORMAT(received_date, '%Y-%m') as month,
               COALESCE(SUM(total_amount), 0) as monthly_purchase
        FROM supplier_purchases
        WHERE received_date >= DATE_SUB(CURDATE(), INTERVAL 12 MONTH)
              AND status = 'received'
        GROUP BY DATE_FORMAT(received_date, '%Y-%m')
        ORDER BY month
    """)
    monthly_purchase_data = cursor.fetchall()
    
    # Combine revenue and purchase data for profit calculation
    monthly_profit = {}
    for item in monthly_revenue_data:
        monthly_profit[item['month']] = {'revenue': item['monthly_revenue'], 'purchase': 0}
    for item in monthly_purchase_data:
        if item['month'] in monthly_profit:
            monthly_profit[item['month']]['purchase'] = item['monthly_purchase']
        else:
            monthly_profit[item['month']] = {'revenue': 0, 'purchase': item['monthly_purchase']}
    
    # ============================================
    # SUPPLIER METRICS & ANALYTICS
    # ============================================
    
    # Total Suppliers Count
    cursor.execute("SELECT COUNT(*) as total_suppliers FROM suppliers")
    total_suppliers = cursor.fetchone()['total_suppliers']
    
    # Active Supplier Orders (ordered status)
    cursor.execute("""
        SELECT COUNT(DISTINCT supplier_id) as active_suppliers
        FROM supplier_purchases
        WHERE status = 'ordered'
    """)
    active_suppliers = cursor.fetchone()['active_suppliers']
    
    # Top Suppliers by Purchase Volume (received orders)
    cursor.execute("""
        SELECT s.id, s.name, s.company_name, s.phone,
               COUNT(sp.id) as order_count,
               SUM(sp.total_amount) as total_purchase_value
        FROM suppliers s
        LEFT JOIN supplier_purchases sp ON s.id = sp.supplier_id AND sp.status = 'received'
        GROUP BY s.id, s.name, s.company_name, s.phone
        ORDER BY total_purchase_value DESC
        LIMIT 5
    """)
    top_suppliers = cursor.fetchall()
    
    # Recent Supplier Deliveries
    cursor.execute("""
        SELECT sp.id, sp.medicine_name, sp.quantity, sp.total_amount, sp.received_date,
               s.name as supplier_name, s.company_name
        FROM supplier_purchases sp
        JOIN suppliers s ON sp.supplier_id = s.id
        WHERE sp.status = 'received'
        ORDER BY sp.received_date DESC
        LIMIT 5
    """)
    recent_supplier_deliveries = cursor.fetchall()
    
    # Total Customers Count
    cursor.execute("SELECT COUNT(*) as total_customers FROM customers")
    total_customers = cursor.fetchone()['total_customers']
    
    # Total Bills Count
    cursor.execute("SELECT COUNT(*) as total_bills FROM bills")
    total_bills = cursor.fetchone()['total_bills']
    
    cursor.execute("SELECT COUNT(*) as total FROM products")
    total_products = cursor.fetchone()['total']
    
    db.close()
    
    # Get settings for display
    store_settings = get_all_settings()
    
    return render_template('dashboard.html',
                         total_revenue=total_revenue,
                         today_sales=today_sales,
                         total_products=total_products,
                         low_stock_count=low_stock_count,
                         recent_bills=recent_bills,
                         top_products=top_products,
                         sales_chart=sales_chart,
                         monthly_sales=monthly_sales,
                         company_stock=company_stock,
                         top_selling_medicines=top_selling_medicines,
                         pending_orders_count=pending_orders_count,
                         pending_orders=pending_orders,
                         total_purchase_amount=total_purchase_amount,
                         inventory_value=inventory_value,
                         gross_profit=gross_profit,
                         profit_margin=profit_margin,
                         gst_collected=gst_collected,
                         gst_paid=gst_paid,
                         net_gst_liability=net_gst_liability,
                         today_purchase=today_purchase,
                         today_profit=today_profit,
                         inventory_turnover=inventory_turnover,
                         monthly_profit=monthly_profit,
                         total_suppliers=total_suppliers,
                         active_suppliers=active_suppliers,
                         top_suppliers=top_suppliers,
                         recent_supplier_deliveries=recent_supplier_deliveries,
                         total_customers=total_customers,
                         total_bills=total_bills,
                         current_year=current_year,
                         available_years=available_years,
                         settings=store_settings)

# ============================================
# BILLING ROUTES
# ============================================
@app.route('/billing')
def billing():
    """Billing page - search and add to cart"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    return render_template('billing.html', 
                         cart=session.get('cart', []),
                         search_results=session.get('search_results', []))

@app.route('/search_medicine', methods=['POST'])
def search_medicine():
    """Search medicines with improved precision - prioritizes exact matches"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    search_query = request.form.get('search', '').strip()
    
    if not search_query:
        flash('Please enter a search term', 'warning')
        return redirect(url_for('billing'))
    
    db = get_db()
    if not db:
        flash('Database connection error', 'danger')
        return redirect(url_for('billing'))
    
    cursor = db.cursor(dictionary=True)
    
    # Strategy: Try exact match first, then broad match
    # This prevents unwanted results when typing exact names
    
    results = []
    
    # 1. Try EXACT match first (case-insensitive)
    exact_query = """
        SELECT * FROM products 
        WHERE LOWER(name) = LOWER(%s) 
           OR LOWER(manufacturer) = LOWER(%s)
           OR LOWER(category) = LOWER(%s)
        LIMIT 50
    """
    cursor.execute(exact_query, (search_query, search_query, search_query))
    exact_results = cursor.fetchall()
    
    if exact_results:
        # Exact match found - return only exact matches
        results = exact_results
    else:
        # 2. No exact match - try multi-term AND search for better precision
        terms = search_query.replace(',', ' ').split()
        
        if len(terms) > 1:
            # Multiple terms - ALL terms must match (AND logic)
            and_conditions = []
            and_params = []
            
            for term in terms:
                term_condition = "(name LIKE %s OR manufacturer LIKE %s OR category LIKE %s)"
                and_conditions.append(term_condition)
                search_pattern = f'%{term}%'
                and_params.extend([search_pattern, search_pattern, search_pattern])
            
            and_where_clause = " AND ".join(and_conditions)
            and_query = f"""
                SELECT * FROM products 
                WHERE ({and_where_clause})
                LIMIT 50
            """
            cursor.execute(and_query, tuple(and_params))
            results = cursor.fetchall()
        
        # 3. If still no results, try broader OR search
        if not results:
            or_conditions = []
            or_params = []
            
            for term in terms:
                term_condition = "(name LIKE %s OR manufacturer LIKE %s OR category LIKE %s)"
                or_conditions.append(term_condition)
                search_pattern = f'%{term}%'
                or_params.extend([search_pattern, search_pattern, search_pattern])
            
            or_where_clause = " OR ".join(or_conditions)
            or_query = f"""
                SELECT * FROM products 
                WHERE ({or_where_clause})
                LIMIT 50
            """
            cursor.execute(or_query, tuple(or_params))
            results = cursor.fetchall()
    
    # Fetch available batches for each product
    for product in results:
        cursor.execute("""
            SELECT pb.id as batch_id, pb.batch_number, pb.quantity, pb.expiry_date,
                   DATEDIFF(pb.expiry_date, CURDATE()) as days_until_expiry,
                   CASE 
                       WHEN pb.expiry_date < CURDATE() THEN 'expired'
                       WHEN DATEDIFF(pb.expiry_date, CURDATE()) <= 30 THEN 'urgent'
                       WHEN DATEDIFF(pb.expiry_date, CURDATE()) <= 90 THEN 'warning'
                       ELSE 'safe'
                   END as status
            FROM product_batches pb
            WHERE pb.product_id = %s AND pb.quantity > 0
            ORDER BY pb.expiry_date ASC, pb.quantity ASC
        """, (product['id'],))
        batches = cursor.fetchall()
        
        # Convert datetime objects to strings for session storage
        for batch in batches:
            if batch.get('expiry_date'):
                batch['expiry_date'] = batch['expiry_date'].strftime('%Y-%m-%d')
        
        product['batches'] = batches
    
    db.close()
    
    session['search_results'] = results
    session['search_query'] = search_query
    
    if not results:
        flash(f'No medicines found for "{search_query}"', 'info')
    
    return redirect(url_for('billing'))\

@app.route('/add_to_cart', methods=['POST'])
def add_to_cart():
    """Add medicine to cart with batch selection"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    product_id = int(request.form.get('product_id'))
    quantity = int(request.form.get('quantity', 1))
    batch_id = request.form.get('batch_id')  # Optional - for batch-specific selection
    
    db = get_db()
    if not db:
        flash('Database connection error', 'danger')
        return redirect(url_for('billing'))
    
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM products WHERE id = %s", (product_id,))
    product = cursor.fetchone()
    
    if not product:
        db.close()
        flash('Product not found', 'danger')
        return redirect(url_for('billing'))
    
    # If batch_id is provided, get batch details
    batch_info = None
    
    if batch_id:
        cursor.execute("""
            SELECT id, batch_number, quantity, expiry_date
            FROM product_batches 
            WHERE id = %s AND product_id = %s
        """, (batch_id, product_id))
        batch_info = cursor.fetchone()
        
        if not batch_info:
            db.close()
            flash('Selected batch not found', 'danger')
            return redirect(url_for('billing'))
        
        available_stock = batch_info['quantity']
    else:
        # Get total stock from all batches (not products.stock_quantity)
        cursor.execute("""
            SELECT COALESCE(SUM(quantity), 0) as total_stock
            FROM product_batches
            WHERE product_id = %s AND quantity > 0
        """, (product_id,))
        stock_result = cursor.fetchone()
        available_stock = stock_result['total_stock'] if stock_result else 0
    
    db.close()
    
    # Validate quantity
    if quantity > available_stock:
        flash(f'Insufficient stock! Only {available_stock} units available', 'warning')
        return redirect(url_for('billing'))
    
    cart = session.get('cart', [])
    
    # Create unique key: product_id + batch_id (if batch selected)
    cart_key = f"{product_id}_{batch_id}" if batch_id else str(product_id)
    
    # Check if item already in cart
    existing_item = None
    for item in cart:
        item_key = f"{item['id']}_{item.get('batch_id', '')}" if item.get('batch_id') else str(item['id'])
        if item_key == cart_key:
            existing_item = item
            break
    
    if existing_item:
        # Check if total quantity exceeds stock
        total_quantity = existing_item['quantity'] + quantity
        if total_quantity > available_stock:
            flash(f'Cannot add {quantity} more! Only {available_stock} units available and {existing_item["quantity"]} already in cart', 'warning')
            return redirect(url_for('billing'))
        existing_item['quantity'] = total_quantity
    else:
        # New item
        cart_item = {
            'id': product['id'],
            'name': product['name'],
            'price': float(product['price']),
            'quantity': quantity,
            'stock_quantity': available_stock
        }
        
        # Add batch info if selected
        if batch_info:
            cart_item['batch_id'] = batch_info['id']
            cart_item['batch_number'] = batch_info['batch_number']
            cart_item['expiry_date'] = batch_info['expiry_date'].strftime('%Y-%m-%d') if batch_info['expiry_date'] else None
        
        cart.append(cart_item)
    
    session['cart'] = cart
    session.pop('search_results', None)  # Clear search results after adding to cart
    
    batch_text = f" (Batch: {batch_info['batch_number']})" if batch_info else ""
    flash(f'{product["name"]}{batch_text} added to cart', 'success')
    
    return redirect(url_for('billing'))

@app.route('/remove_from_cart/<int:product_id>')
@app.route('/remove_from_cart/<int:product_id>/<int:batch_id>')
def remove_from_cart(product_id, batch_id=0):
    """Remove item from cart (supports batch-specific removal)"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    cart = session.get('cart', [])
    
    # Remove item matching product_id and batch_id (if specified)
    new_cart = []
    for item in cart:
        item_batch_id = item.get('batch_id', 0) or 0
        if item['id'] == product_id and item_batch_id == batch_id:
            continue  # Skip this item (remove it)
        new_cart.append(item)
    
    session['cart'] = new_cart
    flash('Item removed from cart', 'info')
    
    return redirect(url_for('billing'))

@app.route('/update_cart', methods=['POST'])
def update_cart():
    """Update cart quantities (supports batch-specific items)"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    cart = session.get('cart', [])
    
    for item in cart:
        batch_id = item.get('batch_id', 'nobatch')
        qty_key = f'quantity_{item["id"]}_{batch_id}'
        
        if qty_key in request.form:
            new_qty = int(request.form.get(qty_key, 1))
            if new_qty <= item['stock_quantity']:
                item['quantity'] = new_qty
            else:
                flash(f'Quantity for {item["name"]} exceeds stock!', 'warning')
    
    session['cart'] = cart
    flash('Cart updated', 'success')
    
    return redirect(url_for('billing'))

@app.route('/checkout', methods=['GET', 'POST'])
def checkout():
    """Checkout and generate bill"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    cart = session.get('cart', [])
    
    if not cart:
        flash('Cart is empty!', 'warning')
        return redirect(url_for('billing'))
    
    if request.method == 'POST':
        customer_name = request.form.get('customer_name', '').strip()
        customer_phone = request.form.get('customer_phone', '').strip()
        customer_email = request.form.get('customer_email', '').strip()
        customer_address = request.form.get('customer_address', '').strip()
        customer_id = request.form.get('customer_id', '')
        payment_method = request.form.get('payment_method', 'cash')  # Get payment method
        
        # Handle walk-in customers
        if not customer_phone:
            customer_phone = '0000000000'
        if not customer_name:
            customer_name = 'Walk-in Customer'
        
        db = get_db()
        if not db:
            flash('Database connection error', 'danger')
            return redirect(url_for('billing'))
        
        cursor = db.cursor(dictionary=True)
        
        # Find or create customer
        if customer_id:
            # Use existing customer ID
            customer_id = int(customer_id)
        else:
            # Check if customer exists by phone
            cursor.execute("SELECT id FROM customers WHERE phone = %s", (customer_phone,))
            existing = cursor.fetchone()
            
            if existing:
                customer_id = existing['id']
                # Update customer details
                cursor.execute("""
                    UPDATE customers 
                    SET name = %s, email = %s, address = %s
                    WHERE id = %s
                """, (customer_name, customer_email, customer_address, customer_id))
            else:
                # Create new customer
                cursor.execute("""
                    INSERT INTO customers (name, phone, email, address)
                    VALUES (%s, %s, %s, %s)
                """, (customer_name, customer_phone, customer_email, customer_address))
                customer_id = cursor.lastrowid
        
        # Calculate totals
        subtotal = sum(item['price'] * item['quantity'] for item in cart)
        gst_amount = calculate_gst(subtotal)
        total_amount = subtotal + gst_amount
        
        # Generate order/bill number
        order_number = generate_bill_number()
        
        # Validate stock availability before processing
        for item in cart:
            if item.get('batch_id'):
                # Check batch-specific stock
                cursor.execute("""
                    SELECT quantity FROM product_batches 
                    WHERE id = %s AND product_id = %s
                """, (item['batch_id'], item['id']))
                batch = cursor.fetchone()
                
                if not batch or batch['quantity'] < item['quantity']:
                    db.close()
                    available = batch['quantity'] if batch else 0
                    flash(f'Insufficient stock in selected batch for {item["name"]}! Only {available} units available but {item["quantity"]} in cart. Please update cart.', 'danger')
                    return redirect(url_for('billing'))
            else:
                # Check total stock from all batches (not products.stock_quantity)
                cursor.execute("""
                    SELECT COALESCE(SUM(quantity), 0) as total_stock
                    FROM product_batches
                    WHERE product_id = %s AND quantity > 0
                """, (item['id'],))
                stock_check = cursor.fetchone()
                available = stock_check['total_stock'] if stock_check else 0
                
                if available < item['quantity']:
                    db.close()
                    flash(f'Insufficient stock for {item["name"]}! Only {available} units available but {item["quantity"]} in cart. Please update cart.', 'danger')
                    return redirect(url_for('billing'))
        
        # Handle UPI payments differently - create pending order instead of bill
        if payment_method == 'upi':
            import json
            
            # Store cart data as JSON
            cart_json = json.dumps(cart)
            
            # Create pending order instead of bill
            cursor.execute("""
                INSERT INTO pending_orders (order_number, customer_id, customer_name, phone, email, address, 
                                           subtotal, gst, total_amount, payment_method, payment_status, 
                                           cart_data, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (order_number, customer_id, customer_name, customer_phone, customer_email, customer_address,
                  subtotal, gst_amount, total_amount, payment_method, 'pending', cart_json, session.get('user_id')))
            
            pending_order_id = cursor.lastrowid
            
            db.commit()
            db.close()
            
            # Clear cart, customer info, and search results
            session['cart'] = []
            session.pop('customer_info', None)
            session.pop('search_results', None)
            session['last_pending_order_id'] = pending_order_id
            
            flash('Please complete UPI payment. Bill will be created after payment approval.', 'info')
            return redirect(url_for('upi_payment', order_id=pending_order_id))
        
        # For CASH payments - create bill immediately as before
        # Insert bill with customer_id and payment details
        cursor.execute("""
            INSERT INTO bills (bill_number, customer_id, customer_name, phone, subtotal, gst, total_amount, payment_method, payment_status, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (order_number, customer_id, customer_name, customer_phone, subtotal, gst_amount, total_amount, payment_method, 'completed', session.get('user_id')))
        
        bill_id = cursor.lastrowid
        
        # Insert bill items and process batch sales
        for item in cart:
            cursor.execute("""
                INSERT INTO bill_items (bill_id, product_id, medicine_name, price, quantity, total_amount)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (bill_id, item['id'], item['name'], item['price'], item['quantity'], 
                  item['price'] * item['quantity']))
            
            # Check if specific batch was selected
            if item.get('batch_id'):
                # Deduct from specific batch
                batch_id = item['batch_id']
                
                # Verify batch has sufficient quantity
                cursor.execute("""
                    SELECT quantity FROM product_batches 
                    WHERE id = %s AND product_id = %s
                """, (batch_id, item['id']))
                batch = cursor.fetchone()
                
                if not batch or batch['quantity'] < item['quantity']:
                    db.rollback()
                    db.close()
                    flash(f'Insufficient stock in selected batch for {item["name"]}!', 'danger')
                    return redirect(url_for('billing'))
                
                # Deduct from specific batch only (trigger will update products.stock_quantity)
                cursor.execute("""
                    UPDATE product_batches
                    SET quantity = quantity - %s
                    WHERE id = %s
                """, (item['quantity'], batch_id))
                
            else:
                # No specific batch selected - use FIFO batch deduction
                cursor.callproc('sp_sell_product', [item['id'], item['quantity'], bill_id, 0, ''])
                
                # Consume all result sets from the stored procedure
                for result in cursor.stored_results():
                    result.fetchall()
            
        db.commit()
        db.close()
        
        # Clear cart, customer info, and search results
        session['cart'] = []
        session.pop('customer_info', None)
        session.pop('search_results', None)
        session['last_bill_id'] = bill_id
        
        flash('Bill generated successfully!', 'success')
        return redirect(url_for('invoice', bill_id=bill_id))
    
    # Calculate cart totals
    subtotal = sum(item['price'] * item['quantity'] for item in cart)
    gst_amount = calculate_gst(subtotal)
    total_amount = subtotal + gst_amount
    
    # Get customer info from session if available
    customer_info = session.get('customer_info', None)
    
    return render_template('checkout.html', 
                         cart=cart,
                         subtotal=subtotal,
                         gst_amount=gst_amount,
                         total_amount=total_amount,
                         customer_info=customer_info)

@app.route('/invoice/<int:bill_id>')
def invoice(bill_id):
    """Display invoice"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    if not db:
        return "Database connection error", 500
    
    cursor = db.cursor(dictionary=True)
    
    # Get bill details
    cursor.execute("SELECT * FROM bills WHERE id = %s", (bill_id,))
    bill = cursor.fetchone()
    
    if not bill:
        flash('Bill not found', 'danger')
        return redirect(url_for('billing'))
    
    # Get bill items
    cursor.execute("SELECT * FROM bill_items WHERE bill_id = %s", (bill_id,))
    bill_items = cursor.fetchall()
    
    db.close()
    
    # Get settings for invoice display
    store_settings = get_all_settings()
    
    return render_template('invoice.html', bill=bill, bill_items=bill_items, settings=store_settings)

@app.route('/upi_payment/<int:order_id>')
def upi_payment(order_id):
    """Display UPI payment page with QR code for pending order"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    if not db:
        flash('Database connection error', 'danger')
        return redirect(url_for('billing'))
    
    cursor = db.cursor(dictionary=True)
    
    # Get pending order details
    cursor.execute("SELECT * FROM pending_orders WHERE id = %s", (order_id,))
    order = cursor.fetchone()
    
    if not order:
        flash('Order not found', 'danger')
        db.close()
        return redirect(url_for('billing'))
    
    # Check if payment is already approved
    if order['payment_status'] == 'approved' and order['bill_id']:
        flash('Payment already approved', 'info')
        db.close()
        return redirect(url_for('invoice', bill_id=order['bill_id']))
    
    db.close()
    
    # Get UPI ID from settings
    upi_id = get_setting('upi_id', 'medistore@upi')
    
    return render_template('upi_payment.html', 
                         order_id=order['id'],
                         order_number=order['order_number'],
                         customer_name=order['customer_name'],
                         subtotal=order['subtotal'],
                         gst_amount=order['gst'],
                         total_amount=order['total_amount'],
                         upi_id=upi_id)

@app.route('/api/check_payment_status/<int:order_id>')
def check_payment_status(order_id):
    """API endpoint to check pending order payment status"""
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    db = get_db()
    if not db:
        return jsonify({'error': 'Database connection error'}), 500
    
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT payment_status, bill_id FROM pending_orders WHERE id = %s", (order_id,))
    order = cursor.fetchone()
    db.close()
    
    if not order:
        return jsonify({'error': 'Order not found'}), 404
    
    return jsonify({
        'status': order['payment_status'],
        'bill_id': order['bill_id']
    })

@app.route('/approve_payment/<int:order_id>', methods=['POST'])
def approve_payment(order_id):
    """Approve UPI payment and create bill from pending order"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    if not db:
        flash('Database connection error', 'danger')
        return redirect(url_for('bills'))
    
    cursor = db.cursor(dictionary=True)
    
    # Get pending order details
    cursor.execute("SELECT * FROM pending_orders WHERE id = %s", (order_id,))
    order = cursor.fetchone()
    
    if not order:
        flash('Order not found', 'danger')
        db.close()
        return redirect(url_for('bills'))
    
    # Check if already approved
    if order['payment_status'] == 'approved' and order['bill_id']:
        flash('Payment already approved', 'info')
        db.close()
        return redirect(url_for('invoice', bill_id=order['bill_id']))
    
    import json
    cart = json.loads(order['cart_data'])
    
    # Validate stock availability before creating bill
    for item in cart:
        if item.get('batch_id'):
            cursor.execute("""
                SELECT quantity FROM product_batches 
                WHERE id = %s AND product_id = %s
            """, (item['batch_id'], item['id']))
            batch = cursor.fetchone()
            
            if not batch or batch['quantity'] < item['quantity']:
                db.close()
                available = batch['quantity'] if batch else 0
                flash(f'Insufficient stock in selected batch for {item["name"]}! Only {available} units available. Cannot approve payment.', 'danger')
                return redirect(url_for('bills'))
        else:
            # Check total stock from all batches (not products.stock_quantity)
            cursor.execute("""
                SELECT COALESCE(SUM(quantity), 0) as total_stock
                FROM product_batches
                WHERE product_id = %s AND quantity > 0
            """, (item['id'],))
            stock_check = cursor.fetchone()
            available = stock_check['total_stock'] if stock_check else 0
            
            if available < item['quantity']:
                db.close()
                flash(f'Insufficient stock for {item["name"]}! Only {available} units available. Cannot approve payment.', 'danger')
                return redirect(url_for('bills'))
    
    # Create bill from pending order
    cursor.execute("""
        INSERT INTO bills (bill_number, customer_id, customer_name, phone, subtotal, gst, total_amount, 
                          payment_method, payment_status, payment_approved_at, payment_approved_by, created_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s, %s)
    """, (order['order_number'], order['customer_id'], order['customer_name'], order['phone'],
          order['subtotal'], order['gst'], order['total_amount'], 'upi', 'completed',
          session.get('user_id'), order['created_by']))
    
    bill_id = cursor.lastrowid
    
    # Insert bill items and process batch sales
    for item in cart:
        cursor.execute("""
            INSERT INTO bill_items (bill_id, product_id, medicine_name, price, quantity, total_amount)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (bill_id, item['id'], item['name'], item['price'], item['quantity'], 
              item['price'] * item['quantity']))
        
        # Check if specific batch was selected
        if item.get('batch_id'):
            batch_id = item['batch_id']
            
            # Deduct from specific batch only (trigger will update products.stock_quantity)
            cursor.execute("""
                UPDATE product_batches
                SET quantity = quantity - %s
                WHERE id = %s
            """, (item['quantity'], batch_id))
            
        else:
            # No specific batch selected - use FIFO batch deduction
            cursor.callproc('sp_sell_product', [item['id'], item['quantity'], bill_id, 0, ''])
            
            # Consume all result sets from the stored procedure
            for result in cursor.stored_results():
                result.fetchall()
    
    # Update pending order status to approved
    cursor.execute("""
        UPDATE pending_orders 
        SET payment_status = 'approved',
            approved_at = NOW(),
            approved_by = %s,
            bill_id = %s
        WHERE id = %s
    """, (session.get('user_id'), bill_id, order_id))
    
    db.commit()
    db.close()
    
    flash('Payment approved successfully! Bill has been created.', 'success')
    return redirect(url_for('invoice', bill_id=bill_id))

# ============================================
# INVENTORY ROUTES
# ============================================
@app.route('/inventory')
def inventory():
    """View all products with batch summary"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    if not db:
        return "Database connection error", 500
    
    cursor = db.cursor(dictionary=True)
    
    # Get products with aggregated batch info
    cursor.execute("""
        SELECT p.*, 
               COALESCE(SUM(pb.quantity), 0) as total_stock,
               COUNT(DISTINCT pb.id) as batch_count,
               MIN(pb.expiry_date) as nearest_expiry
        FROM products p
        LEFT JOIN product_batches pb ON p.id = pb.product_id AND pb.quantity > 0
        GROUP BY p.id
        ORDER BY p.name
    """)
    products = cursor.fetchall()
    db.close()
    
    # Get settings for display
    store_settings = get_all_settings()
    
    return render_template('inventory.html', products=products, settings=store_settings)
@app.route('/download_inventory_report')
def download_inventory_report():
    """Generate professional PDF with manufacturer-wise value summary"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    if not db:
        flash('Database connection error', 'danger')
        return redirect(url_for('inventory'))
    
    store_settings = get_all_settings()
    cursor = db.cursor(dictionary=True)

    # 1. Fetch Main Inventory Data
    cursor.execute("""
        SELECT p.name, p.manufacturer, p.category, p.price, p.min_stock_level,
               COALESCE(SUM(pb.quantity), 0) as total_stock,
               MIN(pb.expiry_date) as nearest_expiry
        FROM products p
        LEFT JOIN product_batches pb ON p.id = pb.product_id AND pb.quantity > 0
        GROUP BY p.id
        ORDER BY p.name
    """)
    products = cursor.fetchall()

    # 2. Fetch Manufacturer-wise Total Value
    # Value = Current Batch Stock * Product Selling Price
    cursor.execute("""
        SELECT COALESCE(p.manufacturer, 'Unknown') as manufacturer,
               SUM(pb.quantity * p.price) as total_value
        FROM products p
        JOIN product_batches pb ON p.id = pb.product_id
        WHERE pb.quantity > 0
        GROUP BY p.manufacturer
        ORDER BY total_value DESC
    """)
    mfg_summary = cursor.fetchall()
    db.close()

    buffer = io.BytesIO()
    # Using A4 with comfortable margins
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=18)
    elements = []
    styles = getSampleStyleSheet()

    # --- Header Section ---
    header_style = ParagraphStyle('HeaderStyle', fontSize=22, textColor=colors.HexColor('#4f46e5'), fontName='Helvetica-Bold', alignment=TA_CENTER, spaceAfter=10)
    elements.append(Paragraph(store_settings.get('store_name', 'MediStore Pro'), header_style))
    elements.append(Paragraph(f"Inventory Stock Status Report | {datetime.now().strftime('%d %b %Y, %I:%M %p')}", 
                              ParagraphStyle('Sub', fontSize=10, textColor=colors.grey, alignment=TA_CENTER, spaceAfter=20)))
    
    # --- Main Inventory Table ---
    data = [['Medicine Name', 'Manufacturer', 'Category', 'Price', 'Stock Level', 'Expiry']]
    for p in products:
        expiry = p['nearest_expiry'].strftime('%Y-%m-%d') if p['nearest_expiry'] else "-"
        stock_val = int(p['total_stock'])
        min_stock = int(p['min_stock_level'] or 15)
        
        stock_text = f"{stock_val} units"
        if stock_val <= min_stock:
            stock_text = f"{stock_text} (LOW)"

        data.append([
            p['name'], 
            p['manufacturer'] or "-", 
            p['category'] or "N/A", 
            f"INR{float(p['price']):.2f}", 
            stock_text, 
            expiry
        ])
    
    main_table = Table(data, colWidths=[4.5*cm, 3.5*cm, 3.0*cm, 2.5*cm, 3.0*cm, 2.5*cm])
    main_table_style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4f46e5')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e5e7eb')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (3, 1), (3, -1), 'RIGHT'),
        ('ALIGN', (4, 0), (4, -1), 'CENTER'),
    ])
    
    # Apply zebra stripes and low stock coloring
    for i in range(1, len(data)):
        if i % 2 == 0:
            main_table_style.add('BACKGROUND', (0, i), (-1, i), colors.HexColor('#f9fafb'))
        if "(LOW)" in data[i][4]:
            main_table_style.add('TEXTCOLOR', (4, i), (4, i), colors.red)

    main_table.setStyle(main_table_style)
    elements.append(main_table)

    # --- NEW: Manufacturer Value Summary Section ---
    elements.append(Spacer(1, 40))
    elements.append(Paragraph("Inventory Valuation by Manufacturer", 
                              ParagraphStyle('MfgTitle', fontSize=16, fontName='Helvetica-Bold', textColor=colors.HexColor('#10b981'), spaceAfter=12)))
    
    summary_data = [['Manufacturer Name', 'Total Stock Value (Selling Price)']]
    grand_total = 0
    
    for m in mfg_summary:
        val = float(m['total_value'] or 0)
        grand_total += val
        summary_data.append([m['manufacturer'], f"INR{val:,.2f}"])
    
    # Final Total Row
    summary_data.append(['TOTAL INVENTORY VALUE', f"INR{grand_total:,.2f}"])
    
    summary_table = Table(summary_data, colWidths=[11*cm, 8*cm])
    summary_style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#10b981')), # Green Theme for Finance
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        # Highlight Grand Total Row
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#ecfdf5')),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('TEXTCOLOR', (0, -1), (-1, -1), colors.HexColor('#065f46')),
    ])
    summary_table.setStyle(summary_style)
    elements.append(summary_table)

    # --- Footer ---
    elements.append(Spacer(1, 30))
    elements.append(Paragraph("End of Report. Valuation is calculated using (Current Stock Quantity × Selling Price).", 
                              ParagraphStyle('Footer', fontSize=8, textColor=colors.grey, alignment=TA_CENTER)))

    doc.build(elements)
    buffer.seek(0)
    
    return send_file(
        buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f"Inventory_Valuation_{datetime.now().strftime('%Y%m%d')}.pdf"
    )
    
@app.route('/low_stock')
def low_stock():
    """View low stock items based on aggregated batch quantities"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    if not db:
        return "Database connection error", 500
    
    cursor = db.cursor(dictionary=True)
    
    # Get products where total batch quantity is below minimum
    cursor.execute("""
        SELECT p.*, 
               COALESCE(SUM(pb.quantity), 0) as total_stock,
               COUNT(DISTINCT pb.id) as batch_count
        FROM products p
        LEFT JOIN product_batches pb ON p.id = pb.product_id AND pb.quantity > 0
        GROUP BY p.id
        HAVING total_stock < p.min_stock_level
        ORDER BY total_stock ASC
    """)
    low_stock_items = cursor.fetchall()
    db.close()
    
    # Get settings for display
    store_settings = get_all_settings()
    
    return render_template('low_stock.html', products=low_stock_items, settings=store_settings)

@app.route('/expiry_alerts')
def expiry_alerts():
    """View batches nearing expiry or already expired"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    if not db:
        return "Database connection error", 500
    
    cursor = db.cursor(dictionary=True)
    
    # Get batches expiring within 50 days using view
    cursor.execute("SELECT * FROM vw_expiring_batches ORDER BY days_left ASC")
    expiring_soon = cursor.fetchall()
    
    # Get already expired batches using view
    cursor.execute("SELECT * FROM vw_expired_batches ORDER BY days_past DESC")
    expired_items = cursor.fetchall()
    
    db.close()
    
    store_settings = get_all_settings()
    
    return render_template('expiry_alerts.html', 
                         expiring_soon=expiring_soon,
                         expired_items=expired_items,
                         settings=store_settings)

@app.route('/add_product', methods=['GET', 'POST'])
def add_product():
    """Add new product (master catalog only)"""
    if 'user_id' not in session or session.get('role') != 'owner':
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        db = get_db()
        if not db:
            flash('Database connection error', 'danger')
            return redirect(url_for('add_product'))
        
        cursor = db.cursor()
        # Only insert product master data (no batch/expiry here)
        cursor.execute("""
            INSERT INTO products (name, manufacturer, price, category, usage_type, min_stock_level)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            request.form.get('name'),
            request.form.get('manufacturer'),
            float(request.form.get('price')),
            request.form.get('category'),
            request.form.get('usage_type'),
            int(request.form.get('min_stock_level', 15))
        ))
        
        product_id = cursor.lastrowid
        
        # If batch details provided, add the first batch
        batch_number = request.form.get('batch_number', '').strip()
        if batch_number:
            cursor.execute("""
                INSERT INTO product_batches (product_id, batch_number, quantity, expiry_date, shelf_location, cost_price)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                product_id,
                batch_number,
                int(request.form.get('stock_quantity', 0)),
                request.form.get('expiry_date') or None,
                request.form.get('shelf_location') or None,
                float(request.form.get('cost_price', 0)) if request.form.get('cost_price') else None
            ))
        
        db.commit()
        db.close()
        
        flash('Product added successfully!', 'success')
        return redirect(url_for('inventory'))
    
    return render_template('add_product.html')

@app.route('/import_csv')
def import_csv_page():
    """CSV Import page"""
    if 'user_id' not in session or session.get('role') != 'owner':
        return redirect(url_for('login'))
    
    return render_template('import_csv.html')

@app.route('/download_template')
def download_template():
    """Download CSV template file"""
    if 'user_id' not in session or session.get('role') != 'owner':
        return redirect(url_for('login'))
    
    # Create CSV template in memory
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header
    writer.writerow(['name', 'manufacturer', 'price', 'stock_quantity', 'shelf_location', 'category', 'usage_type', 'min_stock_level', 'batch_number', 'expiry_date'])
    
    # Write sample data
    writer.writerow(['Paracetamol 500mg', 'Sun Pharma', '15.00', '100', 'A1', 'Pain Relief', 'Fever, Headache', '15', 'BATCH001', '2026-12-31'])
    writer.writerow(['Cetirizine 10mg', 'Cipla', '25.00', '80', 'A2', 'Antihistamine', 'Allergy', '15', 'BATCH002', '2027-06-30'])
    writer.writerow(['Amoxicillin 250mg', 'Dr. Reddy', '120.00', '50', 'B1', 'Antibiotic', 'Infection', '15', 'BATCH003', '2026-09-15'])
    
    # Create bytes buffer
    output.seek(0)
    byte_output = io.BytesIO()
    byte_output.write(output.getvalue().encode('utf-8'))
    byte_output.seek(0)
    
    return send_file(
        byte_output,
        mimetype='text/csv',
        as_attachment=True,
        download_name='products_template.csv'
    )

@app.route('/upload_csv', methods=['POST'])
def upload_csv():
    """Upload and import CSV file"""
    if 'user_id' not in session or session.get('role') != 'owner':
        return redirect(url_for('login'))
    
    if 'csv_file' not in request.files:
        flash('No file selected!', 'danger')
        return redirect(url_for('import_csv_page'))
    
    file = request.files['csv_file']
    
    if file.filename == '':
        flash('No file selected!', 'danger')
        return redirect(url_for('import_csv_page'))
    
    if not file.filename.endswith('.csv'):
        flash('Please upload a CSV file!', 'danger')
        return redirect(url_for('import_csv_page'))
    
    try:
        # Read CSV file
        stream = io.StringIO(file.stream.read().decode('UTF8'), newline=None)
        csv_reader = csv.DictReader(stream)
        
        db = get_db()
        if not db:
            flash('Database connection error!', 'danger')
            return redirect(url_for('import_csv_page'))
        
        cursor = db.cursor()
        success_count = 0
        error_count = 0
        errors = []
        
        for row_num, row in enumerate(csv_reader, start=2):
            try:
                # Validate required fields
                if not row.get('name') or not row.get('price'):
                    errors.append(f"Row {row_num}: Missing required fields (name or price)")
                    error_count += 1
                    continue
                
                # Insert product
                cursor.execute("""
                    INSERT INTO products (name, manufacturer, price, stock_quantity, 
                                        shelf_location, category, usage_type, min_stock_level,
                                        batch_number, expiry_date)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    row.get('name', ''),
                    row.get('manufacturer', ''),
                    float(row.get('price', 0)),
                    int(row.get('stock_quantity', 0)),
                    row.get('shelf_location', ''),
                    row.get('category', ''),
                    row.get('usage_type', ''),
                    int(row.get('min_stock_level', 15)),
                    row.get('batch_number', '') or None,
                    row.get('expiry_date', '') or None
                ))
                success_count += 1
                
            except Exception as e:
                errors.append(f"Row {row_num}: {str(e)}")
                error_count += 1
        
        db.commit()
        db.close()
        
        # Show results
        if success_count > 0:
            flash(f'Successfully imported {success_count} products!', 'success')
        
        if error_count > 0:
            flash(f'{error_count} rows failed to import.', 'warning')
            for error in errors[:5]:  # Show first 5 errors
                flash(error, 'danger')
        
        return redirect(url_for('inventory'))
        
    except Exception as e:
        flash(f'Error processing CSV file: {str(e)}', 'danger')
        return redirect(url_for('import_csv_page'))

@app.route('/update_stock/<int:product_id>', methods=['POST'])
def update_stock(product_id):
    """Update product stock"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # Handle empty or invalid quantity input
    quantity_str = request.form.get('quantity', '0').strip()
    if not quantity_str or quantity_str == '':
        quantity = 0
    else:
        try:
            quantity = int(quantity_str)
        except ValueError:
            flash('Invalid quantity value!', 'danger')
            return redirect(url_for('inventory'))
    
    # Don't update if quantity is 0
    if quantity == 0:
        flash('Please enter a valid quantity!', 'warning')
        return redirect(url_for('inventory'))
    
    db = get_db()
    if not db:
        flash('Database connection error', 'danger')
        return redirect(url_for('inventory'))
    
    cursor = db.cursor()
    cursor.execute("""
        UPDATE products 
        SET stock_quantity = stock_quantity + %s 
        WHERE id = %s
    """, (quantity, product_id))
    
    db.commit()
    db.close()
    
    flash('Stock updated successfully!', 'success')
    return redirect(url_for('inventory'))

@app.route('/delete_product/<int:product_id>', methods=['POST'])
def delete_product(product_id):
    """Delete a product"""
    if 'user_id' not in session or session.get('role') != 'owner':
        flash('Unauthorized access!', 'danger')
        return redirect(url_for('inventory'))
    
    db = get_db()
    if not db:
        flash('Database connection error', 'danger')
        return redirect(url_for('inventory'))
    
    try:
        cursor = db.cursor()
        # Check if product exists
        cursor.execute("SELECT name FROM products WHERE id = %s", (product_id,))
        product = cursor.fetchone()
        
        if not product:
            flash('Product not found!', 'danger')
            return redirect(url_for('inventory'))
        
        # Delete product
        cursor.execute("DELETE FROM products WHERE id = %s", (product_id,))
        db.commit()
        db.close()
        
        flash(f'Product "{product[0]}" deleted successfully!', 'success')
    except Exception as e:
        flash(f'Error deleting product: {str(e)}', 'danger')
    
    return redirect(url_for('inventory'))

@app.route('/edit_product/<int:product_id>', methods=['GET', 'POST'])
def edit_product(product_id):
    """Edit product master details (not batches)"""
    if 'user_id' not in session or session.get('role') != 'owner':
        return redirect(url_for('login'))
    
    db = get_db()
    if not db:
        flash('Database connection error', 'danger')
        return redirect(url_for('inventory'))
    
    cursor = db.cursor(dictionary=True)
    
    if request.method == 'POST':
        try:
            # Only update master product details
            cursor.execute("""
                UPDATE products 
                SET name = %s, manufacturer = %s, price = %s, 
                    category = %s, usage_type = %s, min_stock_level = %s
                WHERE id = %s
            """, (
                request.form.get('name'),
                request.form.get('manufacturer'),
                float(request.form.get('price')),
                request.form.get('category'),
                request.form.get('usage_type'),
                int(request.form.get('min_stock_level', 15)),
                product_id
            ))
            
            db.commit()
            db.close()
            
            flash('Product updated successfully!', 'success')
            return redirect(url_for('inventory'))
        except Exception as e:
            flash(f'Error updating product: {str(e)}', 'danger')
            return redirect(url_for('edit_product', product_id=product_id))
    
    # GET request - show edit form
    cursor.execute("SELECT * FROM products WHERE id = %s", (product_id,))
    product = cursor.fetchone()
    db.close()
    
    if not product:
        flash('Product not found!', 'danger')
        return redirect(url_for('inventory'))
    
    return render_template('edit_product.html', product=product)

@app.route('/view_product/<int:product_id>')
def view_product(product_id):
    """View product details"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    if not db:
        flash('Database connection error', 'danger')
        return redirect(url_for('inventory'))
    
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM products WHERE id = %s", (product_id,))
    product = cursor.fetchone()
    
    if not product:
        flash('Product not found!', 'danger')
        db.close()
        return redirect(url_for('inventory'))
    
    # Get sales statistics for this product
    cursor.execute("""
        SELECT COUNT(*) as times_sold, 
               COALESCE(SUM(quantity), 0) as total_quantity,
               COALESCE(SUM(total_amount), 0) as total_revenue
        FROM bill_items 
        WHERE product_id = %s
    """, (product_id,))
    stats = cursor.fetchone()
    
    # Get purchase records for this product
    cursor.execute("""
        SELECT sp.id, sp.purchase_number, sp.quantity, sp.unit_price, sp.total_amount,
               sp.status, sp.order_date, sp.expected_delivery_date, sp.received_date,
               s.name as supplier_name, s.company_name, s.phone
        FROM supplier_purchases sp
        JOIN suppliers s ON sp.supplier_id = s.id
        WHERE sp.product_id = %s
        ORDER BY sp.created_at DESC
    """, (product_id,))
    purchase_records = cursor.fetchall()
    
    db.close()
    
    return render_template('view_product.html', product=product, stats=stats, purchase_records=purchase_records)

# ============================================
# REPORTS ROUTES
# ============================================
@app.route('/reports')
def reports():
    """Business reports with analytics and graphs"""
    if 'user_id' not in session or session.get('role') != 'owner':
        return redirect(url_for('login'))
    
    db = get_db()
    if not db:
        return "Database connection error", 500
    
    cursor = db.cursor(dictionary=True, buffered=True)
    
    # Get selected year or default to current
    selected_year = request.args.get('year', type=int, default=datetime.now().year)
    
    # Get available years
    cursor.execute("""
        SELECT DISTINCT YEAR(bill_date) as year 
        FROM bills 
        WHERE bill_date IS NOT NULL
        ORDER BY year DESC
    """)
    years_data = cursor.fetchall()
    available_years = [row['year'] for row in years_data] if years_data else [selected_year]
    if selected_year not in available_years:
        available_years.append(selected_year)
        available_years.sort(reverse=True)
    
    # 1. Sales Trend - Last 30 days
    cursor.execute("""
        SELECT DATE(bill_date) as date, 
               COUNT(*) as bill_count,
               COALESCE(SUM(total_amount), 0) as daily_sales
        FROM bills
        WHERE bill_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
        GROUP BY DATE(bill_date)
        ORDER BY date
    """)
    sales_trend = cursor.fetchall()
    
    # 2. Monthly Revenue for selected year
    cursor.execute("""
        SELECT MONTH(bill_date) as month,
               MONTHNAME(bill_date) as month_name,
               COALESCE(SUM(total_amount), 0) as revenue
        FROM bills
        WHERE YEAR(bill_date) = %s
        GROUP BY MONTH(bill_date), MONTHNAME(bill_date)
        ORDER BY month
    """, (selected_year,))
    monthly_revenue = cursor.fetchall()
    
    # 3. Revenue by Category
    cursor.execute("""
        SELECT p.category,
               COUNT(DISTINCT bi.bill_id) as bill_count,
               SUM(bi.quantity) as total_items,
               COALESCE(SUM(bi.total_amount), 0) as revenue
        FROM bill_items bi
        JOIN products p ON bi.medicine_name = p.name
        JOIN bills b ON bi.bill_id = b.id
        WHERE YEAR(b.bill_date) = %s
        GROUP BY p.category
        ORDER BY revenue DESC
        LIMIT 10
    """, (selected_year,))
    category_revenue = cursor.fetchall()
    
    # 4. Top Selling Products
    cursor.execute("""
        SELECT bi.medicine_name,
               SUM(bi.quantity) as quantity_sold,
               COALESCE(SUM(bi.total_amount), 0) as revenue
        FROM bill_items bi
        JOIN bills b ON bi.bill_id = b.id
        WHERE YEAR(b.bill_date) = %s
        GROUP BY bi.medicine_name
        ORDER BY revenue DESC
        LIMIT 10
    """, (selected_year,))
    top_products = cursor.fetchall()
    
    # 5. Payment Method Distribution
    cursor.execute("""
        SELECT payment_method,
               COUNT(*) as transaction_count,
               COALESCE(SUM(total_amount), 0) as total_amount
        FROM bills
        WHERE YEAR(bill_date) = %s
        GROUP BY payment_method
        ORDER BY total_amount DESC
    """, (selected_year,))
    payment_methods = cursor.fetchall()
    
    # 6. Stock Status Overview (aggregate from batches, not products.stock_quantity)
    cursor.execute("""
        SELECT 
            SUM(CASE WHEN COALESCE(total_stock, 0) = 0 THEN 1 ELSE 0 END) as out_of_stock,
            SUM(CASE WHEN COALESCE(total_stock, 0) > 0 AND COALESCE(total_stock, 0) < p.min_stock_level THEN 1 ELSE 0 END) as low_stock,
            SUM(CASE WHEN COALESCE(total_stock, 0) >= p.min_stock_level THEN 1 ELSE 0 END) as adequate_stock
        FROM products p
        LEFT JOIN (
            SELECT product_id, SUM(quantity) as total_stock
            FROM product_batches
            WHERE quantity > 0
            GROUP BY product_id
        ) pb ON p.id = pb.product_id
    """)
    stock_status = cursor.fetchone()
    
    # 7. Top Customers
    cursor.execute("""
        SELECT customer_name,
               COUNT(*) as total_bills,
               COALESCE(SUM(total_amount), 0) as total_spent
        FROM bills
        WHERE YEAR(bill_date) = %s
        GROUP BY customer_name
        ORDER BY total_spent DESC
        LIMIT 10
    """, (selected_year,))
    top_customers = cursor.fetchall()
    
# Around line 848 in your app.py
# 8. Staff Performance (Updated logic to subtract refunds)
    cursor.execute("""
    SELECT u.full_name as staff_name,
           u.role,
           COUNT(b.id) as bills_processed,
           (COALESCE(SUM(b.total_amount), 0) - 
            COALESCE((SELECT SUM(r.refund_amount) FROM returns r WHERE r.processed_by = u.id AND YEAR(r.return_date) = %s), 0)
           ) as total_sales
    FROM users u
    LEFT JOIN bills b ON u.id = b.created_by AND YEAR(b.bill_date) = %s
    WHERE u.role IN ('owner', 'cashier', 'pharmacist')
    GROUP BY u.id, u.full_name, u.role
    ORDER BY total_sales DESC
    """, (selected_year, selected_year))

# ENSURE THIS VARIABLE NAME MATCHES:
    staff_performance = cursor.fetchall()
    
    # 9. Monthly Revenue & Sales Volume Trend
    cursor.execute("""
        SELECT MONTH(bill_date) as month,
               MONTHNAME(bill_date) as month_name,
               COUNT(*) as bill_count,
               COALESCE(SUM(total_amount), 0) as revenue
        FROM bills
        WHERE YEAR(bill_date) = %s
        GROUP BY MONTH(bill_date), MONTHNAME(bill_date)
        ORDER BY month
    """, (selected_year,))
    revenue_trend = cursor.fetchall()
    
    # 10. Hourly Sales Pattern
    cursor.execute("""
        SELECT HOUR(bill_date) as hour,
               COUNT(*) as bill_count,
               COALESCE(SUM(total_amount), 0) as sales
        FROM bills
        WHERE YEAR(bill_date) = %s
        GROUP BY HOUR(bill_date)
        ORDER BY hour
    """, (selected_year,))
    hourly_sales = cursor.fetchall()
    
    # 11. Expiring Products (Next 90 days)
    cursor.execute("""
        SELECT p.name as product_name,
               pb.expiry_date,
               pb.quantity as stock_quantity,
               DATEDIFF(pb.expiry_date, CURDATE()) as days_to_expiry
        FROM product_batches pb
        JOIN products p ON pb.product_id = p.id
        WHERE pb.expiry_date BETWEEN CURDATE() AND DATE_ADD(CURDATE(), INTERVAL 90 DAY)
          AND pb.quantity > 0
        ORDER BY pb.expiry_date
        LIMIT 10
    """)
    expiring_products = cursor.fetchall()
    
    # 12. Key Metrics Summary
    cursor.execute("""
        SELECT 
            COUNT(*) as total_bills,
            COALESCE(SUM(total_amount), 0) as total_revenue,
            COALESCE(AVG(total_amount), 0) as avg_bill_value
        FROM bills
        WHERE YEAR(bill_date) = %s
    """, (selected_year,))
    summary = cursor.fetchone()
    
    cursor.execute("SELECT COUNT(*) as total_products FROM products")
    summary['total_products'] = cursor.fetchone()['total_products']
    
    cursor.execute("SELECT COUNT(*) as total_customers FROM customers")
    summary['total_customers'] = cursor.fetchone()['total_customers']
    
    db.close()
    
    # Get settings for display
    store_settings = get_all_settings()
    
    return render_template('reports.html',
                         sales_trend=sales_trend,
                         monthly_revenue=monthly_revenue,
                         category_revenue=category_revenue,
                         top_products=top_products,
                         payment_methods=payment_methods,
                         stock_status=stock_status,
                         top_customers=top_customers,
                         revenue_trend=revenue_trend,
                         hourly_sales=hourly_sales,
                         expiring_products=expiring_products,
                         staff_performance=staff_performance,
                         summary=summary,
                         selected_year=selected_year,
                         available_years=available_years,
                         settings=store_settings)
from flask import render_template, redirect, url_for, session, send_file
from datetime import datetime
import io
import calendar

from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)

from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors

from reportlab.graphics.shapes import Drawing
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics.widgets.markers import makeMarker


# =====================================================
# INR FORMAT
# =====================================================

def format_inr(value):
    return "INR {:,.2f}".format(float(value))


# =====================================================
# EXECUTIVE DASHBOARD
# =====================================================

@app.route('/executive_reports')
def executive_reports():

    if 'user_id' not in session or session.get('role') != 'owner':
        return redirect(url_for('login'))

    db = get_db()
    cursor = db.cursor(dictionary=True, buffered=True)

    cursor.execute("""
        SELECT s.name, s.company_name,
               COALESCE(SUM(sp.total_amount),0) as total_purchased,
               COUNT(sp.id) as orders_placed
        FROM suppliers s
        LEFT JOIN supplier_purchases sp
        ON s.id = sp.supplier_id AND sp.status='received'
        GROUP BY s.id
        ORDER BY total_purchased DESC
    """)
    supplier_data = cursor.fetchall()


    cursor.execute("""
        SELECT 
            YEAR(bill_date) as m_year,
            MONTH(bill_date) as m_num,
            MONTHNAME(bill_date) as m_name,
            SUM(total_amount) as m_rev
        FROM bills
        WHERE bill_date >= DATE_SUB(CURDATE(), INTERVAL 12 MONTH)
        GROUP BY m_year,m_num
        ORDER BY m_year DESC,m_num DESC
    """)
    monthly_nav = cursor.fetchall()


    cursor.execute("""
        SELECT p.manufacturer,
               SUM(bi.total_amount) as mfg_revenue
        FROM bill_items bi
        JOIN products p ON bi.product_id = p.id
        GROUP BY p.manufacturer
        ORDER BY mfg_revenue DESC
        LIMIT 10
    """)
    mfg_data = cursor.fetchall()

    db.close()

    return render_template(
        'executive_reports.html',
        supplier_data=supplier_data,
        monthly_nav=monthly_nav,
        mfg_data=mfg_data
    )


# =====================================================
# MONTHLY REPORT REDIRECT
# =====================================================

@app.route('/download_monthly_report/<int:year>/<int:month>')
def download_monthly_report(year, month):
    last_day = calendar.monthrange(year, month)[1]
    from_date = f"{year}-{month:02d}-01"
    to_date = f"{year}-{month:02d}-{last_day}"

    # Use the new detailed report function
    return redirect(url_for(
        'download_detailed_sales_report', 
        period='custom',
        from_date=from_date,
        to_date=to_date
    ))


# =====================================================
# ANALYTICS PDF REPORT
# =====================================================

@app.route('/download_analytics_pdf/<report_type>')
def download_analytics_pdf(report_type):

    if 'user_id' not in session or session.get('role') != 'owner':
        return redirect(url_for('login'))

    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=45,
        leftMargin=45,
        topMargin=70,
        bottomMargin=60
    )

    elements = []
    styles = getSampleStyleSheet()

    brand_style = ParagraphStyle(
        'Brand',
        fontSize=26,
        alignment=1,
        textColor=colors.HexColor('#4f46e5'),
        fontName='Helvetica-Bold',
        spaceAfter=6
    )

    subtitle_style = ParagraphStyle(
        'Subtitle',
        fontSize=12,
        alignment=1,
        textColor=colors.grey,
        spaceAfter=15
    )

    info_style = ParagraphStyle(
        'Info',
        fontSize=10,
        alignment=1,
        textColor=colors.grey,
        spaceAfter=5
    )

    section_header = ParagraphStyle(
        'Section',
        fontSize=14,
        fontName='Helvetica-Bold',
        textColor=colors.HexColor('#4f46e5'),
        spaceBefore=20,
        spaceAfter=12
    )

    today = datetime.now().strftime("%d %B %Y")

    elements.append(Paragraph("MEDISTORE PRO ANALYTICS", brand_style))
    elements.append(Paragraph("", subtitle_style))
    elements.append(Paragraph(f"Generated : {today}", info_style))

    elements.append(Spacer(1,10))
    elements.append(HRFlowable(width="100%", thickness=1, color=colors.lightgrey))
    elements.append(Spacer(1,25))

    db = get_db()
    cursor = db.cursor(dictionary=True)

# =====================================================
# CATEGORY REPORT
# =====================================================

    if report_type == "category_gst":

        cursor.execute("""
            SELECT p.category,
                   SUM(bi.total_amount) as rev,
                   SUM(bi.total_amount*0.12) as gst
            FROM bill_items bi
            JOIN products p ON bi.product_id=p.id
            GROUP BY p.category
            ORDER BY rev DESC
        """)

        raw_data = cursor.fetchall()

        elements.append(Paragraph("Category Revenue Analysis", section_header))

        drawing = Drawing(520, 300)

        bc = VerticalBarChart()
        bc.x = 60
        bc.y = 60
        bc.height = 200
        bc.width = 400

        revenues = [float(r['rev']) for r in raw_data]
        categories = [r['category'] for r in raw_data]

        # Limit chart categories to avoid overlap
        if len(categories) > 10:
            categories = categories[:10]
            revenues = revenues[:10]

        bc.data = [revenues]
        bc.categoryAxis.categoryNames = categories

        # Fix label overlap
        bc.categoryAxis.labels.angle = 45
        bc.categoryAxis.labels.fontSize = 7
        bc.categoryAxis.labels.dy = -10

        bc.valueAxis.valueMin = 0
        bc.valueAxis.visibleGrid = True
        bc.valueAxis.gridStrokeColor = colors.lightgrey

        bc.barWidth = 18
        bc.bars[0].fillColor = colors.HexColor('#4f46e5')

        drawing.add(bc)

        elements.append(drawing)
        elements.append(Spacer(1,25))

        table_data=[["Category","Revenue (INR)","GST (INR)"]]

        for r in raw_data:
            table_data.append([
                r['category'],
                format_inr(r['rev']),
                format_inr(r['gst'])
            ])

        col_widths=[7*cm,4.5*cm,4.5*cm]

# =====================================================
# MANUFACTURER REPORT
# =====================================================

    elif report_type == "mfg_revenue":

        cursor.execute("""
            SELECT p.manufacturer,
                   SUM(bi.total_amount) as rev
            FROM bill_items bi
            JOIN products p ON bi.product_id=p.id
            GROUP BY p.manufacturer
            ORDER BY rev DESC
            LIMIT 8
        """)

        raw_data = cursor.fetchall()

        elements.append(Paragraph("Manufacturer Revenue Distribution", section_header))

        drawing = Drawing(520,300)

        pc = Pie()
        pc.x = 170
        pc.y = 50
        pc.width = 180
        pc.height = 180

        pc.data = [float(r['rev']) for r in raw_data]
        pc.labels = [r['manufacturer'] for r in raw_data]

        drawing.add(pc)

        elements.append(drawing)
        elements.append(Spacer(1,25))

        total=sum(float(r['rev']) for r in raw_data)

        table_data=[["Manufacturer","Revenue (INR)","Market Share"]]

        for r in raw_data:

            share=(float(r['rev'])/total*100) if total else 0

            table_data.append([
                r['manufacturer'],
                format_inr(r['rev']),
                f"{share:.1f}%"
            ])

        col_widths=[7*cm,4.5*cm,4.5*cm]

# =====================================================
# YEARLY SALES REPORT
# =====================================================

    elif report_type == "yearly_sales":

        cursor.execute("""
            SELECT YEAR(bill_date) as year,
                   SUM(total_amount) as revenue
            FROM bills
            GROUP BY year
            ORDER BY year
        """)

        raw_data = cursor.fetchall()

        elements.append(Paragraph("Yearly Revenue Trend", section_header))

        if not raw_data:

            elements.append(Paragraph("No yearly data available.", styles['Normal']))
            table_data=[["Year","Revenue (INR)"]]
            col_widths=[8*cm,8*cm]

        else:

            drawing=Drawing(520,300)

            lc=HorizontalLineChart()

            lc.x=60
            lc.y=60
            lc.height=200
            lc.width=400

            values=[float(r['revenue']) for r in raw_data]

            lc.data=[values]

            lc.categoryAxis.categoryNames=[str(r['year']) for r in raw_data]

            lc.valueAxis.valueMin=0
            lc.valueAxis.visibleGrid=True
            lc.valueAxis.gridStrokeColor=colors.lightgrey

            lc.lines[0].strokeColor=colors.HexColor('#4f46e5')
            lc.lines[0].strokeWidth=2

            lc.lines[0].symbol = makeMarker('FilledCircle')
            lc.lines[0].symbol.size = 6

            drawing.add(lc)

            elements.append(drawing)
            elements.append(Spacer(1,25))

            table_data=[["Year","Revenue (INR)"]]

            for r in raw_data:
                table_data.append([
                    r['year'],
                    format_inr(r['revenue'])
                ])

            col_widths=[8*cm,8*cm]

    db.close()

# =====================================================
# TABLE
# =====================================================

    table = Table(table_data, colWidths=col_widths)

    table.setStyle(TableStyle([

        ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#4f46e5')),
        ('TEXTCOLOR',(0,0),(-1,0),colors.white),

        ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),

        ('ALIGN',(1,1),(-1,-1),'RIGHT'),

        ('GRID',(0,0),(-1,-1),0.5,colors.grey),

        ('ROWBACKGROUNDS',(0,1),(-1,-1),
        [colors.white,colors.HexColor('#f3f4f6')])

    ]))

    elements.append(table)

    elements.append(Spacer(1,40))

    footer = Paragraph(
        "Generated by MediStore Pro Analytics Engine",
        ParagraphStyle(
            'Footer',
            alignment=1,
            fontSize=9,
            textColor=colors.grey
        )
    )

    elements.append(footer)

    doc.build(elements)

    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"MediStore_{report_type}.pdf",
        mimetype="application/pdf"
    )
@app.route('/download_detailed_sales_report')
def download_detailed_sales_report():
    """Generates a comprehensive report with Summary, Product Analysis, and Bill History."""
    if 'user_id' not in session or session.get('role') != 'owner':
        flash('Unauthorized access!', 'danger')
        return redirect(url_for('login'))

    period = request.args.get('period', 'today')
    from_date = request.args.get('from_date')
    to_date = request.args.get('to_date')

    db = get_db()
    if not db:
        flash('Database connection error', 'danger')
        return redirect(url_for('reports'))

    cursor = db.cursor(dictionary=True)

    # --- Date Range Logic ---
    if period == 'today':
        date_condition = "DATE(bill_date) = CURDATE()"
        report_period = datetime.now().strftime('%d %B %Y')
    elif period == 'month':
        date_condition = "MONTH(bill_date) = MONTH(CURDATE()) AND YEAR(bill_date) = YEAR(CURDATE())"
        report_period = datetime.now().strftime('%B %Y')
    elif period == 'year':
        date_condition = "YEAR(bill_date) = YEAR(CURDATE())"
        report_period = datetime.now().strftime('%Y')
    elif period == 'custom' and from_date and to_date:
        date_condition = f"DATE(bill_date) BETWEEN '{from_date}' AND '{to_date}'"
        report_period = f"{from_date} to {to_date}"
    else:
        date_condition = "DATE(bill_date) = CURDATE()"
        report_period = datetime.now().strftime('%d %B %Y')

    # --- Data Queries ---
    # 1. Financial Summary
    cursor.execute(f"SELECT COUNT(*) as total_bills, COALESCE(SUM(total_amount),0) as total_revenue, COALESCE(AVG(total_amount),0) as avg_bill, COALESCE(SUM(gst),0) as total_gst FROM bills WHERE {date_condition}")
    summary = cursor.fetchone()

    # 2. Product Analysis (Top Sellers)
    cursor.execute(f"""
        SELECT bi.medicine_name, SUM(bi.quantity) as total_quantity, SUM(bi.total_amount) as revenue 
        FROM bill_items bi JOIN bills b ON bi.bill_id=b.id 
        WHERE {date_condition} GROUP BY bi.medicine_name ORDER BY revenue DESC LIMIT 10
    """)
    top_products = cursor.fetchall()

    # 3. Bill History (Individual Transactions)
    cursor.execute(f"SELECT bill_number, bill_date, customer_name, payment_method, total_amount FROM bills WHERE {date_condition} ORDER BY bill_date DESC")
    bill_history = cursor.fetchall()
    db.close()

    # --- PDF Generation ---
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=1.5*cm, leftMargin=1.5*cm, topMargin=1.5*cm, bottomMargin=1.5*cm)
    elements = []
    styles = getSampleStyleSheet()

    # Custom Styles for Spacing
    styles.add(ParagraphStyle(name='MainTitle', parent=styles['Title'], fontSize=22, spaceAfter=10))
    styles.add(ParagraphStyle(name='SubTitle', parent=styles['Normal'], fontSize=11, alignment=1, spaceAfter=30, textColor=colors.grey))
    styles.add(ParagraphStyle(name='CustomHeading', parent=styles['Heading2'], spaceBefore=20, spaceAfter=10, textColor=colors.HexColor('#4f46e5')))

    # 1. Header Section
    elements.append(Paragraph("Detailed Business Analytics Report", styles['MainTitle']))
    # Added Date and Time to the subtitle
    elements.append(Paragraph(f"Period: {report_period} | Generated: {datetime.now().strftime('%d-%m-%Y %H:%M')}", styles['SubTitle']))
    elements.append(HRFlowable(width="100%", thickness=1.5, color=colors.black))
    elements.append(Spacer(1, 20))

    # 2. BILLING SUMMARY (Section 1)
    elements.append(Paragraph("I. Financial Summary", styles['CustomHeading']))
    metrics = [
        ["Total Revenue", "Total Bills", "Average Bill", "GST Collected"],
        [f"INR {summary['total_revenue']:,.2f}", str(summary['total_bills']), f"INR {summary['avg_bill']:,.2f}", f"INR {summary['total_gst']:,.2f}"]
    ]
    t_metrics = Table(metrics, colWidths=[4.5*cm]*4)
    t_metrics.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#4f46e5')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
        ('TOPPADDING', (0,0), (-1,-1), 10),
    ]))
    elements.append(t_metrics)

    # 3. PRODUCT ANALYSIS (Section 2)
    if top_products:
        elements.append(Paragraph("II. Product Performance Analysis", styles['CustomHeading']))
        prod_data = [["Medicine Name", "Quantity Sold", "Revenue Contribution"]]
        for p in top_products:
            prod_data.append([p['medicine_name'], str(p['total_quantity']), f"INR {p['revenue']:,.2f}"])
        
        t_prod = Table(prod_data, colWidths=[9*cm, 4*cm, 5*cm])
        t_prod.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#f59e0b')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#fff7ed')]),
            ('ALIGN', (2, 1), (2, -1), 'RIGHT'),
        ]))
        elements.append(t_prod)

    # 4. TRANSACTION HISTORY (Section 3)
    elements.append(Paragraph("III. Detailed Transaction History", styles['CustomHeading']))
    history_data = [["Bill No", "Date & Time", "Customer", "Method", "Amount"]]
    for b in bill_history:
        history_data.append([
            b['bill_number'],
            b['bill_date'].strftime('%d-%m %H:%M'), # Date and Time combined
            b['customer_name'][:20],
            b['payment_method'].upper(),
            f"INR {float(b['total_amount']):,.2f}" # Removed symbol, added INR
        ])
    
    t_history = Table(history_data, colWidths=[3.5*cm, 3.5*cm, 5.5*cm, 2.5*cm, 3*cm])
    t_history.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1f2937')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('GRID', (0,0), (-1,-1), 0.5, colors.lightgrey),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f3f4f6')]),
        ('ALIGN', (4, 0), (4, -1), 'RIGHT'),
        ('FONTSIZE', (0,0), (-1,-1), 9)
    ]))
    elements.append(t_history)

    doc.build(elements)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name=f"Detailed_Sales_Report_{period}.pdf", mimetype="application/pdf")

# ============================================
# NEW COMPREHENSIVE REPORTS ROUTES
# ============================================

@app.route('/api/report/daily_sales_summary')
def api_daily_sales_summary():
    """Daily sales breakdown by hour and payment method"""
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    
    db = get_db()
    if not db:
        return jsonify({'error': 'Database error'}), 500
    
    cursor = db.cursor(dictionary=True)
    
    # Hourly breakdown
    cursor.execute("""
        SELECT HOUR(bill_date) as hour, 
               COUNT(*) as bill_count,
               SUM(total_amount) as revenue,
               SUM(CASE WHEN payment_method='cash' THEN total_amount ELSE 0 END) as cash_amount,
               SUM(CASE WHEN payment_method='upi' THEN total_amount ELSE 0 END) as upi_amount
        FROM bills
        WHERE DATE(bill_date) = %s
        GROUP BY HOUR(bill_date)
        ORDER BY hour
    """, (date,))
    hourly_data = cursor.fetchall()
    
    # Payment method summary
    cursor.execute("""
        SELECT payment_method, 
               COUNT(*) as count,
               SUM(total_amount) as total
        FROM bills
        WHERE DATE(bill_date) = %s
        GROUP BY payment_method
    """, (date,))
    payment_summary = cursor.fetchall()
    
    # Staff performance
    cursor.execute("""
        SELECT u.full_name as staff_name,
               COUNT(b.id) as bills_processed,
               SUM(b.total_amount) as revenue
        FROM bills b
        JOIN users u ON b.created_by = u.id
        WHERE DATE(b.bill_date) = %s
        GROUP BY u.id, u.full_name
        ORDER BY revenue DESC
    """, (date,))
    staff_performance = cursor.fetchall()
    
    db.close()
    
    return jsonify({
        'hourly_data': hourly_data,
        'payment_summary': payment_summary,
        'staff_performance': staff_performance
    })

@app.route('/api/report/sales_trend')
def api_sales_trend():
    """Sales trend analysis over time"""
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    period = request.args.get('period', '30')  # days
    
    db = get_db()
    if not db:
        return jsonify({'error': 'Database error'}), 500
    
    cursor = db.cursor(dictionary=True)
    
    cursor.execute(f"""
        SELECT DATE(bill_date) as date,
               COUNT(*) as bill_count,
               SUM(total_amount) as revenue,
               AVG(total_amount) as avg_bill_value
        FROM bills
        WHERE bill_date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
        GROUP BY DATE(bill_date)
        ORDER BY date
    """, (period,))
    trend_data = cursor.fetchall()
    
    # Calculate growth
    cursor.execute("""
        SELECT SUM(total_amount) as current_period
        FROM bills
        WHERE bill_date >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
    """)
    current_week = cursor.fetchone()
    
    cursor.execute("""
        SELECT SUM(total_amount) as previous_period
        FROM bills
        WHERE bill_date >= DATE_SUB(CURDATE(), INTERVAL 14 DAY)
          AND bill_date < DATE_SUB(CURDATE(), INTERVAL 7 DAY)
    """)
    previous_week = cursor.fetchone()
    
    db.close()
    
    growth_rate = 0
    if previous_week['previous_period'] and previous_week['previous_period'] > 0:
        growth_rate = ((current_week['current_period'] - previous_week['previous_period']) / 
                      previous_week['previous_period'] * 100)
    
    return jsonify({
        'trend_data': trend_data,
        'growth_rate': round(growth_rate, 2)
    })

@app.route('/api/report/payment_method_analysis')
def api_payment_method_analysis():
    """Payment method breakdown and analysis"""
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    from_date = request.args.get('from_date', (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d'))
    to_date = request.args.get('to_date', datetime.now().strftime('%Y-%m-%d'))
    
    db = get_db()
    if not db:
        return jsonify({'error': 'Database error'}), 500
    
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT payment_method,
               COUNT(*) as transaction_count,
               SUM(total_amount) as total_amount,
               AVG(total_amount) as avg_amount,
               payment_status
        FROM bills
        WHERE DATE(bill_date) BETWEEN %s AND %s
          AND payment_status = 'completed'
        GROUP BY payment_method
    """, (from_date, to_date))
    payment_data = cursor.fetchall()
    
    # UPI approval time analysis
    cursor.execute("""
        SELECT AVG(TIMESTAMPDIFF(MINUTE, bill_date, payment_approved_at)) as avg_approval_time
        FROM bills
        WHERE payment_method = 'upi' 
          AND payment_status = 'completed'
          AND payment_approved_at IS NOT NULL
          AND DATE(bill_date) BETWEEN %s AND %s
    """, (from_date, to_date))
    approval_time = cursor.fetchone()
    
    db.close()
    
    return jsonify({
        'payment_data': payment_data,
        'avg_approval_time': approval_time['avg_approval_time'] or 0
    })

@app.route('/api/report/revenue_by_category')
def api_revenue_by_category():
    """Revenue breakdown by product category"""
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    from_date = request.args.get('from_date', (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d'))
    to_date = request.args.get('to_date', datetime.now().strftime('%Y-%m-%d'))
    
    db = get_db()
    if not db:
        return jsonify({'error': 'Database error'}), 500
    
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT COALESCE(p.category, 'Uncategorized') as category,
               COUNT(DISTINCT bi.id) as item_count,
               SUM(bi.quantity) as total_quantity,
               SUM(bi.total_amount) as revenue
        FROM bill_items bi
        LEFT JOIN products p ON bi.product_id = p.id
        JOIN bills b ON bi.bill_id = b.id
        WHERE DATE(b.bill_date) BETWEEN %s AND %s
        GROUP BY p.category
        ORDER BY revenue DESC
    """, (from_date, to_date))
    category_data = cursor.fetchall()
    
    # Calculate total revenue for percentage
    cursor.execute("""
        SELECT SUM(bi.total_amount) as total_revenue
        FROM bill_items bi
        JOIN bills b ON bi.bill_id = b.id
        WHERE DATE(b.bill_date) BETWEEN %s AND %s
    """, (from_date, to_date))
    total_revenue = cursor.fetchone()['total_revenue'] or 0
    
    # Add percentage to each category
    for category in category_data:
        category['percentage'] = (float(category['revenue']) / float(total_revenue) * 100) if total_revenue > 0 else 0
    
    db.close()
    
    return jsonify({
        'category_data': category_data,
        'total_revenue': total_revenue
    })

@app.route('/api/report/stock_valuation')
def api_stock_valuation():
    """Current inventory valuation"""
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    db = get_db()
    if not db:
        return jsonify({'error': 'Database error'}), 500
    
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT p.id, p.name, p.category, p.manufacturer,
               COALESCE(SUM(pb.quantity), 0) as total_quantity,
               p.price as selling_price,
               COALESCE(AVG(pb.cost_price), 0) as avg_cost_price,
               COALESCE(SUM(pb.quantity), 0) * p.price as stock_value,
               COALESCE(SUM(pb.quantity * pb.cost_price), 0) as cost_value
        FROM products p
        LEFT JOIN product_batches pb ON p.id = pb.product_id AND pb.quantity > 0
        GROUP BY p.id
        ORDER BY stock_value DESC
    """)
    stock_data = cursor.fetchall()
    
    # Total valuation
    total_selling_value = sum(float(item['stock_value']) for item in stock_data)
    total_cost_value = sum(float(item['cost_value']) for item in stock_data)
    potential_profit = total_selling_value - total_cost_value
    
    db.close()
    
    return jsonify({
        'stock_data': stock_data,
        'total_selling_value': total_selling_value,
        'total_cost_value': total_cost_value,
        'potential_profit': potential_profit
    })

@app.route('/api/report/fast_slow_moving')
def api_fast_slow_moving():
    """Fast moving vs slow moving products"""
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    days = int(request.args.get('days', 30))
    
    db = get_db()
    if not db:
        return jsonify({'error': 'Database error'}), 500
    
    cursor = db.cursor(dictionary=True)
    
    # Fast moving (top sellers)
    cursor.execute("""
        SELECT bi.medicine_name, p.category,
               SUM(bi.quantity) as total_sold,
               COUNT(DISTINCT bi.bill_id) as transaction_count,
               SUM(bi.total_amount) as revenue,
               COALESCE(SUM(pb.quantity), 0) as current_stock
        FROM bill_items bi
        LEFT JOIN products p ON bi.product_id = p.id
        LEFT JOIN product_batches pb ON p.id = pb.product_id AND pb.quantity > 0
        JOIN bills b ON bi.bill_id = b.id
        WHERE b.bill_date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
        GROUP BY bi.medicine_name, p.category
        ORDER BY total_sold DESC
        LIMIT 20
    """, (days,))
    fast_moving = cursor.fetchall()
    
    # Slow moving (products with sales < 5 in period)
    cursor.execute("""
        SELECT p.name, p.category, p.manufacturer,
               COALESCE(SUM(bi.quantity), 0) as total_sold,
               COALESCE(SUM(pb.quantity), 0) as current_stock,
               p.price * COALESCE(SUM(pb.quantity), 0) as locked_value
        FROM products p
        LEFT JOIN product_batches pb ON p.id = pb.product_id AND pb.quantity > 0
        LEFT JOIN bill_items bi ON p.id = bi.product_id 
            AND bi.bill_id IN (
                SELECT id FROM bills WHERE bill_date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
            )
        GROUP BY p.id
        HAVING total_sold < 5 AND current_stock > 0
        ORDER BY locked_value DESC
        LIMIT 20
    """, (days,))
    slow_moving = cursor.fetchall()
    
    db.close()
    
    return jsonify({
        'fast_moving': fast_moving,
        'slow_moving': slow_moving
    })

@app.route('/api/report/batch_expiry_dashboard')
def api_batch_expiry_dashboard():
    """Enhanced batch expiry analysis"""
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    db = get_db()
    if not db:
        return jsonify({'error': 'Database error'}), 500
    
    cursor = db.cursor(dictionary=True)
    
    # Expired batches
    cursor.execute("""
        SELECT p.name, pb.batch_number, pb.quantity, pb.expiry_date,
               DATEDIFF(CURDATE(), pb.expiry_date) as days_past,
               pb.quantity * p.price as value_lost
        FROM product_batches pb
        JOIN products p ON pb.product_id = p.id
        WHERE pb.expiry_date < CURDATE() AND pb.quantity > 0
        ORDER BY value_lost DESC
    """)
    expired = cursor.fetchall()
    
    # Expiring in 30 days
    cursor.execute("""
        SELECT p.name, p.category, pb.batch_number, pb.quantity, pb.expiry_date,
               DATEDIFF(pb.expiry_date, CURDATE()) as days_left,
               pb.quantity * p.price as value_at_risk
        FROM product_batches pb
        JOIN products p ON pb.product_id = p.id
        WHERE pb.expiry_date BETWEEN CURDATE() AND DATE_ADD(CURDATE(), INTERVAL 30 DAY)
          AND pb.quantity > 0
        ORDER BY days_left ASC
    """)
    expiring_30 = cursor.fetchall()
    
    # Expiring in 60-90 days
    cursor.execute("""
        SELECT p.name, pb.batch_number, pb.quantity, pb.expiry_date,
               DATEDIFF(pb.expiry_date, CURDATE()) as days_left,
               pb.quantity * p.price as value_at_risk
        FROM product_batches pb
        JOIN products p ON pb.product_id = p.id
        WHERE pb.expiry_date BETWEEN DATE_ADD(CURDATE(), INTERVAL 31 DAY) 
          AND DATE_ADD(CURDATE(), INTERVAL 90 DAY)
          AND pb.quantity > 0
        ORDER BY days_left ASC
    """)
    expiring_90 = cursor.fetchall()
    
    db.close()
    
    total_expired_value = sum(float(item['value_lost']) for item in expired)
    total_at_risk_30 = sum(float(item['value_at_risk']) for item in expiring_30)
    total_at_risk_90 = sum(float(item['value_at_risk']) for item in expiring_90)
    
    return jsonify({
        'expired': expired,
        'expiring_30': expiring_30,
        'expiring_90': expiring_90,
        'total_expired_value': total_expired_value,
        'total_at_risk_30': total_at_risk_30,
        'total_at_risk_90': total_at_risk_90
    })

@app.route('/api/report/stock_movement')
def api_stock_movement():
    """Product stock movement tracking"""
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    from_date = request.args.get('from_date', (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d'))
    to_date = request.args.get('to_date', datetime.now().strftime('%Y-%m-%d'))
    
    db = get_db()
    if not db:
        return jsonify({'error': 'Database error'}), 500
    
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT p.name, p.category,
               SUM(CASE WHEN bt.transaction_type='purchase' THEN bt.quantity_change ELSE 0 END) as purchased,
               SUM(CASE WHEN bt.transaction_type='sale' THEN ABS(bt.quantity_change) ELSE 0 END) as sold,
               SUM(CASE WHEN bt.transaction_type='return' THEN bt.quantity_change ELSE 0 END) as returned,
               COALESCE(SUM(pb.quantity), 0) as current_stock
        FROM products p
        LEFT JOIN product_batches pb ON p.id = pb.product_id
        LEFT JOIN batch_transactions bt ON pb.id = bt.batch_id 
            AND DATE(bt.transaction_date) BETWEEN %s AND %s
        GROUP BY p.id
        HAVING purchased > 0 OR sold > 0 OR returned > 0
        ORDER BY sold DESC
    """, (from_date, to_date))
    movement_data = cursor.fetchall()
    
    db.close()
    
    return jsonify({'movement_data': movement_data})

@app.route('/api/report/supplier_performance')
def api_supplier_performance():
    """Supplier delivery and quality performance"""
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    db = get_db()
    if not db:
        return jsonify({'error': 'Database error'}), 500
    
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT s.name, s.company_name, s.phone,
               COUNT(sp.id) as total_orders,
               COUNT(CASE WHEN sp.status='received' THEN 1 END) as completed_orders,
               SUM(CASE WHEN sp.status='received' THEN sp.total_amount ELSE 0 END) as total_purchase_value
        FROM suppliers s
        LEFT JOIN supplier_purchases sp ON s.id = sp.supplier_id
        GROUP BY s.id
        ORDER BY total_purchase_value DESC
    """)
    supplier_data = cursor.fetchall()
    
    db.close()
    
    return jsonify({'supplier_data': supplier_data})

@app.route('/api/report/top_customers')
def api_top_customers():
    """Top customers by purchase value"""
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    period = int(request.args.get('days', 90))
    
    db = get_db()
    if not db:
        return jsonify({'error': 'Database error'}), 500
    
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT c.name, c.phone, c.email,
               COUNT(b.id) as total_purchases,
               SUM(b.total_amount) as total_spent,
               MAX(b.bill_date) as last_purchase_date,
               DATEDIFF(CURDATE(), MAX(b.bill_date)) as days_since_last_purchase
        FROM customers c
        JOIN bills b ON c.id = b.customer_id
        WHERE b.bill_date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
          AND c.name != 'Walk-in Customer'
        GROUP BY c.id
        ORDER BY total_spent DESC
        LIMIT 50
    """, (period,))
    top_customers = cursor.fetchall()
    
    db.close()
    
    return jsonify({'top_customers': top_customers})

@app.route('/api/report/customer_ratio')
def api_customer_ratio():
    """Walk-in vs registered customer analysis"""
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    from_date = request.args.get('from_date', (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d'))
    to_date = request.args.get('to_date', datetime.now().strftime('%Y-%m-%d'))
    
    db = get_db()
    if not db:
        return jsonify({'error': 'Database error'}), 500
    
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT 
            COUNT(CASE WHEN customer_name='Walk-in Customer' THEN 1 END) as walkin_count,
            SUM(CASE WHEN customer_name='Walk-in Customer' THEN total_amount ELSE 0 END) as walkin_revenue,
            COUNT(CASE WHEN customer_name!='Walk-in Customer' THEN 1 END) as registered_count,
            SUM(CASE WHEN customer_name!='Walk-in Customer' THEN total_amount ELSE 0 END) as registered_revenue
        FROM bills
        WHERE DATE(bill_date) BETWEEN %s AND %s
    """, (from_date, to_date))
    ratio_data = cursor.fetchone()
    
    db.close()
    
    return jsonify({'ratio_data': ratio_data})

@app.route('/api/report/staff_sales_comparison')
def api_staff_sales_comparison():
    """Staff performance comparison"""
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    from_date = request.args.get('from_date', (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d'))
    to_date = request.args.get('to_date', datetime.now().strftime('%Y-%m-%d'))
    
    db = get_db()
    if not db:
        return jsonify({'error': 'Database error'}), 500
    
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT u.full_name, u.role,
               COUNT(b.id) as bills_processed
        FROM users u
        LEFT JOIN bills b ON u.id = b.created_by 
            AND DATE(b.bill_date) BETWEEN %s AND %s
        GROUP BY u.id
        ORDER BY bills_processed DESC
    """, (from_date, to_date))
    staff_data = cursor.fetchall()
    
    db.close()
    
    return jsonify({'staff_data': staff_data})

@app.route('/api/report/billing_speed')
def api_billing_speed():
    """Billing speed analysis by staff"""
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    days = int(request.args.get('days', 7))
    
    db = get_db()
    if not db:
        return jsonify({'error': 'Database error'}), 500
    
    cursor = db.cursor(dictionary=True)
    
    # Average items per bill and estimated time (based on items count)
    cursor.execute("""
        SELECT u.full_name,
               COUNT(b.id) as total_bills,
               SUM((SELECT COUNT(*) FROM bill_items WHERE bill_id = b.id)) as total_items,
               AVG((SELECT COUNT(*) FROM bill_items WHERE bill_id = b.id)) as avg_items_per_bill,
               COUNT(b.id) / COUNT(DISTINCT DATE(b.bill_date)) as bills_per_day
        FROM users u
        JOIN bills b ON u.id = b.created_by
        WHERE b.bill_date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
        GROUP BY u.id
        ORDER BY bills_per_day DESC
    """, (days,))
    speed_data = cursor.fetchall()
    
    db.close()
    
    return jsonify({'speed_data': speed_data})

@app.route('/api/report/upi_approval_report')
def api_upi_approval_report():
    """UPI payment approval tracking"""
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    from_date = request.args.get('from_date', (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d'))
    to_date = request.args.get('to_date', datetime.now().strftime('%Y-%m-%d'))
    
    db = get_db()
    if not db:
        return jsonify({'error': 'Database error'}), 500
    
    cursor = db.cursor(dictionary=True)
    
    # Pending approvals
    cursor.execute("""
        SELECT b.id, b.bill_number, b.customer_name, b.total_amount, b.bill_date,
               u.full_name as created_by_name,
               TIMESTAMPDIFF(MINUTE, b.bill_date, NOW()) as pending_minutes
        FROM bills b
        JOIN users u ON b.created_by = u.id
        WHERE b.payment_method = 'upi' 
          AND b.payment_status = 'pending'
          AND DATE(b.bill_date) BETWEEN %s AND %s
        ORDER BY b.bill_date DESC
    """, (from_date, to_date))
    pending = cursor.fetchall()
    
    # Approved payments with approval time
    cursor.execute("""
        SELECT b.bill_number, b.customer_name, b.total_amount, b.bill_date,
               b.payment_approved_at,
               TIMESTAMPDIFF(MINUTE, b.bill_date, b.payment_approved_at) as approval_time_minutes,
               u1.full_name as created_by,
               u2.full_name as approved_by
        FROM bills b
        JOIN users u1 ON b.created_by = u1.id
        LEFT JOIN users u2 ON b.payment_approved_by = u2.id
        WHERE b.payment_method = 'upi' 
          AND b.payment_status = 'completed'
          AND DATE(b.bill_date) BETWEEN %s AND %s
        ORDER BY approval_time_minutes DESC
        LIMIT 50
    """, (from_date, to_date))
    approved = cursor.fetchall()
    
    db.close()
    
    return jsonify({
        'pending': pending,
        'approved': approved
    })

@app.route('/api/report/purchase_order_status')
def api_purchase_order_status():
    """Purchase order status dashboard"""
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    db = get_db()
    if not db:
        return jsonify({'error': 'Database error'}), 500
    
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT sp.purchase_number, sp.medicine_name, sp.quantity, sp.total_amount,
               sp.status, sp.order_date, sp.expected_delivery_date, sp.received_date,
               s.name as supplier_name, s.phone,
               CASE 
                   WHEN sp.status='ordered' AND sp.expected_delivery_date < CURDATE() 
                   THEN 'overdue'
                   WHEN sp.status='ordered' THEN 'pending'
                   ELSE 'completed'
               END as delivery_status
        FROM supplier_purchases sp
        JOIN suppliers s ON sp.supplier_id = s.id
        ORDER BY sp.order_date DESC
        LIMIT 100
    """)
    orders = cursor.fetchall()
    
    # Summary
    cursor.execute("""
        SELECT 
            COUNT(CASE WHEN status='ordered' THEN 1 END) as ordered,
            COUNT(CASE WHEN status='received' THEN 1 END) as received,
            SUM(CASE WHEN status='ordered' THEN total_amount ELSE 0 END) as pending_value
        FROM supplier_purchases
    """)
    summary = cursor.fetchone()
    
    db.close()
    
    return jsonify({
        'orders': orders,
        'summary': summary
    })

@app.route('/api/report/purchase_vs_sales')
def api_purchase_vs_sales():
    """Purchase vs sales analysis"""
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    from_date = request.args.get('from_date', (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d'))
    to_date = request.args.get('to_date', datetime.now().strftime('%Y-%m-%d'))
    
    db = get_db()
    if not db:
        return jsonify({'error': 'Database error'}), 500
    
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT p.name, p.category,
               COALESCE(SUM(sp.quantity), 0) as total_purchased,
               COALESCE(SUM(bi.quantity), 0) as total_sold,
               COALESCE(SUM(sp.quantity), 0) - COALESCE(SUM(bi.quantity), 0) as difference,
               COALESCE(SUM(pb.quantity), 0) as current_stock
        FROM products p
        LEFT JOIN supplier_purchases sp ON p.id = sp.product_id 
            AND sp.status='received' 
            AND DATE(sp.received_date) BETWEEN %s AND %s
        LEFT JOIN bill_items bi ON p.id = bi.product_id
            AND bi.bill_id IN (
                SELECT id FROM bills WHERE DATE(bill_date) BETWEEN %s AND %s
            )
        LEFT JOIN product_batches pb ON p.id = pb.product_id AND pb.quantity > 0
        GROUP BY p.id
        HAVING total_purchased > 0
        ORDER BY difference DESC
    """, (from_date, to_date, from_date, to_date))
    comparison_data = cursor.fetchall()
    
    db.close()
    
    return jsonify({'comparison_data': comparison_data})

@app.route('/api/report/supplier_purchase_summary')
def api_supplier_purchase_summary():
    """Supplier-wise purchase summary"""
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    from_date = request.args.get('from_date', (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d'))
    to_date = request.args.get('to_date', datetime.now().strftime('%Y-%m-%d'))
    
    db = get_db()
    if not db:
        return jsonify({'error': 'Database error'}), 500
    
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT s.name, s.company_name, s.phone, s.gstin,
               COUNT(sp.id) as order_count,
               SUM(sp.total_amount) as total_purchase_value,
               AVG(sp.total_amount) as avg_order_value,
               COUNT(CASE WHEN sp.status='received' THEN 1 END) as completed_orders,
               COUNT(CASE WHEN sp.status='ordered' THEN 1 END) as pending_orders
        FROM suppliers s
        LEFT JOIN supplier_purchases sp ON s.id = sp.supplier_id
            AND DATE(sp.order_date) BETWEEN %s AND %s
        GROUP BY s.id
        HAVING order_count > 0
        ORDER BY total_purchase_value DESC
    """, (from_date, to_date))
    supplier_summary = cursor.fetchall()
    
    db.close()
    
    return jsonify({'supplier_summary': supplier_summary})

@app.route('/api/report/gst_summary')
def api_gst_summary():
    """GST collection and liability summary"""
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    from_date = request.args.get('from_date', (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d'))
    to_date = request.args.get('to_date', datetime.now().strftime('%Y-%m-%d'))
    
    db = get_db()
    if not db:
        return jsonify({'error': 'Database error'}), 500
    
    cursor = db.cursor(dictionary=True)
    
    # GST collected from sales
    cursor.execute("""
        SELECT 
            SUM(subtotal) as total_taxable_value,
            SUM(gst) as total_gst_collected,
            SUM(total_amount) as total_with_gst,
            COUNT(*) as total_bills
        FROM bills
        WHERE DATE(bill_date) BETWEEN %s AND %s
    """, (from_date, to_date))
    sales_gst = cursor.fetchone()
    
    # Daily breakdown
    cursor.execute("""
        SELECT DATE(bill_date) as date,
               SUM(subtotal) as taxable_value,
               SUM(gst) as gst_amount,
               COUNT(*) as bill_count
        FROM bills
        WHERE DATE(bill_date) BETWEEN %s AND %s
        GROUP BY DATE(bill_date)
        ORDER BY date DESC
    """, (from_date, to_date))
    daily_gst = cursor.fetchall()
    
    db.close()
    
    return jsonify({
        'sales_gst': sales_gst,
        'daily_gst': daily_gst
    })

@app.route('/api/report/cash_collection')
def api_cash_collection():
    """Day-wise cash collection report"""
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    from_date = request.args.get('from_date', (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d'))
    to_date = request.args.get('to_date', datetime.now().strftime('%Y-%m-%d'))
    
    db = get_db()
    if not db:
        return jsonify({'error': 'Database error'}), 500
    
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT DATE(bill_date) as date,
               SUM(CASE WHEN payment_method='cash' THEN total_amount ELSE 0 END) as cash_amount,
               SUM(CASE WHEN payment_method='upi' THEN total_amount ELSE 0 END) as upi_amount,
               SUM(total_amount) as total_amount,
               COUNT(*) as total_bills
        FROM bills
        WHERE DATE(bill_date) BETWEEN %s AND %s
        GROUP BY DATE(bill_date)
        ORDER BY date DESC
    """, (from_date, to_date))
    daily_collection = cursor.fetchall()
    
    db.close()
    
    return jsonify({'daily_collection': daily_collection})

@app.route('/api/report/demand_forecasting')
def api_demand_forecasting():
    """Product demand forecasting based on historical data"""
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    db = get_db()
    if not db:
        return jsonify({'error': 'Database error'}), 500
    
    cursor = db.cursor(dictionary=True)
    
    # Calculate average monthly demand
    cursor.execute("""
        SELECT bi.medicine_name, p.category,
               COUNT(DISTINCT MONTH(b.bill_date)) as months_sold,
               SUM(bi.quantity) / COUNT(DISTINCT MONTH(b.bill_date)) as avg_monthly_demand,
               COALESCE(SUM(pb.quantity), 0) as current_stock,
               CEIL((COALESCE(SUM(pb.quantity), 0) / 
                   (SUM(bi.quantity) / COUNT(DISTINCT MONTH(b.bill_date))))) as months_of_stock
        FROM bill_items bi
        JOIN bills b ON bi.bill_id = b.id
        LEFT JOIN products p ON bi.product_id = p.id
        LEFT JOIN product_batches pb ON p.id = pb.product_id AND pb.quantity > 0
        WHERE b.bill_date >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH)
        GROUP BY bi.medicine_name, p.category
        HAVING avg_monthly_demand > 0
        ORDER BY avg_monthly_demand DESC
        LIMIT 50
    """)
    forecast_data = cursor.fetchall()
    
    db.close()
    
    return jsonify({'forecast_data': forecast_data})

@app.route('/api/report/seasonal_analysis')
def api_seasonal_analysis():
    """Seasonal product sales analysis"""
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    db = get_db()
    if not db:
        return jsonify({'error': 'Database error'}), 500
    
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT bi.medicine_name,
               MONTH(b.bill_date) as month,
               MONTHNAME(b.bill_date) as month_name,
               SUM(bi.quantity) as quantity_sold,
               SUM(bi.total_amount) as revenue
        FROM bill_items bi
        JOIN bills b ON bi.bill_id = b.id
        WHERE b.bill_date >= DATE_SUB(CURDATE(), INTERVAL 12 MONTH)
        GROUP BY bi.medicine_name, MONTH(b.bill_date), MONTHNAME(b.bill_date)
        ORDER BY bi.medicine_name, month
    """)
    seasonal_data = cursor.fetchall()
    
    db.close()
    
    return jsonify({'seasonal_data': seasonal_data})

@app.route('/api/report/near_expiry_impact')
def api_near_expiry_impact():
    """Near-expiry product sales impact analysis"""
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    db = get_db()
    if not db:
        return jsonify({'error': 'Database error'}), 500
    
    cursor = db.cursor(dictionary=True)
    
    # Products sold from batches near expiry
    cursor.execute("""
        SELECT p.name, pb.batch_number, pb.expiry_date,
               pb.quantity as remaining_quantity,
               pb.quantity * p.price as value_at_risk,
               DATEDIFF(pb.expiry_date, CURDATE()) as days_to_expiry
        FROM product_batches pb
        JOIN products p ON pb.product_id = p.id
        WHERE pb.quantity > 0
          AND pb.expiry_date BETWEEN CURDATE() AND DATE_ADD(CURDATE(), INTERVAL 60 DAY)
        ORDER BY days_to_expiry ASC
    """)
    near_expiry = cursor.fetchall()
    
    db.close()
    
    return jsonify({'near_expiry': near_expiry})

@app.route('/api/report/stockout_report')
def api_stockout_report():
    """Stock-out and potential lost sales report"""
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    days = int(request.args.get('days', 30))
    
    db = get_db()
    if not db:
        return jsonify({'error': 'Database error'}), 500
    
    cursor = db.cursor(dictionary=True)
    
    # Products currently out of stock that had recent sales
    cursor.execute("""
        SELECT p.name, p.category, p.manufacturer,
               SUM(bi.quantity) as quantity_sold_before,
               SUM(bi.total_amount) as revenue_before,
               COALESCE(SUM(pb.quantity), 0) as current_stock,
               DATEDIFF(CURDATE(), MAX(b.bill_date)) as days_out_of_stock
        FROM products p
        LEFT JOIN product_batches pb ON p.id = pb.product_id AND pb.quantity > 0
        LEFT JOIN bill_items bi ON p.id = bi.product_id
        LEFT JOIN bills b ON bi.bill_id = b.id 
            AND b.bill_date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
        GROUP BY p.id
        HAVING current_stock = 0 AND quantity_sold_before > 0
        ORDER BY revenue_before DESC
    """, (days,))
    stockout_products = cursor.fetchall()
    
    db.close()
    
    return jsonify({'stockout_products': stockout_products})

@app.route('/api/report/low_stock_alert_dashboard')
def api_low_stock_alert_dashboard():
    """Enhanced low stock alert with reorder suggestions"""
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    db = get_db()
    if not db:
        return jsonify({'error': 'Database error'}), 500
    
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT p.id, p.name, p.category, p.manufacturer,
               COALESCE(SUM(pb.quantity), 0) as current_stock,
               p.min_stock_level,
               p.min_stock_level - COALESCE(SUM(pb.quantity), 0) as reorder_quantity,
               p.price,
               (p.min_stock_level - COALESCE(SUM(pb.quantity), 0)) * p.price as reorder_value,
               (SELECT SUM(bi.quantity) / COUNT(DISTINCT MONTH(b.bill_date))
                FROM bill_items bi
                JOIN bills b ON bi.bill_id = b.id
                WHERE bi.product_id = p.id 
                  AND b.bill_date >= DATE_SUB(CURDATE(), INTERVAL 3 MONTH)
               ) as avg_monthly_sales
        FROM products p
        LEFT JOIN product_batches pb ON p.id = pb.product_id AND pb.quantity > 0
        GROUP BY p.id
        HAVING current_stock < p.min_stock_level
        ORDER BY (p.min_stock_level - current_stock) DESC
    """)
    low_stock_items = cursor.fetchall()
    
    db.close()
    
    return jsonify({'low_stock_items': low_stock_items})

# CSV Export for all reports
@app.route('/export_report/<report_type>')
def export_report(report_type):
    """Export any report to CSV"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # Get query parameters
    params = dict(request.args)
    
    # Map report type to API endpoint
    report_apis = {
        'daily_sales': 'api_daily_sales_summary',
        'sales_trend': 'api_sales_trend',
        'payment_method': 'api_payment_method_analysis',
        'revenue_category': 'api_revenue_by_category',
        'stock_valuation': 'api_stock_valuation',
        'fast_slow_moving': 'api_fast_slow_moving',
        'batch_expiry': 'api_batch_expiry_dashboard',
        'stock_movement': 'api_stock_movement',
        'supplier_performance': 'api_supplier_performance',
        'top_customers': 'api_top_customers',
        'customer_ratio': 'api_customer_ratio',
        'staff_comparison': 'api_staff_sales_comparison',
        'billing_speed': 'api_billing_speed',
        'upi_approval': 'api_upi_approval_report',
        'purchase_orders': 'api_purchase_order_status',
        'purchase_vs_sales': 'api_purchase_vs_sales',
        'supplier_summary': 'api_supplier_purchase_summary',
        'gst_summary': 'api_gst_summary',
        'cash_collection': 'api_cash_collection',
        'demand_forecast': 'api_demand_forecasting',
        'seasonal': 'api_seasonal_analysis',
        'near_expiry_impact': 'api_near_expiry_impact',
        'stockout': 'api_stockout_report',
        'low_stock_alert': 'api_low_stock_alert_dashboard',
    }
    
    if report_type not in report_apis:
        flash('Invalid report type', 'danger')
        return redirect(url_for('reports'))
    
    # Get data from corresponding API function
    api_func = globals()[report_apis[report_type]]
    
    # Temporarily override session check for internal call
    with app.test_request_context(f'/api/report/{report_type}', query_string=params):
        session['user_id'] = session.get('user_id')
        response = api_func()
        data = response.get_json()
    
    # Create CSV
    output = io.StringIO()
    
    # Extract the main data array from response
    main_key = list(data.keys())[0] if data else None
    rows = data.get(main_key, []) if isinstance(data.get(main_key), list) else []
    
    if rows:
        writer = csv.DictWriter(output, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    
    # Convert to bytes
    output.seek(0)
    byte_output = io.BytesIO()
    byte_output.write(output.getvalue().encode('utf-8'))
    byte_output.seek(0)
    
    filename = f"{report_type}_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    
    return send_file(
        byte_output,
        mimetype='text/csv',
        as_attachment=True,
        download_name=filename
    )

# ============================================
# CUSTOMER MANAGEMENT ROUTES
# ============================================
@app.route('/customers')
def customers():
    """Customer management page"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    if not db:
        return "Database connection error", 500
    
    cursor = db.cursor(dictionary=True)
    cursor.execute("""
        SELECT c.*, COUNT(DISTINCT b.id) as total_bills,
               COALESCE(SUM(b.total_amount), 0) as total_spent
        FROM customers c
        LEFT JOIN bills b ON c.id = b.customer_id
        GROUP BY c.id
        ORDER BY c.created_at DESC
    """)
    customers_list = cursor.fetchall()
    db.close()
    
    return render_template('customers.html', customers=customers_list)

@app.route('/add_customer', methods=['POST'])
def add_customer():
    """Add new customer"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    name = request.form.get('name')
    phone = request.form.get('phone')
    email = request.form.get('email', '')
    address = request.form.get('address', '')
    
    db = get_db()
    if not db:
        flash('Database connection error', 'danger')
        return redirect(url_for('customers'))
    
    try:
        cursor = db.cursor()
        cursor.execute("""
            INSERT INTO customers (name, phone, email, address)
            VALUES (%s, %s, %s, %s)
        """, (name, phone, email, address))
        db.commit()
        flash(f'Customer {name} added successfully!', 'success')
    except mysql.connector.IntegrityError:
        flash('Phone number already exists!', 'danger')
    finally:
        db.close()
    
    return redirect(url_for('customers'))

@app.route('/customer_lookup', methods=['GET', 'POST'])
def customer_lookup():
    """Look up customer by phone number"""
    if request.method == 'POST':
        phone = request.form.get('phone', '').strip()
        
        if not phone:
            flash('Please enter a phone number', 'warning')
            return redirect(url_for('index'))
        
        db = get_db()
        if not db:
            flash('Database connection error', 'danger')
            return redirect(url_for('index'))
        
        cursor = db.cursor(dictionary=True)
        
        # Get customer details
        cursor.execute("SELECT * FROM customers WHERE phone = %s", (phone,))
        customer = cursor.fetchone()
        
        if not customer:
            flash('Customer not found! Please contact staff to register.', 'warning')
            db.close()
            return redirect(url_for('index'))
        
        # Get regular purchases
        cursor.execute("""
            SELECT rp.*, p.price, p.stock_quantity, p.id as product_id
            FROM regular_purchases rp
            LEFT JOIN products p ON rp.product_id = p.id
            WHERE rp.customer_id = %s
            ORDER BY rp.added_at DESC
        """, (customer['id'],))
        regular_purchases = cursor.fetchall()
        
        # Get purchase history
        cursor.execute("""
            SELECT b.*, COUNT(bi.id) as item_count
            FROM bills b
            LEFT JOIN bill_items bi ON b.id = bi.bill_id
            WHERE b.customer_id = %s
            GROUP BY b.id
            ORDER BY b.bill_date DESC
            LIMIT 10
        """, (customer['id'],))
        recent_bills = cursor.fetchall()
        
        # Get statistics
        cursor.execute("""
            SELECT 
                (SELECT COUNT(*) FROM bills WHERE customer_id = %s) as total_bills,
                (SELECT COALESCE(SUM(total_amount), 0) FROM bills WHERE customer_id = %s) as total_spent,
                (SELECT COUNT(DISTINCT medicine_name) FROM bill_items bi 
                 JOIN bills b ON bi.bill_id = b.id WHERE b.customer_id = %s) as unique_medicines
        """, (customer['id'], customer['id'], customer['id']))
        stats = cursor.fetchone()
        
        db.close()
        
        return render_template('customer_history.html',
                             customer=customer,
                             regular_purchases=regular_purchases,
                             recent_bills=recent_bills,
                             stats=stats)
    
    return render_template('customer_lookup.html')

@app.route('/manage_regular_purchases/<int:customer_id>')
def manage_regular_purchases(customer_id):
    """Manage customer's regular purchases"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    if not db:
        return "Database connection error", 500
    
    cursor = db.cursor(dictionary=True)
    
    # Get customer details
    cursor.execute("SELECT * FROM customers WHERE id = %s", (customer_id,))
    customer = cursor.fetchone()
    
    if not customer:
        flash('Customer not found!', 'danger')
        db.close()
        return redirect(url_for('customers'))
    
    # Get regular purchases
    cursor.execute("""
        SELECT rp.*, p.price, p.stock_quantity
        FROM regular_purchases rp
        LEFT JOIN products p ON rp.product_id = p.id
        WHERE rp.customer_id = %s
    """, (customer_id,))
    regular_purchases = cursor.fetchall()
    
    db.close()
    
    return render_template('manage_regular_purchases.html',
                         customer=customer,
                         regular_purchases=regular_purchases)

@app.route('/add_regular_purchase/<int:customer_id>', methods=['POST'])
def add_regular_purchase(customer_id):
    """Add medicine to customer's regular purchases"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    medicine_name = request.form.get('medicine_name')
    default_quantity = int(request.form.get('default_quantity', 1))
    
    # Find product by name
    db = get_db()
    if not db:
        flash('Database connection error', 'danger')
        return redirect(url_for('manage_regular_purchases', customer_id=customer_id))
    
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT id FROM products WHERE name LIKE %s LIMIT 1", (f'%{medicine_name}%',))
    product = cursor.fetchone()
    
    product_id = product['id'] if product else None
    
    try:
        cursor.execute("""
            INSERT INTO regular_purchases (customer_id, product_id, medicine_name, default_quantity)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE default_quantity = %s
        """, (customer_id, product_id, medicine_name, default_quantity, default_quantity))
        db.commit()
        flash('Regular purchase added successfully!', 'success')
    except Exception as e:
        flash(f'Error adding regular purchase: {str(e)}', 'danger')
    finally:
        db.close()
    
    return redirect(url_for('manage_regular_purchases', customer_id=customer_id))
 
@app.route('/remove_regular_purchase/<int:purchase_id>')
def remove_regular_purchase(purchase_id):
    """Remove medicine from regular purchases"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    if not db:
        flash('Database connection error', 'danger')
        return redirect(url_for('customers'))
    
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT customer_id FROM regular_purchases WHERE id = %s", (purchase_id,))
    result = cursor.fetchone()
    
    if result:
        customer_id = result['customer_id']
        cursor.execute("DELETE FROM regular_purchases WHERE id = %s", (purchase_id,))
        db.commit()
        flash('Regular purchase removed successfully!', 'success')
        db.close()
        return redirect(url_for('manage_regular_purchases', customer_id=customer_id))
    
    db.close()
    flash('Regular purchase not found!', 'danger')
    return redirect(url_for('customers'))

@app.route('/quick_billing/<int:customer_id>')
def quick_billing(customer_id):
    """Quick billing with customer's regular purchases"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    if not db:
        flash('Database connection error', 'danger')
        return redirect(url_for('billing'))
    
    cursor = db.cursor(dictionary=True)
    
    # Get customer
    cursor.execute("SELECT * FROM customers WHERE id = %s", (customer_id,))
    customer = cursor.fetchone()
    
    if not customer:
        flash('Customer not found!', 'danger')
        db.close()
        return redirect(url_for('billing'))
    
    # Get regular purchases and add to cart
    cursor.execute("""
        SELECT rp.*, p.*
        FROM regular_purchases rp
        INNER JOIN products p ON rp.product_id = p.id
        WHERE rp.customer_id = %s AND p.stock_quantity > 0
    """, (customer_id,))
    regular_items = cursor.fetchall()
    
    db.close()
    
    # Clear cart and add regular purchases
    cart = []
    for item in regular_items:
        cart_item = {
            'id': item['id'],
            'name': item['name'],
            'price': float(item['price']),
            'quantity': item['default_quantity'],
            'stock_quantity': item['stock_quantity']
        }
        cart.append(cart_item)
    
    session['cart'] = cart
    session['customer_info'] = {
        'id': customer['id'],
        'name': customer['name'],
        'phone': customer['phone']
    }
    
    flash(f'Added {len(cart)} regular items to cart for {customer["name"]}', 'success')
    return redirect(url_for('billing'))

@app.route('/search_medicine_names')
def search_medicine_names():
    """Get all medicine names for autocomplete"""
    db = get_db()
    if not db:
        return jsonify([])
    
    cursor = db.cursor()
    # Get products that have available stock in batches (not products.stock_quantity)
    cursor.execute("""
        SELECT DISTINCT p.name 
        FROM products p
        INNER JOIN product_batches pb ON p.id = pb.product_id
        WHERE pb.quantity > 0
        ORDER BY p.name
    """)
    names = [row[0] for row in cursor.fetchall()]
    db.close()
    
    return jsonify(names)

@app.route('/clear_search_cache')
def clear_search_cache():
    session['search_results'] = None
    return jsonify({'status': 'success'})


@app.route('/api/search_customers')
def api_search_customers():
    """API endpoint to search customers by partial phone number"""
    phone = request.args.get('phone', '')
    
    if len(phone) < 4:
        return jsonify({'customers': []})
    
    db = get_db()
    if not db:
        return jsonify({'customers': []})
    
    cursor = db.cursor(dictionary=True)
    # Search for phone numbers that contain the digits
    cursor.execute(
        "SELECT id, name, phone, email, address FROM customers WHERE phone LIKE %s ORDER BY phone LIMIT 10",
        (f'%{phone}%',)
    )
    customers = cursor.fetchall()
    db.close()
    
    return jsonify({'customers': customers})

@app.route('/api/customer/<phone>')
def api_get_customer(phone):
    """API endpoint to fetch customer by phone"""
    db = get_db()
    if not db:
        return jsonify({'found': False})
    
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM customers WHERE phone = %s", (phone,))
    customer = cursor.fetchone()
    db.close()
    
    if customer:
        return jsonify({
            'found': True,
            'customer': {
                'id': customer['id'],
                'name': customer['name'],
                'phone': customer['phone'],
                'email': customer['email'] or '',
                'address': customer['address'] or ''
            }
        })
    else:
        return jsonify({'found': False})

@app.route('/bills')
def bills():
    """All bills page with filtering, sorting, and pagination"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # 1. Get and Clean Parameters
    search = request.args.get('search', '').strip()
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    sort_by = request.args.get('sort_by', 'bill_date')
    sort_order = request.args.get('sort_order', 'desc').lower()
    
    db = get_db()
    if not db:
        return "Database connection error", 500
    
    cursor = db.cursor(dictionary=True)
    
    # 2. Build Filter Conditions
    conditions = []
    params = []
    
    if search:
        # Search across bill number, customer name, and phone
        conditions.append("(b.bill_number LIKE %s OR b.customer_name LIKE %s OR b.phone LIKE %s)")
        search_param = f'%{search}%'
        params.extend([search_param, search_param, search_param])
    
    if date_from:
        conditions.append("DATE(b.bill_date) >= %s")
        params.append(date_from)
    
    if date_to:
        conditions.append("DATE(b.bill_date) <= %s")
        params.append(date_to)
    
    where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""

    # 3. Get Total Record Count (for Pagination)
    count_query = f"SELECT COUNT(*) as total FROM bills b {where_clause}"
    cursor.execute(count_query, params)
    total_bills = cursor.fetchone()['total'] or 0
    
    # 4. Define Sorting Logic
    sort_columns = {
        'bill_number': 'b.bill_number',
        'bill_date': 'b.bill_date',
        'customer_name': 'b.customer_name',
        'phone': 'b.phone',
        'subtotal': 'b.subtotal',
        'gst': 'b.gst',
        'total_amount': 'b.total_amount',
        'item_count': 'item_count' # This maps to the alias in the main query
    }
    
    sort_column = sort_columns.get(sort_by, 'b.bill_date')
    sort_direction = 'ASC' if sort_order == 'asc' else 'DESC'
    
    # 5. Fetch Main Data
    # We use a subquery or GROUP BY to get the item count per bill
    query = f"""
        SELECT b.*, 
               (SELECT COUNT(*) FROM bill_items bi WHERE bi.bill_id = b.id) as item_count
        FROM bills b
        {where_clause}
        ORDER BY {sort_column} {sort_direction}
        LIMIT %s OFFSET %s
    """
    
    # Pagination math
    offset = (page - 1) * per_page
    query_params = params + [per_page, offset]
    
    cursor.execute(query, query_params)
    bills_list = cursor.fetchall()
    
    # 6. Get Summary Statistics (Filtered by current search/dates)
    stats_query = f"""
        SELECT 
            COUNT(*) as total_bills,
            COALESCE(SUM(total_amount), 0) as total_revenue,
            COALESCE(AVG(total_amount), 0) as avg_bill_amount
        FROM bills b
        {where_clause}
    """
    cursor.execute(stats_query, params)
    stats = cursor.fetchone()
    
    db.close()
    
    total_pages = (total_bills + per_page - 1) // per_page if total_bills > 0 else 1
    
    return render_template('bills.html',
                         bills=bills_list,
                         stats=stats,
                         page=page,
                         total_pages=total_pages,
                         search=search,
                         date_from=date_from,
                         date_to=date_to,
                         sort_by=sort_by,
                         sort_order=sort_order)
    
# ============================================
# SUPPLIER MANAGEMENT ROUTES
# ============================================
@app.route('/suppliers')
def suppliers():
    """Supplier management page"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    if not db:
        return "Database connection error", 500
    
    cursor = db.cursor(dictionary=True)
    cursor.execute("""
        SELECT * FROM suppliers
        ORDER BY name
    """)
    suppliers_list = cursor.fetchall()
    db.close()
    
    return render_template('suppliers.html', suppliers=suppliers_list)

@app.route('/add_supplier', methods=['POST'])
def add_supplier():
    """Add new supplier"""
    if 'user_id' not in session or session.get('role') != 'owner':
        flash('Unauthorized access!', 'danger')
        return redirect(url_for('suppliers'))
    
    name = request.form.get('name')
    company_name = request.form.get('company_name', '')
    phone = request.form.get('phone')
    email = request.form.get('email', '')
    address = request.form.get('address', '')
    gstin = request.form.get('gstin', '')
    
    db = get_db()
    if not db:
        flash('Database connection error', 'danger')
        return redirect(url_for('suppliers'))
    
    try:
        cursor = db.cursor()
        cursor.execute("""
            INSERT INTO suppliers (name, company_name, phone, email, address, gstin)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (name, company_name, phone, email, address, gstin))
        db.commit()
        flash(f'Supplier {name} added successfully!', 'success')
    except mysql.connector.IntegrityError:
        flash('Phone number already exists!', 'danger')
    except Exception as e:
        flash(f'Error adding supplier: {str(e)}', 'danger')
    finally:
        db.close()
    
    return redirect(url_for('suppliers'))

@app.route('/edit_supplier/<int:supplier_id>', methods=['POST'])
def edit_supplier(supplier_id):
    """Edit existing supplier"""
    if 'user_id' not in session or session.get('role') != 'owner':
        flash('Unauthorized access!', 'danger')
        return redirect(url_for('suppliers'))
    
    name = request.form.get('name')
    company_name = request.form.get('company_name', '')
    phone = request.form.get('phone')
    email = request.form.get('email', '')
    address = request.form.get('address', '')
    gstin = request.form.get('gstin', '')
    
    db = get_db()
    if not db:
        flash('Database connection error', 'danger')
        return redirect(url_for('suppliers'))
    
    try:
        cursor = db.cursor()
        cursor.execute("""
            UPDATE suppliers 
            SET name = %s, company_name = %s, phone = %s, email = %s, address = %s, gstin = %s
            WHERE id = %s
        """, (name, company_name, phone, email, address, gstin, supplier_id))
        db.commit()
        flash(f'Supplier {name} updated successfully!', 'success')
    except mysql.connector.IntegrityError:
        flash('Phone number already exists!', 'danger')
    except Exception as e:
        flash(f'Error updating supplier: {str(e)}', 'danger')
    finally:
        db.close()
    
    return redirect(url_for('suppliers'))

@app.route('/supplier_purchases/<int:supplier_id>')
def supplier_purchases(supplier_id):
    """View supplier's purchase orders"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    status_filter = request.args.get('status', 'all')
    
    db = get_db()
    if not db:
        return "Database connection error", 500
    
    cursor = db.cursor(dictionary=True)
    
    # Get supplier details
    cursor.execute("SELECT * FROM suppliers WHERE id = %s", (supplier_id,))
    supplier = cursor.fetchone()
    
    if not supplier:
        flash('Supplier not found!', 'danger')
        db.close()
        return redirect(url_for('suppliers'))
    
    # Get all products for datalist
    cursor.execute("SELECT name FROM products ORDER BY name")
    products = cursor.fetchall()
    
    # Get purchases based on filter
    if status_filter == 'all':
        cursor.execute("""
            SELECT * FROM supplier_purchases
            WHERE supplier_id = %s
            ORDER BY created_at DESC
        """, (supplier_id,))
    else:
        cursor.execute("""
            SELECT * FROM supplier_purchases
            WHERE supplier_id = %s AND status = %s
            ORDER BY created_at DESC
        """, (supplier_id, status_filter))
    
    purchases = cursor.fetchall()
    
    # Get statistics
    cursor.execute("""
        SELECT 
            SUM(CASE WHEN status = 'to_be_ordered' THEN 1 ELSE 0 END) as to_be_ordered,
            SUM(CASE WHEN status = 'ordered' THEN 1 ELSE 0 END) as ordered,
            SUM(CASE WHEN status = 'received' THEN 1 ELSE 0 END) as received
        FROM supplier_purchases
        WHERE supplier_id = %s
    """, (supplier_id,))
    stats = cursor.fetchone()
    
    db.close()
    
    return render_template('supplier_purchases.html',
                         supplier=supplier,
                         purchases=purchases,
                         products=products,
                         stats=stats,
                         status=status_filter)

@app.route('/add_supplier_purchase', methods=['POST'])
def add_supplier_purchase():
    """Add new supplier purchase order"""
    if 'user_id' not in session or session.get('role') != 'owner':
        flash('Unauthorized access!', 'danger')
        return redirect(url_for('suppliers'))
    
    supplier_id = int(request.form.get('supplier_id'))
    medicine_name = request.form.get('medicine_name')
    quantity = int(request.form.get('quantity'))
    unit_price = float(request.form.get('unit_price'))
    batch_number = request.form.get('batch_number', '').strip()
    expiry_date = request.form.get('expiry_date') or None
    status = request.form.get('status', 'to_be_ordered')
    expected_delivery_date = request.form.get('expected_delivery_date')
    notes = request.form.get('notes', '')
    
    total_amount = quantity * unit_price
    cost_price = unit_price  # Cost price same as unit price
    purchase_number = generate_purchase_number()
    
    db = get_db()
    if not db:
        flash('Database connection error', 'danger')
        return redirect(url_for('supplier_purchases', supplier_id=supplier_id))
    
    try:
        cursor = db.cursor(dictionary=True)
        
        # Find product ID if exists
        cursor.execute("SELECT id FROM products WHERE name = %s", (medicine_name,))
        product = cursor.fetchone()
        
        # Block if medicine doesn't exist in inventory
        if not product:
            flash(f'Error: "{medicine_name}" does not exist in inventory. Please add the product to inventory first before creating a purchase order.', 'danger')
            db.close()
            return redirect(url_for('supplier_purchases', supplier_id=supplier_id))
        
        product_id = product['id']
        
        # Set order_date if status is 'ordered'
        order_date = datetime.now().date() if status == 'ordered' else None
        
        # If batch_number is not provided, generate one
        if not batch_number:
            batch_number = f"BATCH-{purchase_number}"
        
        cursor.execute("""
            INSERT INTO supplier_purchases 
            (purchase_number, supplier_id, product_id, medicine_name, batch_number, 
             quantity, expiry_date, unit_price, cost_price, total_amount, status, 
             order_date, expected_delivery_date, notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (purchase_number, supplier_id, product_id, medicine_name, batch_number,
              quantity, expiry_date, unit_price, cost_price, total_amount, status, 
              order_date, expected_delivery_date, notes))
        
        db.commit()
        flash(f'Purchase order {purchase_number} created successfully!', 'success')
            
    except Exception as e:
        flash(f'Error creating purchase order: {str(e)}', 'danger')
    finally:
        db.close()
    
    return redirect(url_for('supplier_purchases', supplier_id=supplier_id))

@app.route('/update_purchase_status/<int:purchase_id>/<new_status>')
def update_purchase_status(purchase_id, new_status):
    """Update purchase order status"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    if not db:
        flash('Database connection error', 'danger')
        return redirect(url_for('suppliers'))
    
    try:
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT supplier_id FROM supplier_purchases WHERE id = %s", (purchase_id,))
        result = cursor.fetchone()
        
        if not result:
            flash('Purchase order not found!', 'danger')
            return redirect(url_for('suppliers'))
        
        supplier_id = result['supplier_id']
        
        # Update status and set order_date if changing to 'ordered'
        if new_status == 'ordered':
            cursor.execute("""
                UPDATE supplier_purchases 
                SET status = %s, order_date = %s
                WHERE id = %s
            """, (new_status, datetime.now().date(), purchase_id))
        else:
            cursor.execute("""
                UPDATE supplier_purchases 
                SET status = %s
                WHERE id = %s
            """, (new_status, purchase_id))
        
        db.commit()
        flash('Purchase order status updated!', 'success')
    except Exception as e:
        flash(f'Error updating status: {str(e)}', 'danger')
    finally:
        db.close()
    
    return redirect(url_for('supplier_purchases', supplier_id=supplier_id))

@app.route('/receive_purchase/<int:purchase_id>')
def receive_purchase(purchase_id):
    """Mark purchase as received and update stock"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    if not db:
        flash('Database connection error', 'danger')
        return redirect(url_for('suppliers'))
    
    try:
        cursor = db.cursor(dictionary=True)
        
        # Get purchase details
        cursor.execute("SELECT * FROM supplier_purchases WHERE id = %s", (purchase_id,))
        purchase = cursor.fetchone()
        
        if not purchase:
            flash('Purchase order not found!', 'danger')
            return redirect(url_for('suppliers'))
        
        supplier_id = purchase['supplier_id']
        
        # Update purchase status
        cursor.execute("""
            UPDATE supplier_purchases 
            SET status = 'received', received_date = %s, batch_created = TRUE
            WHERE id = %s
        """, (datetime.now().date(), purchase_id))
        
        # Update product stock if product exists
        if purchase['product_id']:
            cursor.execute("""
                UPDATE products 
                SET stock_quantity = stock_quantity + %s
                WHERE id = %s
            """, (purchase['quantity'], purchase['product_id']))
            
            # Create batch entry in product_batches table
            batch_number = purchase.get('batch_number') or f"SP-{purchase['purchase_number']}"
            expiry_date = purchase.get('expiry_date')
            
            # If no expiry date provided, set default to 1 year from now
            if not expiry_date:
                expiry_date = (datetime.now() + timedelta(days=365)).date()
            
            cost_price = purchase.get('cost_price') or purchase['unit_price']
            
            # Check if batch already exists
            cursor.execute("""
                SELECT id FROM product_batches 
                WHERE product_id = %s AND batch_number = %s
            """, (purchase['product_id'], batch_number))
            
            existing_batch = cursor.fetchone()
            
            if existing_batch:
                # Update existing batch quantity
                cursor.execute("""
                    UPDATE product_batches 
                    SET quantity = quantity + %s
                    WHERE id = %s
                """, (purchase['quantity'], existing_batch['id']))
                flash(f'Purchase order received! Batch {batch_number} updated for {purchase["medicine_name"]}', 'success')
            else:
                # Create new batch
                cursor.execute("""
                    INSERT INTO product_batches 
                    (product_id, batch_number, quantity, expiry_date, cost_price, 
                     supplier_id, purchase_date)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (purchase['product_id'], batch_number, purchase['quantity'], 
                      expiry_date, cost_price, supplier_id, datetime.now().date()))
                flash(f'Purchase order received! Batch {batch_number} created for {purchase["medicine_name"]}', 'success')
        
        db.commit()
    except Exception as e:
        db.rollback()
        flash(f'Error receiving purchase: {str(e)}', 'danger')
    finally:
        db.close()
    
    return redirect(url_for('supplier_purchases', supplier_id=supplier_id))

# ============================================
# SETTINGS ROUTES
# ============================================
@app.route('/settings', methods=['GET', 'POST'])
def settings():
    """Store settings management"""
    if 'user_id' not in session or session.get('role') != 'owner':
        flash('Only owners can access settings!', 'danger')
        return redirect(url_for('login'))
    
    db = get_db()
    if not db:
        flash('Database connection error', 'danger')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        try:
            cursor = db.cursor()
            
            # Get all settings to update
            cursor.execute("SELECT setting_key, is_editable FROM settings")
            all_settings = cursor.fetchall()
            
            # Update each editable setting
            for setting_key, is_editable in all_settings:
                if is_editable and setting_key in request.form:
                    new_value = request.form.get(setting_key)
                    cursor.execute("""
                        UPDATE settings 
                        SET setting_value = %s, updated_at = CURRENT_TIMESTAMP
                        WHERE setting_key = %s
                    """, (new_value, setting_key))
            
            db.commit()
            flash('Settings updated successfully!', 'success')
        except Exception as e:
            db.rollback()
            flash(f'Error updating settings: {str(e)}', 'danger')
        finally:
            db.close()
        
        return redirect(url_for('settings'))
    
    # GET request - display settings
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM settings ORDER BY setting_key")
    settings_list = cursor.fetchall()
    db.close()
    
    return render_template('settings.html', settings=settings_list)

# ============================================
# STAFF MANAGEMENT ROUTES (OWNER ONLY)
# ============================================
@app.route('/staff')
def staff():
    """View all staff accounts - Owner only"""
    if 'user_id' not in session or session.get('role') != 'owner':
        flash('Access denied! Owner privileges required.', 'danger')
        return redirect(url_for('login'))
    
    db = get_db()
    if not db:
        return "Database connection error", 500
    
    cursor = db.cursor(dictionary=True)
    cursor.execute("""
        SELECT id, username, full_name, role, email, phone, 
               created_at, is_active 
        FROM users 
        ORDER BY created_at DESC
    """)
    staff_list = cursor.fetchall()
    db.close()
    
    return render_template('staff.html', staff_list=staff_list)

@app.route('/staff/add', methods=['POST'])
def add_staff():
    """Create new staff account - Owner only"""
    if 'user_id' not in session or session.get('role') != 'owner':
        flash('Access denied!', 'danger')
        return redirect(url_for('login'))
    
    username = request.form.get('username')
    password = request.form.get('password')
    full_name = request.form.get('full_name')
    role = request.form.get('role')
    email = request.form.get('email')
    phone = request.form.get('phone')
    
    if not username or not password or not full_name or not role:
        flash('Username, password, full name, and role are required!', 'danger')
        return redirect(url_for('staff'))
    
    hashed_password = hash_password(password)
    
    db = get_db()
    if not db:
        flash('Database connection error!', 'danger')
        return redirect(url_for('staff'))
    
    try:
        cursor = db.cursor()
        cursor.execute("""
            INSERT INTO users (username, password, full_name, role, email, phone)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (username, hashed_password, full_name, role, email, phone))
        db.commit()
        db.close()
        flash(f'Staff account "{username}" created successfully!', 'success')
    except mysql.connector.IntegrityError:
        db.close()
        flash('Username already exists! Please choose a different username.', 'danger')
    except Exception as e:
        db.close()
        flash(f'Error creating staff account: {str(e)}', 'danger')
    
    return redirect(url_for('staff'))

@app.route('/staff/edit/<int:staff_id>', methods=['POST'])
def edit_staff(staff_id):
    """Edit staff account details - Owner only"""
    if 'user_id' not in session or session.get('role') != 'owner':
        flash('Access denied!', 'danger')
        return redirect(url_for('login'))
    
    full_name = request.form.get('full_name')
    role = request.form.get('role')
    email = request.form.get('email')
    phone = request.form.get('phone')
    is_active = request.form.get('is_active') == '1'
    
    if not full_name or not role:
        flash('Full name and role are required!', 'danger')
        return redirect(url_for('staff'))
    
    db = get_db()
    if not db:
        flash('Database connection error!', 'danger')
        return redirect(url_for('staff'))
    
    try:
        cursor = db.cursor()
        cursor.execute("""
            UPDATE users 
            SET full_name = %s, role = %s, email = %s, phone = %s, is_active = %s
            WHERE id = %s
        """, (full_name, role, email, phone, is_active, staff_id))
        db.commit()
        db.close()
        flash('Staff account updated successfully!', 'success')
    except Exception as e:
        db.close()
        flash(f'Error updating staff account: {str(e)}', 'danger')
    
    return redirect(url_for('staff'))

@app.route('/staff/change-password/<int:staff_id>', methods=['POST'])
def change_staff_password(staff_id):
    """Change staff password - Owner only"""
    if 'user_id' not in session or session.get('role') != 'owner':
        flash('Access denied!', 'danger')
        return redirect(url_for('login'))
    
    new_password = request.form.get('new_password')
    
    if not new_password or len(new_password) < 4:
        flash('Password must be at least 4 characters long!', 'danger')
        return redirect(url_for('staff'))
    
    hashed_password = hash_password(new_password)
    
    db = get_db()
    if not db:
        flash('Database connection error!', 'danger')
        return redirect(url_for('staff'))
    
    try:
        cursor = db.cursor()
        cursor.execute("""
            UPDATE users 
            SET password = %s
            WHERE id = %s
        """, (hashed_password, staff_id))
        db.commit()
        db.close()
        flash('Password changed successfully!', 'success')
    except Exception as e:
        db.close()
        flash(f'Error changing password: {str(e)}', 'danger')
    
    return redirect(url_for('staff'))

@app.route('/staff/delete/<int:staff_id>', methods=['POST'])
def delete_staff(staff_id):
    """Delete staff account - Owner only"""
    if 'user_id' not in session or session.get('role') != 'owner':
        flash('Access denied!', 'danger')
        return redirect(url_for('login'))
    
    # Prevent owner from deleting their own account
    if staff_id == session.get('user_id'):
        flash('You cannot delete your own account!', 'warning')
        return redirect(url_for('staff'))
    
    db = get_db()
    if not db:
        flash('Database connection error!', 'danger')
        return redirect(url_for('staff'))
    
    try:
        cursor = db.cursor(dictionary=True)
        # Get username before deleting
        cursor.execute("SELECT username FROM users WHERE id = %s", (staff_id,))
        user = cursor.fetchone()
        
        if user:
            cursor.execute("DELETE FROM users WHERE id = %s", (staff_id,))
            db.commit()
            flash(f'Staff account "{user["username"]}" deleted successfully!', 'success')
        else:
            flash('Staff account not found!', 'danger')
        
        db.close()
    except Exception as e:
        db.close()
        flash(f'Error deleting staff account: {str(e)}', 'danger')
    
    return redirect(url_for('staff'))

# ============================================
# STAFF ANALYSIS ROUTES
# ============================================
@app.route('/staff-analysis')
def staff_analysis():
    """View staff performance analysis - Owner only"""
    if 'user_id' not in session or session.get('role') != 'owner':
        flash('Access denied! Owner privileges required.', 'danger')
        return redirect(url_for('login'))
    
    db = get_db()
    if not db:
        return "Database connection error", 500
    
    cursor = db.cursor(dictionary=True)
    
    # Get staff analytics with bill counts and total sales
    cursor.execute("""
        SELECT 
            u.id,
            u.full_name,
            u.username,
            u.role,
            u.is_active,
            COUNT(DISTINCT b.id) as total_bills,
            COALESCE(SUM(b.total_amount), 0) as total_sales,
            MAX(b.bill_date) as last_bill_date,
            MIN(b.bill_date) as first_bill_date
        FROM users u
        LEFT JOIN bills b ON u.id = b.created_by
        GROUP BY u.id, u.full_name, u.username, u.role, u.is_active
        ORDER BY total_sales DESC
    """)
    staff_analytics = cursor.fetchall()
    
    db.close()
    
    return render_template('staff_analysis.html', staff_analytics=staff_analytics)

@app.route('/staff-analysis/<int:staff_id>')
def staff_bills_detail(staff_id):
    """View detailed bills for a specific staff member - Owner only"""
    if 'user_id' not in session or session.get('role') != 'owner':
        flash('Access denied! Owner privileges required.', 'danger')
        return redirect(url_for('login'))
    
    db = get_db()
    if not db:
        return "Database connection error", 500
    
    cursor = db.cursor(dictionary=True)
    
    # Get staff details
    cursor.execute("SELECT id, full_name, username, role FROM users WHERE id = %s", (staff_id,))
    staff = cursor.fetchone()
    
    if not staff:
        flash('Staff member not found!', 'danger')
        db.close()
        return redirect(url_for('staff_analysis'))
    
    # Get all bills created by this staff member
    cursor.execute("""
        SELECT 
            b.id,
            b.bill_number,
            b.customer_name,
            b.phone,
            b.subtotal,
            b.gst,
            b.total_amount,
            b.bill_date,
            COUNT(bi.id) as item_count
        FROM bills b
        LEFT JOIN bill_items bi ON b.id = bi.bill_id
        WHERE b.created_by = %s
        GROUP BY b.id
        ORDER BY b.bill_date DESC
    """, (staff_id,))
    bills = cursor.fetchall()
    
    # Get summary statistics
    cursor.execute("""
        SELECT 
            COUNT(*) as total_bills,
            COALESCE(SUM(total_amount), 0) as total_sales,
            COALESCE(AVG(total_amount), 0) as avg_sale,
            MAX(bill_date) as last_sale,
            MIN(bill_date) as first_sale
        FROM bills
        WHERE created_by = %s
    """, (staff_id,))
    summary = cursor.fetchone()
    
    db.close()
    
    return render_template('staff_bills_detail.html', 
                          staff=staff, 
                          bills=bills, 
                          summary=summary)

# ============================================
# CUSTOMER BILLING HISTORY ROUTES
# ============================================
@app.route('/customer-billing-history/<int:customer_id>')
def customer_billing_history(customer_id):
    """View detailed billing history for a specific customer"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    if not db:
        return "Database connection error", 500
    
    cursor = db.cursor(dictionary=True)
    
    # Get customer details
    cursor.execute("SELECT * FROM customers WHERE id = %s", (customer_id,))
    customer = cursor.fetchone()
    
    if not customer:
        flash('Customer not found!', 'danger')
        db.close()
        return redirect(url_for('customers'))
    
    # Get all bills for this customer
    cursor.execute("""
        SELECT 
            b.id,
            b.bill_number,
            b.subtotal,
            b.gst,
            b.total_amount,
            b.bill_date,
            b.created_by,
            u.full_name as staff_name,
            COUNT(bi.id) as item_count
        FROM bills b
        LEFT JOIN bill_items bi ON b.id = bi.bill_id
        LEFT JOIN users u ON b.created_by = u.id
        WHERE b.customer_id = %s
        GROUP BY b.id
        ORDER BY b.bill_date DESC
    """, (customer_id,))
    bills = cursor.fetchall()
    
    # Get summary statistics
    cursor.execute("""
        SELECT 
            COUNT(*) as total_bills,
            COALESCE(SUM(total_amount), 0) as total_spent,
            COALESCE(AVG(total_amount), 0) as avg_bill,
            MAX(bill_date) as last_purchase,
            MIN(bill_date) as first_purchase
        FROM bills
        WHERE customer_id = %s
    """, (customer_id,))
    summary = cursor.fetchone()
    
    # Get top purchased medicines
    cursor.execute("""
        SELECT 
            bi.medicine_name,
            SUM(bi.quantity) as total_quantity,
            COUNT(DISTINCT bi.bill_id) as purchase_count,
            SUM(bi.total_amount) as total_spent
        FROM bill_items bi
        JOIN bills b ON bi.bill_id = b.id
        WHERE b.customer_id = %s
        GROUP BY bi.medicine_name
        ORDER BY total_quantity DESC
        LIMIT 10
    """, (customer_id,))
    top_medicines = cursor.fetchall()
    
    db.close()
    
    return render_template('customer_billing_history.html', 
                          customer=customer, 
                          bills=bills, 
                          summary=summary,
                          top_medicines=top_medicines)

# ============================================
# BATCH MANAGEMENT ROUTES
# ============================================

@app.route('/product/<int:product_id>/batches')
def view_batches(product_id):
    """View all batches for a specific product"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    if not db:
        flash('Database connection error', 'danger')
        return redirect(url_for('inventory'))
    
    cursor = db.cursor(dictionary=True)
    
    # Get product details
    cursor.execute("SELECT * FROM products WHERE id = %s", (product_id,))
    product = cursor.fetchone()
    
    if not product:
        flash('Product not found!', 'danger')
        db.close()
        return redirect(url_for('inventory'))
    
    # Get all batches for this product
    cursor.execute("""
        SELECT pb.*, 
               s.name as supplier_name,
               DATEDIFF(pb.expiry_date, CURDATE()) as days_until_expiry,
               CASE 
                   WHEN pb.expiry_date < CURDATE() THEN 'expired'
                   WHEN DATEDIFF(pb.expiry_date, CURDATE()) <= 30 THEN 'urgent'
                   WHEN DATEDIFF(pb.expiry_date, CURDATE()) <= 90 THEN 'warning'
                   ELSE 'safe'
               END as status
        FROM product_batches pb
        LEFT JOIN suppliers s ON pb.supplier_id = s.id
        WHERE pb.product_id = %s
        ORDER BY pb.expiry_date ASC
    """, (product_id,))
    batches = cursor.fetchall()
    
    # Get total stock
    cursor.execute("""
        SELECT COALESCE(SUM(quantity), 0) as total_stock
        FROM product_batches
        WHERE product_id = %s
    """, (product_id,))
    total_stock = cursor.fetchone()['total_stock']
    
    db.close()
    
    return render_template('view_batches.html', 
                         product=product, 
                         batches=batches,
                         total_stock=total_stock)

@app.route('/product/<int:product_id>/add_batch', methods=['GET', 'POST'])
def add_batch(product_id):
    """Add new batch to existing product"""
    if 'user_id' not in session or session.get('role') != 'owner':
        return redirect(url_for('login'))
    
    db = get_db()
    if not db:
        flash('Database connection error', 'danger')
        return redirect(url_for('inventory'))
    
    cursor = db.cursor(dictionary=True)
    
    # Get product details
    cursor.execute("SELECT * FROM products WHERE id = %s", (product_id,))
    product = cursor.fetchone()
    
    if not product:
        flash('Product not found!', 'danger')
        db.close()
        return redirect(url_for('inventory'))
    
    if request.method == 'POST':
        try:
            batch_number = request.form.get('batch_number')
            quantity = int(request.form.get('quantity'))
            expiry_date = request.form.get('expiry_date') or None
            cost_price = float(request.form.get('cost_price')) if request.form.get('cost_price') else None
            supplier_id = request.form.get('supplier_id') or None
            shelf_location = request.form.get('shelf_location') or None
            
            cursor.execute("""
                INSERT INTO product_batches 
                (product_id, batch_number, quantity, expiry_date, cost_price, supplier_id, shelf_location)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (product_id, batch_number, quantity, expiry_date, cost_price, supplier_id, shelf_location))
            
            db.commit()
            flash(f'Batch {batch_number} added successfully!', 'success')
            db.close()
            return redirect(url_for('view_batches', product_id=product_id))
            
        except Exception as e:
            flash(f'Error adding batch: {str(e)}', 'danger')
            db.rollback()
    
    # Get suppliers for dropdown
    cursor.execute("SELECT id, name FROM suppliers ORDER BY name")
    suppliers = cursor.fetchall()
    
    db.close()
    
    return render_template('add_batch.html', product=product, suppliers=suppliers)

@app.route('/batch/<int:batch_id>/edit', methods=['GET', 'POST'])
def edit_batch(batch_id):
    """Edit batch details"""
    if 'user_id' not in session or session.get('role') != 'owner':
        return redirect(url_for('login'))
    
    db = get_db()
    if not db:
        flash('Database connection error', 'danger')
        return redirect(url_for('inventory'))
    
    cursor = db.cursor(dictionary=True)
    
    # Get batch details
    cursor.execute("""
        SELECT pb.*, p.name as product_name, p.id as product_id
        FROM product_batches pb
        JOIN products p ON pb.product_id = p.id
        WHERE pb.id = %s
    """, (batch_id,))
    batch = cursor.fetchone()
    
    if not batch:
        flash('Batch not found!', 'danger')
        db.close()
        return redirect(url_for('inventory'))
    
    if request.method == 'POST':
        try:
            cursor.execute("""
                UPDATE product_batches
                SET batch_number = %s, quantity = %s, expiry_date = %s, 
                    cost_price = %s, supplier_id = %s, shelf_location = %s
                WHERE id = %s
            """, (
                request.form.get('batch_number'),
                int(request.form.get('quantity')),
                request.form.get('expiry_date') or None,
                float(request.form.get('cost_price')) if request.form.get('cost_price') else None,
                request.form.get('supplier_id') or None,
                request.form.get('shelf_location') or None,
                batch_id
            ))
            
            db.commit()
            flash('Batch updated successfully!', 'success')
            db.close()
            return redirect(url_for('view_batches', product_id=batch['product_id']))
            
        except Exception as e:
            flash(f'Error updating batch: {str(e)}', 'danger')
            db.rollback()
    
    # Get suppliers for dropdown
    cursor.execute("SELECT id, name FROM suppliers ORDER BY name")
    suppliers = cursor.fetchall()
    
    db.close()
    
    return render_template('edit_batch.html', batch=batch, suppliers=suppliers)

@app.route('/batch/<int:batch_id>/delete', methods=['POST'])
def delete_batch(batch_id):
    """Delete a batch (only if quantity is 0)"""
    if 'user_id' not in session or session.get('role') != 'owner':
        flash('Unauthorized access!', 'danger')
        return redirect(url_for('login'))
    
    db = get_db()
    if not db:
        flash('Database connection error', 'danger')
        return redirect(url_for('inventory'))
    
    cursor = db.cursor(dictionary=True)
    
    # Get batch details
    cursor.execute("SELECT product_id, quantity FROM product_batches WHERE id = %s", (batch_id,))
    batch = cursor.fetchone()
    
    if not batch:
        flash('Batch not found!', 'danger')
        db.close()
        return redirect(url_for('inventory'))
    
    if batch['quantity'] > 0:
        flash('Cannot delete batch with remaining stock! Adjust quantity to 0 first.', 'danger')
        db.close()
        return redirect(url_for('view_batches', product_id=batch['product_id']))
    
    try:
        cursor.execute("DELETE FROM product_batches WHERE id = %s", (batch_id,))
        db.commit()
        flash('Batch deleted successfully!', 'success')
    except Exception as e:
        flash(f'Error deleting batch: {str(e)}', 'danger')
    finally:
        db.close()
    
    return redirect(url_for('view_batches', product_id=batch['product_id']))

# ============================================
# ADMINISTRATIVE ROUTES
# ============================================
@app.route('/admin/cleanup_old_data', methods=['POST'])
def admin_cleanup_old_data():
    """Cleanup data older than 6 quarters - Admin only"""
    if 'user_id' not in session or session.get('role') != 'owner':
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        success = cleanup_old_data()
        if success:
            return jsonify({
                'success': True,
                'message': 'Old data cleaned up successfully (data older than 6 quarters removed)'
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Error during cleanup'
            }), 500
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error: {str(e)}'
        }), 500

@app.route('/admin/quarter_stats')
def admin_quarter_stats():
    """Get statistics about quarterly data - Admin only"""
    if 'user_id' not in session or session.get('role') != 'owner':
        return jsonify({'error': 'Unauthorized'}), 401
    
    db = get_db()
    if not db:
        return jsonify({'error': 'Database error'}), 500
    
    cursor = db.cursor(dictionary=True)
    
    # Get data distribution by quarter
    quarters = get_last_n_quarters(8)  # Get 8 quarters for stats
    quarter_stats = []
    
    for q in quarters:
        start_date, end_date = get_quarter_date_range(q['quarter'], q['fiscal_year'])
        
        cursor.execute("""
            SELECT 
                COUNT(*) as bill_count,
                COALESCE(SUM(total_amount), 0) as total_revenue
            FROM bills
            WHERE bill_date BETWEEN %s AND %s
        """, (start_date, end_date))
        
        stats = cursor.fetchone()
        stats['quarter'] = q['display']
        stats['start_date'] = start_date.strftime('%Y-%m-%d')
        stats['end_date'] = end_date.strftime('%Y-%m-%d')
        quarter_stats.append(stats)
    
    db.close()
    
    return jsonify({
        'quarter_stats': quarter_stats,
        'current_quarter': get_quarter_info()
    })

@app.route('/returns', methods=['GET', 'POST'])
def returns_page():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)

    # Analytics for the page
    cursor.execute("""
        SELECT 
            COALESCE(SUM(CASE WHEN MONTH(return_date) = MONTH(CURDATE()) THEN refund_amount ELSE 0 END), 0) as monthly_returns,
            COALESCE(SUM(CASE WHEN YEAR(return_date) = YEAR(CURDATE()) THEN refund_amount ELSE 0 END), 0) as yearly_returns
        FROM returns
    """)
    stats = cursor.fetchone()
    
    # Recent returns list
    cursor.execute("""
        SELECT r.*, p.name as medicine_name, b.bill_number 
        FROM returns r 
        JOIN products p ON r.product_id = p.id 
        JOIN bills b ON r.bill_id = b.id 
        ORDER BY r.return_date DESC LIMIT 10
    """)
    recent_returns = cursor.fetchall()
    db.close()
    
    return render_template('returns.html', stats=stats, recent_returns=recent_returns)

@app.route('/api/get_bill_items/<bill_number>')
def get_bill_items(bill_number):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("""
        SELECT bi.*, b.id as bill_id 
        FROM bill_items bi 
        JOIN bills b ON bi.bill_id = b.id 
        WHERE b.bill_number = %s
    """, (bill_number,))
    items = cursor.fetchall()
    db.close()
    return jsonify(items)
@app.route('/process_return', methods=['POST'])
def process_return():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    # Extract form data
    bill_id = request.form.get('bill_id')
    product_id = request.form.get('product_id')
    qty = int(request.form.get('quantity'))
    unit_price = float(request.form.get('unit_price'))
    # Checkbox logic for inventory restoration
    add_back = request.form.get('add_to_inventory') == 'on'
    
    refund = qty * unit_price
    
    db = get_db()
    cursor = db.cursor()
    try:
        # 1. Record the return transaction for financial tracking
        cursor.execute("""
            INSERT INTO returns (bill_id, product_id, quantity, refund_amount, added_to_inventory, processed_by)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (bill_id, product_id, qty, refund, add_back, session['user_id']))
        
        # 2. Update Inventory AND Batches if requested
        if add_back:
            # Update the master product count (used for general inventory view)
            cursor.execute("""
                UPDATE products 
                SET stock_quantity = stock_quantity + %s 
                WHERE id = %s
            """, (qty, product_id))
            
            # CRITICAL: Update the most recent batch so the medicine can be re-sold
            # We target the batch with the furthest expiry date to follow pharmacy best practices
            cursor.execute("""
                UPDATE product_batches 
                SET quantity = quantity + %s 
                WHERE product_id = %s 
                ORDER BY expiry_date DESC LIMIT 1
            """, (qty, product_id))
            
        db.commit()
        flash(f'Return processed successfully. Refund: ₹{refund:.2f} issued.', 'success')
        
    except Exception as e:
        db.rollback()
        flash(f'Error processing return: {str(e)}', 'danger')
    finally:
        db.close()
    
    return redirect(url_for('returns_page'))
# ============================================
# RUN APPLICATION
# ============================================
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
