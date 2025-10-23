from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import date
from typing import Optional
import aiosqlite

app = FastAPI(title="Cost Manager")

DB_FILE = "sales.db"
CATEGORIES_FILE = "categories.json"

# Load categories
import json
try:
    with open(CATEGORIES_FILE, 'r') as f:
        CATEGORIES = json.load(f)
except FileNotFoundError:
    CATEGORIES = {"misc": ["other"]}

async def init_db():
    async with aiosqlite.connect(DB_FILE) as db:
        # Check if old schema exists
        async with db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sales'") as cursor:
            old_sales = await cursor.fetchone()
        
        if old_sales:
            # Check if customer_id column exists
            async with db.execute("PRAGMA table_info(sales)") as cursor:
                columns = await cursor.fetchall()
                has_customer_id = any(col[1] == 'customer_id' for col in columns)
            
            if not has_customer_id:
                print("⚠️  Old database schema detected. Migrating...")
                # Backup old data
                await db.execute("ALTER TABLE sales RENAME TO sales_old")
                await db.execute("ALTER TABLE payments RENAME TO payments_old")
                
        # Create new schema
        await db.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                phone TEXT UNIQUE NOT NULL,
                location TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER NOT NULL,
                item TEXT NOT NULL,
                category TEXT NOT NULL,
                sub_category TEXT NOT NULL,
                total_price REAL NOT NULL,
                sale_date TEXT NOT NULL,
                paid REAL DEFAULT 0,
                remaining REAL DEFAULT 0,
                FOREIGN KEY (customer_id) REFERENCES customers(id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sale_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                payment_date TEXT NOT NULL,
                note TEXT DEFAULT '',
                FOREIGN KEY (sale_id) REFERENCES sales(id)
            )
        """)
        
        # Migrate old data if exists
        async with db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sales_old'") as cursor:
            if await cursor.fetchone():
                print("📦 Migrating old sales data...")
                # Create default customer for old sales
                await db.execute(
                    "INSERT INTO customers (name, phone, location) VALUES (?, ?, ?)",
                    ("Legacy Customer", "0000000000", "Unknown")
                )
                legacy_customer_id = 1
                
                # Migrate old sales
                async with db.execute("SELECT * FROM sales_old") as cursor:
                    old_sales = await cursor.fetchall()
                    for sale in old_sales:
                        await db.execute(
                            "INSERT INTO sales (customer_id, item, category, sub_category, total_price, sale_date, paid, remaining) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (legacy_customer_id, sale[3], "misc", "other", sale[4], sale[5], sale[6], sale[7])
                        )
                
                # Migrate payments
                async with db.execute("SELECT * FROM payments_old") as cursor:
                    old_payments = await cursor.fetchall()
                    for payment in old_payments:
                        await db.execute(
                            "INSERT INTO payments (sale_id, amount, payment_date, note) VALUES (?, ?, ?, ?)",
                            (payment[1], payment[2], payment[3], payment[4])
                        )
                
                # Drop old tables
                await db.execute("DROP TABLE sales_old")
                await db.execute("DROP TABLE payments_old")
                print("✅ Migration complete!")
        
        await db.commit()

@app.on_event("startup")
async def startup():
    await init_db()

# Data models
class Customer(BaseModel):
    name: str
    phone: str
    location: str

class Sale(BaseModel):
    customer_id: int
    item: str
    category: str
    sub_category: str
    total_price: float
    sale_date: date
    paid: float = 0

class Payment(BaseModel):
    sale_id: int
    amount: float
    payment_date: date
    note: str = ""

@app.post("/customers/")
async def create_customer(customer: Customer):
    async with aiosqlite.connect(DB_FILE) as db:
        try:
            cursor = await db.execute(
                "INSERT INTO customers (name, phone, location) VALUES (?, ?, ?)",
                (customer.name, customer.phone, customer.location)
            )
            await db.commit()
            return {"message": "Customer created", "customer_id": cursor.lastrowid}
        except aiosqlite.IntegrityError:
            raise HTTPException(400, "Phone number already exists")

@app.get("/customers/")
async def list_customers():
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM customers ORDER BY name") as cursor:
            customers = await cursor.fetchall()
            return {"customers": [dict(c) for c in customers]}

@app.get("/customers/{customer_id}")
async def get_customer(customer_id: int):
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)) as cursor:
            customer = await cursor.fetchone()
            if not customer:
                raise HTTPException(404, "Customer not found")
        
        async with db.execute("SELECT * FROM sales WHERE customer_id = ? ORDER BY sale_date DESC", (customer_id,)) as cursor:
            sales = await cursor.fetchall()
        
        total_purchased = sum(s['total_price'] for s in sales)
        total_paid = sum(s['paid'] for s in sales)
        total_remaining = sum(s['remaining'] for s in sales)
        
        return {
            "customer": dict(customer),
            "sales": [dict(s) for s in sales],
            "summary": {
                "total_purchased": total_purchased,
                "total_paid": total_paid,
                "total_remaining": total_remaining
            }
        }

@app.get("/categories/")
async def get_categories():
    return {"categories": CATEGORIES}

@app.post("/sales/")
async def create_sale(sale: Sale):
    # Validate category
    if sale.category not in CATEGORIES:
        raise HTTPException(400, f"Invalid category. Choose from: {list(CATEGORIES.keys())}")
    if sale.sub_category not in CATEGORIES[sale.category]:
        raise HTTPException(400, f"Invalid sub_category for {sale.category}. Choose from: {CATEGORIES[sale.category]}")
    
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT id FROM customers WHERE id = ?", (sale.customer_id,)) as cursor:
            customer = await cursor.fetchone()
            if not customer:
                raise HTTPException(404, "Customer not found")
        
        remaining = sale.total_price - sale.paid
        cursor = await db.execute(
            "INSERT INTO sales (customer_id, item, category, sub_category, total_price, sale_date, paid, remaining) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (sale.customer_id, sale.item, sale.category, sale.sub_category, sale.total_price, str(sale.sale_date), sale.paid, remaining)
        )
        sale_id = cursor.lastrowid
        
        if sale.paid > 0:
            await db.execute(
                "INSERT INTO payments (sale_id, amount, payment_date, note) VALUES (?, ?, ?, ?)",
                (sale_id, sale.paid, str(sale.sale_date), "Initial payment")
            )
        await db.commit()
    
    return {"message": "Sale created", "sale_id": sale_id, "remaining": remaining}

@app.post("/payments/")
async def add_payment(payment: Payment):
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM sales WHERE id = ?", (payment.sale_id,)) as cursor:
            sale = await cursor.fetchone()
            if not sale:
                raise HTTPException(404, "Sale not found")
        
        if payment.amount > sale['remaining']:
            raise HTTPException(400, f"Payment exceeds remaining balance of {sale['remaining']}")
        
        new_paid = sale['paid'] + payment.amount
        new_remaining = sale['remaining'] - payment.amount
        
        await db.execute("UPDATE sales SET paid = ?, remaining = ? WHERE id = ?", 
                    (new_paid, new_remaining, payment.sale_id))
        await db.execute("INSERT INTO payments (sale_id, amount, payment_date, note) VALUES (?, ?, ?, ?)",
                    (payment.sale_id, payment.amount, str(payment.payment_date), payment.note))
        await db.commit()
    
    return {"message": "Payment added", "remaining": new_remaining}

@app.get("/sales/")
async def list_sales():
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT s.*, c.name as customer_name, c.phone, c.location 
            FROM sales s 
            JOIN customers c ON s.customer_id = c.id 
            ORDER BY s.sale_date DESC
        """) as cursor:
            sales = await cursor.fetchall()
            return {"sales": [dict(s) for s in sales]}

@app.get("/sales/{sale_id}")
async def get_sale(sale_id: int):
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT s.*, c.name as customer_name, c.phone, c.location 
            FROM sales s 
            JOIN customers c ON s.customer_id = c.id 
            WHERE s.id = ?
        """, (sale_id,)) as cursor:
            sale = await cursor.fetchone()
            if not sale:
                raise HTTPException(404, "Sale not found")
        
        async with db.execute("SELECT * FROM payments WHERE sale_id = ? ORDER BY payment_date", (sale_id,)) as cursor:
            payments = await cursor.fetchall()
        
        return {"sale": dict(sale), "payments": [dict(p) for p in payments]}

@app.get("/monthly-summary/{year}/{month}")
async def monthly_summary(year: int, month: int):
    start = f"{year}-{month:02d}-01"
    end = f"{year}-{month:02d}-31"
    
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT SUM(amount) as total, COUNT(*) as count FROM payments WHERE payment_date BETWEEN ? AND ?",
            (start, end)
        ) as cursor:
            payments = await cursor.fetchone()
        
        async with db.execute(
            "SELECT SUM(total_price) as total, COUNT(*) as count FROM sales WHERE sale_date BETWEEN ? AND ?",
            (start, end)
        ) as cursor:
            sales = await cursor.fetchone()
        
        async with db.execute("SELECT SUM(remaining) as total FROM sales") as cursor:
            outstanding = await cursor.fetchone()
    
    return {
        "month": f"{year}-{month:02d}",
        "payments_received": payments['total'] or 0,
        "new_sales_total": sales['total'] or 0,
        "outstanding_balance": outstanding['total'] or 0,
        "payments_count": payments['count'] or 0,
        "new_sales_count": sales['count'] or 0
    }

@app.get("/outstanding/")
async def outstanding_sales():
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT s.*, c.name as customer_name, c.phone, c.location 
            FROM sales s 
            JOIN customers c ON s.customer_id = c.id 
            WHERE s.remaining > 0 
            ORDER BY s.sale_date
        """) as cursor:
            unpaid = await cursor.fetchall()
        
        async with db.execute("SELECT SUM(remaining) as total FROM sales WHERE remaining > 0") as cursor:
            total = await cursor.fetchone()
        
        return {
            "outstanding_sales": [dict(s) for s in unpaid], 
            "total_outstanding": total['total'] or 0
        }

if __name__ == "__main__":
    import uvicorn
    print("🚀 Starting Async Sales Tracker API on http://localhost:8000")
    print("📚 API docs: http://localhost:8000/docs")
    print("💾 Database: sales.db (async)")
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=True)