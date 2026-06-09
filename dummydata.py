import mysql.connector
import random
from faker import Faker
from datetime import datetime, timedelta

fake = Faker('en_IN')

db_config = {
    "host": "localhost",
    "user": "root",
    "password": "",
    "database": "medical_store2"
}

def generate_complex_data():
    conn = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        print("Connected. Generating specific pharmacy data...")

        # 1. Update existing medicines: Randomize units between 50 and 100
        cursor.execute("SELECT id FROM products")
        existing_prods = cursor.fetchall()
        for p in existing_prods:
            new_qty = random.randint(50, 100)
            cursor.execute("UPDATE products SET stock_quantity = %s WHERE id = %s", (new_qty, p['id']))
            # Important: Update batches too so the app sees the stock
            cursor.execute("UPDATE product_batches SET quantity = %s WHERE product_id = %s", (new_qty, p['id']))

        # 2. Supplier Purchase History (From 01/2025)
        cursor.execute("SELECT id FROM suppliers LIMIT 5")
        supps = [s['id'] for s in cursor.fetchall()]
        cursor.execute("SELECT id, name, price FROM products LIMIT 30")
        prods = cursor.fetchall()

        if supps and prods:
            # Recent Deliveries (15) & Pending (8)
            for i in range(23):
                status = 'received' if i < 15 else 'ordered'
                supp_id = random.choice(supps)
                prod = random.choice(prods)
                qty = random.randint(20, 100)
                u_price = float(prod['price']) * 0.7
                
                cursor.execute("""
                    INSERT INTO supplier_purchases 
                    (purchase_number, supplier_id, product_id, medicine_name, quantity, unit_price, total_amount, status, received_date, order_date)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (f"PO-{202500+i}", supp_id, prod['id'], prod['name'], qty, u_price, qty*u_price, status, 
                      datetime(2025, random.randint(1,12), random.randint(1,28)) if status == 'received' else None,
                      datetime(2025, 1, 10)))

        # 3. Last 15 Days: 19 Bills + 25 Cashier Bills (Total 44 new bills)
        cursor.execute("SELECT id, name, phone FROM customers LIMIT 20")
        custs = cursor.fetchall()
        
        for i in range(44):
            # First 25 bills assigned to Cashier (ID 2), rest to Admin (ID 1)
            role_user = 2 if i < 25 else 1 
            
            # Last 15 days window
            bill_date = datetime.now() - timedelta(days=random.randint(0, 15))
            bill_date = bill_date.replace(hour=random.randint(8, 22), minute=random.randint(0, 59))
            cust = random.choice(custs) if custs else {'id': None, 'name': 'Walk-in', 'phone': '0000000000'}
            
            # Get random product for the bill
            prod = random.choice(prods)
            qty = random.randint(1, 3)
            subtotal = float(prod['price']) * qty
            gst = round(subtotal * 0.12, 2)
            total = subtotal + gst

            cursor.execute("""
                INSERT INTO bills (bill_number, customer_id, customer_name, phone, subtotal, gst, total_amount, bill_date, created_by, payment_method)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (f"INV-NEW-{i}", cust['id'], cust['name'], cust['phone'], subtotal, gst, total, bill_date, role_user, 'cash'))
            b_id = cursor.lastrowid
            
            cursor.execute("""
                INSERT INTO bill_items (bill_id, product_id, medicine_name, price, quantity, total_amount) 
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (b_id, prod['id'], prod['name'], prod['price'], qty, subtotal))
            
            # Create 3 returns specifically in the recent batch
            if i in [2, 5, 8]:
                cursor.execute("""
                    INSERT INTO returns (bill_id, product_id, quantity, refund_amount, processed_by, return_date)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (b_id, prod['id'], 1, float(prod['price']), role_user, datetime.now()))

        # 4. Force Low Stock (10 Medicines)
        for i in range(min(10, len(prods))):
            lp = prods[i]
            cursor.execute("UPDATE products SET stock_quantity = %s WHERE id = %s", (random.randint(1, 10), lp['id']))
            cursor.execute("UPDATE product_batches SET quantity = %s WHERE product_id = %s", (5, lp['id']))

        conn.commit()
        print("Done! Inventory updated, cashier bills added, and returns processed.")

    except mysql.connector.Error as e:
        print(f"MySQL Error: {e}")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if conn and conn.is_connected():
            conn.close()

if __name__ == "__main__":
    generate_complex_data()