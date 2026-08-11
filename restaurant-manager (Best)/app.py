import os
import sqlite3
from datetime import datetime, date
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, session, g
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'restaurant-secret-key-2024')
DATABASE = 'database.db'

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def rows_to_dict(rows):
    """Convert sqlite3.Row objects to plain dicts for template safety"""
    return [dict(row) for row in rows]

# ==================== AUTH DECORATORS ====================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def manager_only(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        if session.get('user_role') != 'Manager':
            flash('Access denied. Manager only.', 'error')
            return redirect(get_first_allowed_route(session.get('user_role')))
        return f(*args, **kwargs)
    return decorated_function

def manager_or_chef(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        if session.get('user_role') not in ['Manager', 'Chef']:
            flash('Access denied. Insufficient permissions.', 'error')
            return redirect(get_first_allowed_route(session.get('user_role')))
        return f(*args, **kwargs)
    return decorated_function

# ==================== PERMISSIONS SYSTEM ====================

def get_role_permissions(role):
    """Get list of section names a role can access"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT section FROM role_permissions WHERE role = ?", (role,))
    perms = [row['section'] for row in cursor.fetchall()]
    conn.close()
    return perms

def has_permission(role, section):
    """Check if a role has access to a section"""
    return section in get_role_permissions(role)

def require_permission(section):
    """Decorator to check if user's role has permission for a section"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('login'))
            role = session.get('user_role')
            if not has_permission(role, section):
                flash('Access denied. You do not have permission for this section.', 'error')
                return redirect(get_first_allowed_route(role))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

@app.route('/sw.js')
def service_worker():
    return app.send_static_file('sw.js')

@app.route('/permissions', methods=['GET', 'POST'])
@manager_only
def manage_permissions():
    conn = get_db()
    cursor = conn.cursor()

    if request.method == 'POST':
        cursor.execute("DELETE FROM role_permissions")
        for key in request.form:
            if key.startswith('perm_'):
                parts = key.split('_', 2)
                if len(parts) == 3:
                    role = parts[1]
                    section = parts[2]
                    cursor.execute(
                        "INSERT INTO role_permissions (role, section) VALUES (?, ?)",
                        (role, section)
                    )
        conn.commit()
        flash('Permissions updated successfully!', 'success')
        conn.close()
        return redirect(url_for('workers'))

    roles = ['Manager', 'Chef', 'Waiter', 'Cashier']
    cursor.execute("SELECT role, section FROM role_permissions")
    perms = {(row['role'], row['section']) for row in cursor.fetchall()}
    conn.close()

    sections = [
        ('dashboard', '📊 Dashboard'),
        ('sales', '🛒 Sales / POS'),
        ('products', '🍕 Products'),
        ('storage', '📦 Storage'),
        ('pre_products', '🥣 Pre-Products'),
        ('purchases', '🚚 Purchases'),
        ('workers', '👥 Workers'),
    ]
    return render_template('permissions.html', roles=roles, perms=perms, sections=sections)

# ==================== CONTEXT & SESSION ====================
@app.context_processor
def inject_user():
    user = None
    if 'user_id' in session:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE id = ?", (session['user_id'],))
        row = cursor.fetchone()
        conn.close()
        if row:
            user = dict(row)
    return dict(current_user=user, get_role_permissions=get_role_permissions)

@app.before_request
def load_user():
    g.user = None
    if 'user_id' in session:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE id = ?", (session['user_id'],))
        row = cursor.fetchone()
        conn.close()
        if row:
            g.user = dict(row)

# ==================== DATABASE ====================
def init_db():
    conn = get_db()
    cursor = conn.cursor()

    # Users/Workers
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT,
        role TEXT DEFAULT 'Waiter',
        phone TEXT,
        password TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Categories
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Articles (raw materials / ingredients)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS articles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        unit TEXT DEFAULT 'kg',
        stock_qty REAL DEFAULT 0,
        avg_cost REAL DEFAULT 0,
        min_stock REAL DEFAULT 10,
        location TEXT DEFAULT 'Storage Room',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Products (menu items for sale)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT,
        price REAL NOT NULL,
        category TEXT DEFAULT 'Food',
        is_active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Product Recipes / BOM
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS product_recipes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER,
        article_id INTEGER,
        quantity_needed REAL,
        FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
        FOREIGN KEY (article_id) REFERENCES articles(id) ON DELETE CASCADE
    )
    """)

    # Purchases
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS purchases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        supplier TEXT NOT NULL,
        invoice_number TEXT,
        total_amount REAL DEFAULT 0,
        status TEXT DEFAULT 'Ordered',
        ordered_by TEXT,
        order_date TEXT DEFAULT CURRENT_TIMESTAMP,
        received_at TEXT
    )
    """)

    # Purchase Items
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS purchase_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        purchase_id INTEGER,
        article_id INTEGER,
        item_name TEXT,
        quantity REAL,
        unit TEXT,
        unit_price REAL,
        total REAL,
        conversion_factor REAL DEFAULT 1,
        storage_unit TEXT,
        storage_qty REAL,
        FOREIGN KEY (purchase_id) REFERENCES purchases(id) ON DELETE CASCADE,
        FOREIGN KEY (article_id) REFERENCES articles(id)
    )
    """)

    # Sales
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sales (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_number TEXT UNIQUE,
        table_number TEXT,
        status TEXT DEFAULT 'Pending',
        total_amount REAL DEFAULT 0,
        discount_value REAL DEFAULT 0,
        discount_type TEXT DEFAULT 'fixed',
        discount_amount REAL DEFAULT 0,
        payment_method TEXT DEFAULT 'Cash',
        cashier_name TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        completed_at TEXT
    )
    """)

    # Pre-Products (intermediate manufactured items)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS pre_products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        unit TEXT DEFAULT 'kg',
        yield_qty REAL DEFAULT 1,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Pre-Product Recipes
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS pre_product_recipes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pre_product_id INTEGER,
        article_id INTEGER,
        quantity_needed REAL,
        FOREIGN KEY (pre_product_id) REFERENCES pre_products(id) ON DELETE CASCADE,
        FOREIGN KEY (article_id) REFERENCES articles(id) ON DELETE CASCADE
    )
    """)

    # Product Pre-Products
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS product_pre_products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER,
        pre_product_id INTEGER,
        quantity_needed REAL,
        FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
        FOREIGN KEY (pre_product_id) REFERENCES pre_products(id) ON DELETE CASCADE
    )
    """)

    # Sale Items
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sale_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sale_id INTEGER,
        product_id INTEGER,
        product_name TEXT,
        quantity INTEGER,
        unit_price REAL,
        total REAL,
        FOREIGN KEY (sale_id) REFERENCES sales(id) ON DELETE CASCADE
    )
    """)

    # Role Permissions
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS role_permissions (
        role TEXT NOT NULL,
        section TEXT NOT NULL,
        PRIMARY KEY (role, section)
    )
    """)

    conn.commit()
    conn.close()

def migrate_if_needed():
    """Check if old DB exists without articles table, backup and recreate"""
    if not os.path.exists(DATABASE):
        init_db()
        seed_data()
        return

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='articles'")
    has_articles = cursor.fetchone()
    conn.close()

    if not has_articles:
        backup_name = 'database.db.backup.' + datetime.now().strftime('%Y%m%d_%H%M%S')
        os.rename(DATABASE, backup_name)
        print(f"Old database backed up to: {backup_name}")
        init_db()
        seed_data()
        print("New database created with updated schema!")

def migrate_db():
    """Add missing columns and ensure default manager exists"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("PRAGMA table_info(users)")
    columns = [row['name'] for row in cursor.fetchall()]

    if 'password' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN password TEXT")
        default_hash = generate_password_hash('123456')
        cursor.execute("UPDATE users SET password = ?", (default_hash,))
        print("Migrated: added password column to users")

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='categories'")
    if not cursor.fetchone():
        cursor.execute("""
        CREATE TABLE categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)
        cursor.execute("INSERT INTO categories (name) VALUES (?)", ('Food',))
        cursor.execute("INSERT INTO categories (name) VALUES (?)", ('Drinks',))
        cursor.execute("INSERT INTO categories (name) VALUES (?)", ('Desserts',))
        cursor.execute("INSERT INTO categories (name) VALUES (?)", ('Sides',))
        cursor.execute("INSERT INTO categories (name) VALUES (?)", ('Other',))
        print("Migrated: created categories table")

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='role_permissions'")
    if not cursor.fetchone():
        cursor.execute("""
        CREATE TABLE role_permissions (
            role TEXT NOT NULL,
            section TEXT NOT NULL,
            PRIMARY KEY (role, section)
        )
        """)
        print("Migrated: created role_permissions table")

    # Seed default permissions if table is empty
    cursor.execute("SELECT COUNT(*) FROM role_permissions")
    if cursor.fetchone()[0] == 0:
        defaults = [
            ('Manager', 'dashboard'), ('Manager', 'sales'), ('Manager', 'products'),
            ('Manager', 'storage'), ('Manager', 'pre_products'), ('Manager', 'purchases'), ('Manager', 'workers'),
            ('Chef', 'dashboard'), ('Chef', 'sales'), ('Chef', 'products'),
            ('Chef', 'storage'), ('Chef', 'pre_products'), ('Chef', 'purchases'),
            ('Waiter', 'dashboard'), ('Waiter', 'sales'),
            ('Cashier', 'dashboard'), ('Cashier', 'sales'),
        ]
        cursor.executemany('INSERT INTO role_permissions (role, section) VALUES (?, ?)', defaults)
        print("Migrated: seeded default role permissions")

    cursor.execute("SELECT * FROM users WHERE role = 'Manager' LIMIT 1")
    if not cursor.fetchone():
        manager_hash = generate_password_hash('admin')
        cursor.execute("""
            INSERT INTO users (name, email, role, phone, password)
            VALUES (?, ?, ?, ?, ?)
        """, ('Manager', 'manager@restaurant.com', 'Manager', '000', manager_hash))
        print("Created default Manager account: manager@restaurant.com / admin")

    conn.commit()
    conn.close()

def seed_data():
    """Insert sample data into fresh database"""
    conn = get_db()
    cursor = conn.cursor()

    manager_hash = generate_password_hash('admin')
    chef_hash = generate_password_hash('123456')
    waiter_hash = generate_password_hash('123456')

    cursor.execute("INSERT INTO users (name, email, role, phone, password) VALUES (?, ?, ?, ?, ?)",
        ('Manager', 'manager@restaurant.com', 'Manager', '555-0100', manager_hash))
    cursor.execute("INSERT INTO users (name, email, role, phone, password) VALUES (?, ?, ?, ?, ?)",
        ('John Smith', 'john@restaurant.com', 'Chef', '555-0101', chef_hash))
    cursor.execute("INSERT INTO users (name, email, role, phone, password) VALUES (?, ?, ?, ?, ?)",
        ('Sarah Jones', 'sarah@restaurant.com', 'Waiter', '555-0102', waiter_hash))

    cursor.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", ('Food',))
    cursor.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", ('Drinks',))
    cursor.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", ('Desserts',))
    cursor.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", ('Sides',))
    cursor.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", ('Other',))

    cursor.execute("INSERT INTO articles (name, unit, stock_qty, avg_cost, min_stock, location) VALUES (?, ?, ?, ?, ?, ?)",
        ('Flour', 'kg', 50, 2.5, 10, 'Storage Room'))
    cursor.execute("INSERT INTO articles (name, unit, stock_qty, avg_cost, min_stock, location) VALUES (?, ?, ?, ?, ?, ?)",
        ('Mozzarella Cheese', 'kg', 20, 8.0, 5, 'Fridge'))
    cursor.execute("INSERT INTO articles (name, unit, stock_qty, avg_cost, min_stock, location) VALUES (?, ?, ?, ?, ?, ?)",
        ('Tomato Sauce', 'L', 15, 3.5, 3, 'Fridge'))
    cursor.execute("INSERT INTO articles (name, unit, stock_qty, avg_cost, min_stock, location) VALUES (?, ?, ?, ?, ?, ?)",
        ('Pasta', 'kg', 30, 3.0, 5, 'Storage Room'))
    cursor.execute("INSERT INTO articles (name, unit, stock_qty, avg_cost, min_stock, location) VALUES (?, ?, ?, ?, ?, ?)",
        ('Bacon', 'kg', 10, 12.0, 2, 'Fridge'))
    cursor.execute("INSERT INTO articles (name, unit, stock_qty, avg_cost, min_stock, location) VALUES (?, ?, ?, ?, ?, ?)",
        ('Coca Cola Cans', 'can', 100, 0.8, 20, 'Storage Room'))
    cursor.execute("INSERT INTO articles (name, unit, stock_qty, avg_cost, min_stock, location) VALUES (?, ?, ?, ?, ?, ?)",
        ('Orange', 'kg', 25, 2.0, 5, 'Fridge'))

    cursor.execute("INSERT INTO products (name, description, price, category) VALUES (?, ?, ?, ?)",
        ('Margherita Pizza', 'Classic tomato and mozzarella', 12.99, 'Food'))
    cursor.execute("INSERT INTO products (name, description, price, category) VALUES (?, ?, ?, ?)",
        ('Pasta Carbonara', 'Creamy bacon pasta', 14.99, 'Food'))
    cursor.execute("INSERT INTO products (name, description, price, category) VALUES (?, ?, ?, ?)",
        ('Caesar Salad', 'Fresh romaine with dressing', 9.99, 'Food'))
    cursor.execute("INSERT INTO products (name, description, price, category) VALUES (?, ?, ?, ?)",
        ('Coca Cola', '330ml can', 2.50, 'Drinks'))
    cursor.execute("INSERT INTO products (name, description, price, category) VALUES (?, ?, ?, ?)",
        ('Orange Juice', 'Freshly squeezed', 4.99, 'Drinks'))

    cursor.execute("INSERT INTO pre_products (name, unit, yield_qty) VALUES (?, ?, ?)",
        ('Mayonnaise', 'kg', 8))
    cursor.execute("INSERT INTO pre_products (name, unit, yield_qty) VALUES (?, ?, ?)",
        ('Tomato Sauce Base', 'L', 5))

    cursor.execute("INSERT INTO pre_product_recipes (pre_product_id, article_id, quantity_needed) VALUES (?, ?, ?)", (1, 1, 4))
    cursor.execute("INSERT INTO pre_product_recipes (pre_product_id, article_id, quantity_needed) VALUES (?, ?, ?)", (1, 3, 10))
    cursor.execute("INSERT INTO pre_product_recipes (pre_product_id, article_id, quantity_needed) VALUES (?, ?, ?)", (2, 3, 2))
    cursor.execute("INSERT INTO pre_product_recipes (pre_product_id, article_id, quantity_needed) VALUES (?, ?, ?)", (2, 3, 0.5))

    cursor.execute("INSERT INTO product_recipes (product_id, article_id, quantity_needed) VALUES (?, ?, ?)", (1, 1, 0.3))
    cursor.execute("INSERT INTO product_recipes (product_id, article_id, quantity_needed) VALUES (?, ?, ?)", (1, 2, 0.2))
    cursor.execute("INSERT INTO product_recipes (product_id, article_id, quantity_needed) VALUES (?, ?, ?)", (1, 3, 0.1))
    cursor.execute("INSERT INTO product_recipes (product_id, article_id, quantity_needed) VALUES (?, ?, ?)", (2, 4, 0.2))
    cursor.execute("INSERT INTO product_recipes (product_id, article_id, quantity_needed) VALUES (?, ?, ?)", (2, 5, 0.15))
    cursor.execute("INSERT INTO product_recipes (product_id, article_id, quantity_needed) VALUES (?, ?, ?)", (4, 6, 1))
    cursor.execute("INSERT INTO product_recipes (product_id, article_id, quantity_needed) VALUES (?, ?, ?)", (5, 7, 0.3))

    cursor.execute("INSERT INTO product_pre_products (product_id, pre_product_id, quantity_needed) VALUES (?, ?, ?)", (3, 1, 0.1))

    # Seed default permissions
    defaults = [
        ('Manager', 'dashboard'), ('Manager', 'sales'), ('Manager', 'products'),
        ('Manager', 'storage'), ('Manager', 'pre_products'), ('Manager', 'purchases'), ('Manager', 'workers'),
        ('Chef', 'dashboard'), ('Chef', 'sales'), ('Chef', 'products'),
        ('Chef', 'storage'), ('Chef', 'pre_products'), ('Chef', 'purchases'),
        ('Waiter', 'dashboard'), ('Waiter', 'sales'),
        ('Cashier', 'dashboard'), ('Cashier', 'sales'),
    ]
    cursor.executemany('INSERT OR IGNORE INTO role_permissions (role, section) VALUES (?, ?)', defaults)

    conn.commit()
    conn.close()

migrate_if_needed()
migrate_db()

# ==================== AUTH ROUTES ====================
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
        user = cursor.fetchone()
        conn.close()

        if user and user['password'] and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['user_role'] = user['role']
            session['user_name'] = user['name']
            flash(f'Welcome back, {user["name"]}!', 'success')
            return redirect(get_first_allowed_route(user['role']))
        else:
            flash('Invalid email or password.', 'error')

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

# ==================== HELPERS ====================
def get_product_cost(product_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT SUM(pr.quantity_needed * a.avg_cost) as total_cost
        FROM product_recipes pr
        JOIN articles a ON pr.article_id = a.id
        WHERE pr.product_id = ?
    """, (product_id,))
    article_cost = cursor.fetchone()['total_cost'] or 0

    cursor.execute("""
        SELECT ppp.quantity_needed, pp.yield_qty,
            (SELECT SUM(ppr.quantity_needed * a.avg_cost)
             FROM pre_product_recipes ppr
             JOIN articles a ON ppr.article_id = a.id
             WHERE ppr.pre_product_id = pp.id) as pre_cost
        FROM product_pre_products ppp
        JOIN pre_products pp ON ppp.pre_product_id = pp.id
        WHERE ppp.product_id = ?
    """, (product_id,))
    pre_items = cursor.fetchall()

    pre_cost = 0
    for item in pre_items:
        if item['yield_qty'] and item['yield_qty'] > 0:
            unit_cost = (item['pre_cost'] or 0) / item['yield_qty']
            pre_cost += unit_cost * item['quantity_needed']

    conn.close()
    return round(article_cost + pre_cost, 2)

def get_product_recipe(product_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT pr.*, a.name as article_name, a.unit as article_unit, a.avg_cost
        FROM product_recipes pr
        JOIN articles a ON pr.article_id = a.id
        WHERE pr.product_id = ?
    """, (product_id,))
    recipe = rows_to_dict(cursor.fetchall())
    conn.close()
    return recipe

def get_pre_product_cost(pre_product_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT SUM(ppr.quantity_needed * a.avg_cost) as total_cost, pp.yield_qty
        FROM pre_product_recipes ppr
        JOIN articles a ON ppr.article_id = a.id
        JOIN pre_products pp ON ppr.pre_product_id = pp.id
        WHERE ppr.pre_product_id = ?
    """, (pre_product_id,))
    result = cursor.fetchone()
    conn.close()
    if result and result['total_cost'] is not None and result['yield_qty'] > 0:
        return round(result['total_cost'] / result['yield_qty'], 2)
    return 0

def get_pre_product_recipe(pre_product_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT ppr.*, a.name as article_name, a.unit as article_unit, a.avg_cost
        FROM pre_product_recipes ppr
        JOIN articles a ON ppr.article_id = a.id
        WHERE ppr.pre_product_id = ?
    """, (pre_product_id,))
    recipe = rows_to_dict(cursor.fetchall())
    conn.close()
    return recipe

def get_product_pre_products(product_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT ppp.*, pp.name as pre_product_name, pp.unit as pre_product_unit, pp.yield_qty
        FROM product_pre_products ppp
        JOIN pre_products pp ON ppp.pre_product_id = pp.id
        WHERE ppp.product_id = ?
    """, (product_id,))
    items = rows_to_dict(cursor.fetchall())
    conn.close()
    return items

# ==================== HELPERS ====================
def get_first_allowed_route(role):
    """Get the first section a role has permission for"""
    perms = get_role_permissions(role)
    section_routes = [
        ('dashboard', '/'),
        ('sales', '/sales'),
        ('products', '/products'),
        ('storage', '/storage'),
        ('pre_products', '/pre-products'),
        ('purchases', '/purchases'),
        ('workers', '/workers'),
    ]
    for section, route in section_routes:
        if section in perms:
            return route
    return '/'

# ==================== DASHBOARD ====================
@app.route('/')
@login_required
def dashboard():
    conn = get_db()
    cursor = conn.cursor()
    # If user doesn't have dashboard permission, redirect to first allowed section
    if not has_permission(session.get('user_role'), 'dashboard'):
        return redirect(get_first_allowed_route(session.get('user_role')))

    today = date.today().isoformat()

    cursor.execute("SELECT COUNT(*), COALESCE(SUM(total_amount), 0) FROM sales WHERE DATE(created_at) = ?", (today,))
    today_sales = cursor.fetchone()

    cursor.execute("SELECT COUNT(*) FROM products WHERE is_active = 1")
    total_products = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM articles WHERE stock_qty <= min_stock")
    low_stock = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM users")
    total_workers = cursor.fetchone()[0]

    cursor.execute("""
        SELECT s.*, GROUP_CONCAT(si.product_name || ' (x' || si.quantity || ')', ', ') as items
        FROM sales s
        LEFT JOIN sale_items si ON s.id = si.sale_id
        GROUP BY s.id
        ORDER BY s.created_at DESC
        LIMIT 5
    """)
    recent_sales = rows_to_dict(cursor.fetchall())

    cursor.execute("""
        SELECT * FROM articles
        WHERE stock_qty <= min_stock
        ORDER BY stock_qty ASC
        LIMIT 10
    """)
    low_stock_items = rows_to_dict(cursor.fetchall())

    cursor.execute("""
        SELECT DATE(created_at) as date, COALESCE(SUM(total_amount), 0) as total
        FROM sales
        WHERE DATE(created_at) >= DATE('now', '-6 days')
        GROUP BY DATE(created_at)
        ORDER BY date
    """)
    chart_data = rows_to_dict(cursor.fetchall())

    conn.close()

    current_date = datetime.now().strftime("%A, %B %d, %Y")

    return render_template('dashboard.html',
        today_orders=today_sales[0] or 0,
        today_revenue=round(today_sales[1] or 0, 2),
        total_products=total_products,
        low_stock=low_stock,
        total_workers=total_workers,
        recent_sales=recent_sales,
        low_stock_items=low_stock_items,
        chart_data=chart_data,
        current_date=current_date)

# ==================== PRODUCTS ====================
@app.route('/products')
@require_permission('products')
def products():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM products ORDER BY created_at DESC")
    products_raw = rows_to_dict(cursor.fetchall())

    products = []
    for p in products_raw:
        p['cost'] = get_product_cost(p['id'])
        p['margin'] = round(((p['price'] - p['cost']) / p['price'] * 100), 1) if p['price'] > 0 else 0
        products.append(p)

    cursor.execute("SELECT id, name, unit, avg_cost FROM articles ORDER BY name")
    articles = rows_to_dict(cursor.fetchall())

    cursor.execute("SELECT id, name, unit, yield_qty FROM pre_products ORDER BY name")
    pre_products_list = rows_to_dict(cursor.fetchall())
    for pp in pre_products_list:
        pp['cost_per_unit'] = get_pre_product_cost(pp['id'])

    cursor.execute("SELECT * FROM categories ORDER BY name")
    categories = rows_to_dict(cursor.fetchall())

    cursor.execute("SELECT product_id, article_id, quantity_needed FROM product_recipes")
    all_recipes = rows_to_dict(cursor.fetchall())
    product_recipes_map = {}
    for r in all_recipes:
        pid = r['product_id']
        if pid not in product_recipes_map:
            product_recipes_map[pid] = []
        product_recipes_map[pid].append(r)

    cursor.execute("SELECT product_id, pre_product_id, quantity_needed FROM product_pre_products")
    all_pre = rows_to_dict(cursor.fetchall())
    product_pre_map = {}
    for r in all_pre:
        pid = r['product_id']
        if pid not in product_pre_map:
            product_pre_map[pid] = []
        product_pre_map[pid].append(r)

    conn.close()
    return render_template('products.html', products=products, articles=articles,
                           pre_products=pre_products_list, categories=categories,
                           product_recipes_map=product_recipes_map, product_pre_map=product_pre_map)

@app.route('/products/add', methods=['POST'])
@manager_or_chef
def add_product():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO products (name, description, price, category)
        VALUES (?, ?, ?, ?)
    """, (request.form['name'], request.form.get('description', ''),
        float(request.form['price']), request.form.get('category', 'Food')))
    product_id = cursor.lastrowid

    article_ids = request.form.getlist('recipe_article_id[]')
    quantities = request.form.getlist('recipe_qty[]')
    for i, aid in enumerate(article_ids):
        if aid and quantities[i] and float(quantities[i]) > 0:
            cursor.execute("""
                INSERT INTO product_recipes (product_id, article_id, quantity_needed)
                VALUES (?, ?, ?)
            """, (product_id, int(aid), float(quantities[i])))

    pre_product_ids = request.form.getlist('recipe_pre_product_id[]')
    pre_quantities = request.form.getlist('recipe_pre_qty[]')
    for i, pid in enumerate(pre_product_ids):
        if pid and pre_quantities[i] and float(pre_quantities[i]) > 0:
            cursor.execute("""
                INSERT INTO product_pre_products (product_id, pre_product_id, quantity_needed)
                VALUES (?, ?, ?)
            """, (product_id, int(pid), float(pre_quantities[i])))

    conn.commit()
    conn.close()
    flash('Product added with recipe!', 'success')
    return redirect('/products')

@app.route('/products/delete/<int:id>')
@manager_or_chef
def delete_product(id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM product_recipes WHERE product_id = ?", (id,))
    cursor.execute("DELETE FROM product_pre_products WHERE product_id = ?", (id,))
    cursor.execute("DELETE FROM products WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    flash('Product deleted!', 'success')
    return redirect('/products')

@app.route('/products/edit/<int:id>', methods=['POST'])
@manager_or_chef
def edit_product(id):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE products SET name = ?, description = ?, price = ?, category = ?
        WHERE id = ?
    """, (request.form['name'], request.form.get('description', ''),
        float(request.form['price']), request.form.get('category', 'Food'), id))

    cursor.execute("DELETE FROM product_recipes WHERE product_id = ?", (id,))
    cursor.execute("DELETE FROM product_pre_products WHERE product_id = ?", (id,))

    article_ids = request.form.getlist('recipe_article_id[]')
    quantities = request.form.getlist('recipe_qty[]')
    for i, aid in enumerate(article_ids):
        if aid and quantities[i] and float(quantities[i]) > 0:
            cursor.execute("""
                INSERT INTO product_recipes (product_id, article_id, quantity_needed)
                VALUES (?, ?, ?)
            """, (id, int(aid), float(quantities[i])))

    pre_product_ids = request.form.getlist('recipe_pre_product_id[]')
    pre_quantities = request.form.getlist('recipe_pre_qty[]')
    for i, pid in enumerate(pre_product_ids):
        if pid and pre_quantities[i] and float(pre_quantities[i]) > 0:
            cursor.execute("""
                INSERT INTO product_pre_products (product_id, pre_product_id, quantity_needed)
                VALUES (?, ?, ?)
            """, (id, int(pid), float(pre_quantities[i])))

    conn.commit()
    conn.close()
    flash('Product updated successfully!', 'success')
    return redirect('/products')

# ==================== CATEGORIES ====================
@app.route('/categories/add', methods=['POST'])
@manager_or_chef
def add_category():
    name = request.form.get('name', '').strip()
    if not name:
        flash('Category name is required.', 'error')
        return redirect('/products')
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO categories (name) VALUES (?)", (name,))
        conn.commit()
        flash(f'Category "{name}" added!', 'success')
    except sqlite3.IntegrityError:
        flash(f'Category "{name}" already exists.', 'error')
    conn.close()
    return redirect('/products')

@app.route('/categories/delete/<int:id>')
@manager_or_chef
def delete_category(id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM categories WHERE id = ?", (id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        flash('Category not found.', 'error')
        return redirect('/products')

    cat_name = row['name']
    cursor.execute("SELECT COUNT(*) FROM products WHERE category = ?", (cat_name,))
    count = cursor.fetchone()[0]
    if count > 0:
        conn.close()
        flash(f'Cannot delete: {count} product(s) are using this category. Reassign them first.', 'error')
        return redirect('/products')

    cursor.execute("DELETE FROM categories WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    flash(f'Category "{cat_name}" deleted!', 'success')
    return redirect('/products')

# ==================== STORAGE / ARTICLES ====================
@app.route('/storage')
@require_permission('storage')
def storage():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM articles ORDER BY created_at DESC")
    items = rows_to_dict(cursor.fetchall())
    conn.close()
    return render_template('storage.html', items=items)

@app.route('/storage/update/<int:id>', methods=['POST'])
@manager_or_chef
def update_article(id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE articles SET stock_qty = ?, min_stock = ?, location = ?, unit = ?, name = ?
        WHERE id = ?
    """, (float(request.form['quantity']), float(request.form['min_stock']),
        request.form['location'], request.form['unit'], request.form['name'], id))
    conn.commit()
    conn.close()
    flash('Article updated!', 'success')
    return redirect('/storage')

@app.route('/storage/delete/<int:id>')
@manager_or_chef
def delete_article(id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM product_recipes WHERE article_id = ?", (id,))
    count = cursor.fetchone()[0]
    if count > 0:
        flash('Cannot delete: this article is used in product recipes!', 'error')
    else:
        cursor.execute("DELETE FROM articles WHERE id = ?", (id,))
        conn.commit()
        flash('Article deleted and stock reset!', 'success')
    conn.close()
    return redirect('/storage')

# ==================== SALES / POS ====================
@app.route('/sales')
@require_permission('sales')
def sales():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM products WHERE is_active = 1 ORDER BY category, name")
    products = rows_to_dict(cursor.fetchall())

    cursor.execute("""
        SELECT s.*, GROUP_CONCAT(si.product_name || ' (x' || si.quantity || ')', ', ') as items
        FROM sales s
        LEFT JOIN sale_items si ON s.id = si.sale_id
        GROUP BY s.id
        ORDER BY s.created_at DESC
        LIMIT 20
    """)
    recent_sales = rows_to_dict(cursor.fetchall())

    cursor.execute("SELECT name FROM users")
    workers = rows_to_dict(cursor.fetchall())

    cursor.execute("SELECT * FROM categories ORDER BY name")
    categories = rows_to_dict(cursor.fetchall())

    conn.close()
    return render_template('sales.html', products=products, recent_sales=recent_sales, workers=workers, categories=categories)

@app.route('/sales/create', methods=['POST'])
@login_required
def create_sale():
    conn = get_db()
    cursor = conn.cursor()

    order_num = 'ORD-' + datetime.now().strftime('%Y%m%d-%H%M%S')
    items = request.form.getlist('product_id[]')
    quantities = request.form.getlist('quantity[]')

    total = 0
    sale_items = []

    for i, prod_id in enumerate(items):
        qty = int(quantities[i])
        if qty > 0:
            cursor.execute("SELECT name, price FROM products WHERE id = ?", (prod_id,))
            product = cursor.fetchone()
            if product:
                item_total = product['price'] * qty
                total += item_total
                sale_items.append({
                    'product_id': prod_id,
                    'name': product['name'],
                    'qty': qty,
                    'price': product['price'],
                    'total': item_total
                })

            cursor.execute("""
                SELECT pr.quantity_needed, pr.article_id, a.stock_qty
                FROM product_recipes pr
                JOIN articles a ON pr.article_id = a.id
                WHERE pr.product_id = ?
            """, (prod_id,))
            recipe = cursor.fetchall()
            for comp in recipe:
                deduct_qty = comp['quantity_needed'] * qty
                new_qty = comp['stock_qty'] - deduct_qty
                if new_qty < 0:
                    new_qty = 0
                cursor.execute("""
                    UPDATE articles SET stock_qty = ? WHERE id = ?
                """, (new_qty, comp['article_id']))

            cursor.execute("""
                SELECT ppp.quantity_needed, ppp.pre_product_id, pp.yield_qty
                FROM product_pre_products ppp
                JOIN pre_products pp ON ppp.pre_product_id = pp.id
                WHERE ppp.product_id = ?
            """, (prod_id,))
            pre_products_used = cursor.fetchall()

            for ppu in pre_products_used:
                pre_qty_needed = ppu['quantity_needed'] * qty
                ratio = pre_qty_needed / ppu['yield_qty'] if ppu['yield_qty'] > 0 else 0

                cursor.execute("""
                    SELECT ppr.quantity_needed, ppr.article_id, a.stock_qty
                    FROM pre_product_recipes ppr
                    JOIN articles a ON ppr.article_id = a.id
                    WHERE ppr.pre_product_id = ?
                """, (ppu['pre_product_id'],))
                pre_recipe = cursor.fetchall()

                for pre_comp in pre_recipe:
                    deduct_qty = pre_comp['quantity_needed'] * ratio
                    new_qty = pre_comp['stock_qty'] - deduct_qty
                    if new_qty < 0:
                        new_qty = 0
                    cursor.execute("""
                        UPDATE articles SET stock_qty = ? WHERE id = ?
                    """, (new_qty, pre_comp['article_id']))

    discount_val = float(request.form.get('discount_value', 0))
    discount_type = request.form.get('discount_type', 'fixed')

    if discount_type == 'percent':
        discount_amount = total * (discount_val / 100)
    else:
        discount_amount = discount_val

    if discount_amount > total:
        discount_amount = total
    if discount_amount < 0:
        discount_amount = 0

    grand_total = total - discount_amount
    if grand_total < 0:
        grand_total = 0

    cursor.execute("""
        INSERT INTO sales (order_number, table_number, status, total_amount, discount_value, discount_type, discount_amount, payment_method, cashier_name)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (order_num, request.form.get('table_number', ''), 'Completed', grand_total, discount_val, discount_type, discount_amount,
        request.form.get('payment_method', 'Cash'), request.form.get('cashier', '')))

    sale_id = cursor.lastrowid

    for item in sale_items:
        cursor.execute("""
            INSERT INTO sale_items (sale_id, product_id, product_name, quantity, unit_price, total)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (sale_id, item['product_id'], item['name'], item['qty'], item['price'], item['total']))

    conn.commit()
    conn.close()
    flash(f'Sale created! Order: {order_num} - Total: DT{grand_total:.2f}', 'success')
    return redirect('/sales')

@app.route('/sales/delete/<int:id>')
@manager_or_chef
def delete_sale(id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sale_items WHERE sale_id = ?", (id,))
    cursor.execute("DELETE FROM sales WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    flash('Sale deleted!', 'success')
    return redirect('/sales')

# ==================== PURCHASES ====================
@app.route('/purchases')
@require_permission('purchases')
def purchases():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT p.*, GROUP_CONCAT(pi.item_name || ' (x' || pi.quantity || ' ' || pi.unit || ')', ', ') as item_summary
        FROM purchases p
        LEFT JOIN purchase_items pi ON p.id = pi.purchase_id
        GROUP BY p.id
        ORDER BY p.order_date DESC
    """)
    purchases = rows_to_dict(cursor.fetchall())

    cursor.execute("SELECT * FROM purchase_items ORDER BY purchase_id, id")
    all_items = rows_to_dict(cursor.fetchall())
    purchase_items_map = {}
    for item in all_items:
        pid = item['purchase_id']
        if pid not in purchase_items_map:
            purchase_items_map[pid] = []
        purchase_items_map[pid].append(item)

    cursor.execute("SELECT name FROM users")
    workers = rows_to_dict(cursor.fetchall())
    conn.close()
    return render_template('purchases.html', purchases=purchases, workers=workers, purchase_items_map=purchase_items_map)

@app.route('/purchases/add', methods=['POST'])
@manager_or_chef
def add_purchase():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO purchases (supplier, invoice_number, status, ordered_by)
        VALUES (?, ?, ?, ?)
    """, (request.form['supplier'], request.form.get('invoice', ''), 'Ordered', request.form.get('ordered_by', '')))

    purchase_id = cursor.lastrowid

    items = request.form.getlist('item_name[]')
    quantities = request.form.getlist('qty[]')
    units = request.form.getlist('unit[]')
    prices = request.form.getlist('price[]')
    conv_factors = request.form.getlist('conv_factor[]')
    storage_units = request.form.getlist('storage_unit[]')
    conv_active_flags = request.form.getlist('conv_active[]')

    total = 0
    for i, name in enumerate(items):
        if name.strip():
            qty = float(quantities[i])
            price = float(prices[i])
            unit = units[i]

            is_conv_active = (i < len(conv_active_flags) and conv_active_flags[i] == '1')

            if is_conv_active:
                conv_factor = float(conv_factors[i]) if i < len(conv_factors) and conv_factors[i] else 1
                storage_unit = storage_units[i] if i < len(storage_units) and storage_units[i] else unit
                storage_qty = qty * conv_factor
            else:
                conv_factor = 1
                storage_unit = unit
                storage_qty = qty

            item_total = price * qty
            total += item_total

            cursor.execute("SELECT id, stock_qty, avg_cost, unit FROM articles WHERE name = ?", (name.strip(),))
            article = cursor.fetchone()

            if article:
                article_id = article['id']
                old_qty = article['stock_qty'] or 0
                old_cost = article['avg_cost'] or 0
                new_qty = old_qty + storage_qty
                new_avg = ((old_qty * old_cost) + item_total) / new_qty if new_qty > 0 else price / conv_factor if conv_factor > 0 else price
                cursor.execute("""
                    UPDATE articles SET stock_qty = ?, avg_cost = ?, unit = ? WHERE id = ?
                """, (new_qty, round(new_avg, 2), storage_unit, article_id))
            else:
                avg_cost = item_total / storage_qty if storage_qty > 0 else price
                cursor.execute("""
                    INSERT INTO articles (name, unit, stock_qty, avg_cost, min_stock)
                    VALUES (?, ?, ?, ?, ?)
                """, (name.strip(), storage_unit, storage_qty, round(avg_cost, 2), 10))
                article_id = cursor.lastrowid

            cursor.execute("""
                INSERT INTO purchase_items (purchase_id, article_id, item_name, quantity, unit, unit_price, total, conversion_factor, storage_unit, storage_qty)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (purchase_id, article_id, name.strip(), qty, unit, price, item_total, conv_factor, storage_unit, storage_qty))

    cursor.execute("UPDATE purchases SET total_amount = ? WHERE id = ?", (total, purchase_id))
    conn.commit()
    conn.close()
    flash('Purchase order created and stock updated!', 'success')
    return redirect('/purchases')

@app.route('/purchases/receive/<int:id>')
@manager_or_chef
def receive_purchase(id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE purchases SET status = 'Received', received_at = CURRENT_TIMESTAMP WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    flash('Purchase marked as received!', 'success')
    return redirect('/purchases')

# ==================== PRE-PRODUCTS ====================
@app.route('/pre-products')
@require_permission('pre_products')
def pre_products():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM pre_products ORDER BY created_at DESC")
    pre_products_raw = rows_to_dict(cursor.fetchall())

    pre_products = []
    for pp in pre_products_raw:
        pp['cost_per_unit'] = get_pre_product_cost(pp['id'])
        pp['recipe'] = get_pre_product_recipe(pp['id'])
        pre_products.append(pp)

    cursor.execute("SELECT id, name, unit, avg_cost FROM articles ORDER BY name")
    articles = rows_to_dict(cursor.fetchall())
    conn.close()
    return render_template('pre_products.html', pre_products=pre_products, articles=articles)

@app.route('/pre-products/add', methods=['POST'])
@manager_or_chef
def add_pre_product():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO pre_products (name, unit, yield_qty)
        VALUES (?, ?, ?)
    """, (request.form['name'], request.form.get('unit', 'kg'), float(request.form.get('yield_qty', 1))))
    pre_product_id = cursor.lastrowid

    article_ids = request.form.getlist('recipe_article_id[]')
    quantities = request.form.getlist('recipe_qty[]')
    for i, aid in enumerate(article_ids):
        if aid and quantities[i] and float(quantities[i]) > 0:
            cursor.execute("""
                INSERT INTO pre_product_recipes (pre_product_id, article_id, quantity_needed)
                VALUES (?, ?, ?)
            """, (pre_product_id, int(aid), float(quantities[i])))

    conn.commit()
    conn.close()
    flash('Pre-product created!', 'success')
    return redirect('/pre-products')

@app.route('/pre-products/delete/<int:id>')
@manager_or_chef
def delete_pre_product(id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM pre_product_recipes WHERE pre_product_id = ?", (id,))
    cursor.execute("DELETE FROM product_pre_products WHERE pre_product_id = ?", (id,))
    cursor.execute("DELETE FROM pre_products WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    flash('Pre-product deleted!', 'success')
    return redirect('/pre-products')

# ==================== WORKERS ====================
@app.route('/workers')
@require_permission('workers')
def workers():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users ORDER BY created_at DESC")
    workers = rows_to_dict(cursor.fetchall())

    cursor.execute("SELECT role, section FROM role_permissions")
    all_perms = {}
    for row in cursor.fetchall():
        if row['role'] not in all_perms:
            all_perms[row['role']] = []
        all_perms[row['role']].append(row['section'])

    conn.close()

    sections = [
        ('dashboard', '📊 Dashboard'),
        ('sales', '🛒 Sales / POS'),
        ('products', '🍕 Products'),
        ('storage', '📦 Storage'),
        ('pre_products', '🥣 Pre-Products'),
        ('purchases', '🚚 Purchases'),
        ('workers', '👥 Workers'),
    ]

    return render_template('workers.html', workers=workers, all_perms=all_perms, sections=sections)

@app.route('/workers/add', methods=['POST'])
@manager_only
def add_worker():
    conn = get_db()
    cursor = conn.cursor()
    password_hash = generate_password_hash(request.form['password'])
    cursor.execute("""
        INSERT INTO users (name, email, role, phone, password)
        VALUES (?, ?, ?, ?, ?)
    """, (request.form['name'], request.form.get('email', ''),
        request.form.get('role', 'Waiter'), request.form.get('phone', ''), password_hash))
    conn.commit()
    conn.close()
    flash('Worker added successfully!', 'success')
    return redirect('/workers')

@app.route('/workers/edit/<int:id>', methods=['POST'])
@manager_only
def edit_worker(id):
    conn = get_db()
    cursor = conn.cursor()

    name = request.form['name']
    email = request.form.get('email', '')
    role = request.form.get('role', 'Waiter')
    phone = request.form.get('phone', '')

    # Only update password if provided
    password = request.form.get('password', '')
    if password:
        password_hash = generate_password_hash(password)
        cursor.execute("""
            UPDATE users SET name = ?, email = ?, role = ?, phone = ?, password = ?
            WHERE id = ?
        """, (name, email, role, phone, password_hash, id))
    else:
        cursor.execute("""
            UPDATE users SET name = ?, email = ?, role = ?, phone = ?
            WHERE id = ?
        """, (name, email, role, phone, id))

    # Update role permissions
    cursor.execute("DELETE FROM role_permissions WHERE role = ?", (role,))
    for key in request.form:
        if key.startswith('perm_'):
            section = key.split('_', 1)[1]
            cursor.execute("INSERT INTO role_permissions (role, section) VALUES (?, ?)", (role, section))

    conn.commit()
    conn.close()
    flash('Worker and role permissions updated!', 'success')
    return redirect('/workers')

@app.route('/workers/delete/<int:id>')
@manager_only
def delete_worker(id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    flash('Worker removed!', 'success')
    return redirect('/workers')

if __name__ == '__main__':
    print("="*60)
    print("RESTAURANT MANAGER STARTED!")
    print("Open your browser and go to: http://127.0.0.1:5000")
    print("Default login: manager@restaurant.com / admin")
    print("="*60)
    app.run(debug=True, host='0.0.0.0', port=5000)
