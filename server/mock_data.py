"""
Mock data for the Factory Inventory Management System
This module loads sample data from JSON files for inventory items, orders, demand forecasts, and backlog items.
All data is from September 2025 and includes warehouse, category, and date fields for filtering.
"""

import json
import os
import threading

# Get the directory where this file is located
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')

def load_json_file(filename):
    """Load data from a JSON file in the data directory"""
    filepath = os.path.join(DATA_DIR, filename)
    with open(filepath, 'r') as f:
        return json.load(f)

# Load all datasets from JSON files
inventory_items = load_json_file('inventory.json')
orders = load_json_file('orders.json')
demand_forecasts = load_json_file('demand_forecasts.json')
backlog_items = load_json_file('backlog_items.json')

# Load spending data
spending_data = load_json_file('spending.json')
spending_summary = spending_data['spending_summary']
monthly_spending = spending_data['monthly_spending']
category_spending = spending_data['category_spending']

# Load transactions
recent_transactions = load_json_file('transactions.json')

# Load purchase orders
purchase_orders = load_json_file('purchase_orders.json')

# All data is now loaded from JSON files in the data/ directory
# This allows for easier maintenance and updates of the sample data

# Restocking orders submitted through the app. Unlike the datasets above this file is
# written at runtime, so a missing file is treated as "no orders yet" and it is gitignored.
SUBMITTED_ORDERS_PATH = os.path.join(DATA_DIR, 'submitted_orders.json')
submitted_orders_lock = threading.Lock()

def _load_submitted_orders():
    try:
        with open(SUBMITTED_ORDERS_PATH, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return []

# Callers must mutate this list in place (append), never reassign it: main.py imports it by name.
submitted_orders = _load_submitted_orders()

def save_submitted_orders():
    """Persist submitted_orders atomically. Caller must hold submitted_orders_lock."""
    # Write to a temp file then os.replace so a crash mid-write can't leave truncated JSON.
    tmp_path = SUBMITTED_ORDERS_PATH + '.tmp'
    with open(tmp_path, 'w') as f:
        json.dump(submitted_orders, f, indent=2)
    os.replace(tmp_path, SUBMITTED_ORDERS_PATH)
