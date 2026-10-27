"""
Pharmacy Sales Management System  (Flask + MySQL, everything in one file)

HOW IT FITS TOGETHER (for your viva):
  Browser (HTML/JS UI)  --HTTP/JSON-->  Flask routes (this file)  --SQL-->  MySQL database
  1. The UI at "/" is a web page served by Flask. It calls URLs like /api/medicine.
  2. Each route validates the input, then runs SQL through mysql-connector-python.
  3. MySQL stores the data and enforces keys/constraints as the last line of defence.

SETUP
  pip install flask mysql-connector-python
  Set your MySQL login (or edit the defaults below):
      Windows (cmd):  set DB_USER=root & set DB_PASSWORD=yourpassword
      Mac/Linux:      export DB_USER=root DB_PASSWORD=yourpassword
  python pharmacy_app.py            -> creates the database + sample data, opens http://localhost:5000
  python pharmacy_app.py --reset    -> drops and recreates the database with fresh sample data
  python pharmacy_app.py --print-sql-> prints the CREATE TABLE script (for the report / MySQL Workbench)
"""
import os
import re
import sys
from datetime import date, timedelta
from decimal import Decimal

import mysql.connector
from flask import Flask, jsonify, request
from mysql.connector import errors as dberr

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "pharmacy_db")

# ============================================================================
# 1. DATABASE SCHEMA
# Improvements over the ER diagram (explain these in the report):
#  * Sale_Details gets its own key (detail_id) and stores Medicine_ID (a foreign key)
#    instead of a medicine NAME, so names/prices are not duplicated (3NF).
#  * Sale_Details.unit_price keeps the price AT THE TIME OF SALE, so old bills do not
#    change when a medicine's price is edited later.
#  * Medicine has Supplier_ID: this is how "suppliers supply medicines" is stored (1 supplier : many medicines).
#  * CHECK constraints stop negative stock, zero prices and zero quantities.
#  * ON DELETE RESTRICT protects history: you cannot delete a customer/employee/medicine used in a sale.
#    Deleting a sale removes its own detail rows (ON DELETE CASCADE).
# ============================================================================
SCHEMA = [
    """CREATE TABLE IF NOT EXISTS supplier (
        supplier_id INT AUTO_INCREMENT PRIMARY KEY,
        name        VARCHAR(100) NOT NULL,
        phone       VARCHAR(15)  NOT NULL,
        address     VARCHAR(255)
    ) ENGINE=InnoDB""",
    """CREATE TABLE IF NOT EXISTS customer (
        customer_id INT AUTO_INCREMENT PRIMARY KEY,
        name        VARCHAR(100) NOT NULL,
        phone       VARCHAR(15)  NOT NULL,
        address     VARCHAR(255)
    ) ENGINE=InnoDB""",
    """CREATE TABLE IF NOT EXISTS employee (
        employee_id INT AUTO_INCREMENT PRIMARY KEY,
        name        VARCHAR(100) NOT NULL,
        position    VARCHAR(50)  NOT NULL,
        phone       VARCHAR(15)  NOT NULL,
        salary      DECIMAL(10,2) NOT NULL,
        CONSTRAINT chk_salary CHECK (salary >= 0)
    ) ENGINE=InnoDB""",
    """CREATE TABLE IF NOT EXISTS medicine (
        medicine_id INT AUTO_INCREMENT PRIMARY KEY,
        supplier_id INT NOT NULL,
        category    VARCHAR(50)  NOT NULL,
        name        VARCHAR(100) NOT NULL,
        expiry_date DATE         NOT NULL,
        stock       INT          NOT NULL DEFAULT 0,
        price       DECIMAL(10,2) NOT NULL,
        CONSTRAINT chk_stock CHECK (stock >= 0),
        CONSTRAINT chk_price CHECK (price > 0),
        CONSTRAINT fk_med_supplier FOREIGN KEY (supplier_id)
            REFERENCES supplier(supplier_id) ON DELETE RESTRICT
    ) ENGINE=InnoDB""",
    """CREATE TABLE IF NOT EXISTS sales (
        sale_id      INT AUTO_INCREMENT PRIMARY KEY,
        sale_date    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        total_amount DECIMAL(10,2) NOT NULL,
        customer_id  INT NOT NULL,
        employee_id  INT NOT NULL,
        CONSTRAINT chk_total CHECK (total_amount >= 0),
        CONSTRAINT fk_sale_customer FOREIGN KEY (customer_id)
            REFERENCES customer(customer_id) ON DELETE RESTRICT,
        CONSTRAINT fk_sale_employee FOREIGN KEY (employee_id)
            REFERENCES employee(employee_id) ON DELETE RESTRICT
    ) ENGINE=InnoDB""",
    """CREATE TABLE IF NOT EXISTS sale_details (
        detail_id   INT AUTO_INCREMENT PRIMARY KEY,
        sale_id     INT NOT NULL,
        medicine_id INT NOT NULL,
        quantity    INT NOT NULL,
        unit_price  DECIMAL(10,2) NOT NULL,
        CONSTRAINT chk_qty CHECK (quantity > 0),
        CONSTRAINT uq_sale_medicine UNIQUE (sale_id, medicine_id),
        CONSTRAINT fk_det_sale FOREIGN KEY (sale_id)
            REFERENCES sales(sale_id) ON DELETE CASCADE,
        CONSTRAINT fk_det_medicine FOREIGN KEY (medicine_id)
            REFERENCES medicine(medicine_id) ON DELETE RESTRICT
    ) ENGINE=InnoDB""",
]


def connect(with_db=True):
    kw = dict(host=DB_HOST, user=DB_USER, password=DB_PASSWORD)
    if with_db:
        kw["database"] = DB_NAME
    return mysql.connector.connect(**kw)


def run(sql, args=(), one=False, write=False):
    """Run one statement. Reads return dict rows; writes return the new row id."""
    cn = connect()
    try:
        cur = cn.cursor(dictionary=True)
        cur.execute(sql, args)
        if write:
            cn.commit()
            return cur.lastrowid
        rows = cur.fetchall()
        return (rows[0] if rows else None) if one else rows
    finally:
        cn.close()


def init_db(reset=False):
    cn = connect(with_db=False)
    cur = cn.cursor()
    if reset:
        cur.execute(f"DROP DATABASE IF EXISTS {DB_NAME}")
    cur.execute(f"CREATE DATABASE IF NOT EXISTS {DB_NAME} CHARACTER SET utf8mb4")
    cn.close()
    cn = connect()
    cur = cn.cursor()
    for stmt in SCHEMA:
        cur.execute(stmt)
    cn.commit()
    cn.close()
    if not run("SELECT 1 AS x FROM medicine LIMIT 1", one=True):
        seed()


def seed():
    d = date.today()
    sup = [("HealthPlus Distributors", "0300111222", "12 Market Road, Lahore"),
           ("MediCare Supplies", "0321333444", "45 Industrial Area, Karachi"),
           ("PharmaLink", "0345555666", "7 Canal Avenue, Islamabad")]
    for s in sup:
        run("INSERT INTO supplier(name,phone,address) VALUES (%s,%s,%s)", s, write=True)
    for c in [("Walk-in Customer", "0000000000", "-"), ("Ayesha Khan", "0300123456", "House 5, Street 2, Lahore"),
              ("Bilal Ahmed", "0312987654", "Flat 9, Gulshan, Karachi"), ("Sara Malik", "0333456789", "Sector F-8, Islamabad")]:
        run("INSERT INTO customer(name,phone,address) VALUES (%s,%s,%s)", c, write=True)
    for e in [("Usman Tariq", "Pharmacist", "0301000001", 85000), ("Hina Raza", "Cashier", "0301000002", 45000),
              ("Imran Ali", "Manager", "0301000003", 120000)]:
        run("INSERT INTO employee(name,position,phone,salary) VALUES (%s,%s,%s,%s)", e, write=True)
    meds = [(1, "Painkiller", "Paracetamol 500mg", d + timedelta(days=540), 200, "2.50"),
            (1, "Antibiotic", "Amoxicillin 250mg", d + timedelta(days=300), 120, "12.00"),
            (2, "Antacid", "Antacid Syrup 120ml", d + timedelta(days=200), 60, "85.00"),
            (2, "Vitamin", "Vitamin C 1000mg", d + timedelta(days=400), 150, "6.00"),
            (3, "Allergy", "Cetirizine 10mg", d + timedelta(days=25), 5, "4.00"),       # low stock, expiring soon
            (3, "Cough", "Cough Syrup 100ml", d - timedelta(days=10), 30, "95.00"),    # EXPIRED: cannot be sold
            (1, "Diabetes", "Metformin 500mg", d + timedelta(days=700), 90, "5.50"),
            (3, "First Aid", "Antiseptic Cream 20g", d + timedelta(days=600), 40, "55.00")]
    for m in meds:
        run("INSERT INTO medicine(supplier_id,category,name,expiry_date,stock,price) VALUES (%s,%s,%s,%s,%s,%s)", m, write=True)
    create_sale({"customer_id": 2, "employee_id": 1, "items": [{"medicine_id": 1, "quantity": 10}, {"medicine_id": 4, "quantity": 2}]})
    create_sale({"customer_id": 3, "employee_id": 2, "items": [{"medicine_id": 2, "quantity": 3}, {"medicine_id": 3, "quantity": 1}]})


# ============================================================================
# 2. ENTITY DEFINITIONS + VALIDATION
# One description per table drives the API, the validation AND the forms in the UI.
# types: text | phone | int | money | date | fk (foreign key, "ref" = referenced entity)
# ============================================================================
def F(n, l, t, req=True, **kw):
    return dict(n=n, l=l, t=t, req=req, **kw)


ENT = {
    "customer": dict(table="customer", pk="customer_id", label="Customers",
                     sql="SELECT c.* FROM customer c", search=["c.name", "c.phone", "c.address"], order="c.name",
                     fields=[F("name", "Name", "text", max=100), F("phone", "Phone", "phone"),
                             F("address", "Address", "text", False, max=255)]),
    "employee": dict(table="employee", pk="employee_id", label="Employees",
                     sql="SELECT e.* FROM employee e", search=["e.name", "e.position", "e.phone"], order="e.name",
                     fields=[F("name", "Name", "text", max=100), F("position", "Position", "text", max=50),
                             F("phone", "Phone", "phone"), F("salary", "Salary", "money", min=0)]),
    "supplier": dict(table="supplier", pk="supplier_id", label="Suppliers",
                     sql="SELECT s.* FROM supplier s", search=["s.name", "s.phone", "s.address"], order="s.name",
                     fields=[F("name", "Name", "text", max=100), F("phone", "Phone", "phone"),
                             F("address", "Address", "text", False, max=255)]),
    "medicine": dict(table="medicine", pk="medicine_id", label="Medicines",
                     sql="SELECT m.*, s.name AS supplier_name FROM medicine m JOIN supplier s ON s.supplier_id=m.supplier_id",
                     search=["m.name", "m.category", "s.name"], order="m.name",
                     fields=[F("name", "Name", "text", max=100), F("category", "Category", "text", max=50),
                             F("supplier_id", "Supplier", "fk", ref="supplier", show="supplier_name"),
                             F("expiry_date", "Expiry date", "date"), F("stock", "Stock", "int", min=0),
                             F("price", "Price", "money", min=0.01)]),
}


def validate(cfg, data):
    clean, errs = {}, []
    for f in cfg["fields"]:
        raw, label = data.get(f["n"]), f["l"]
        raw = raw.strip() if isinstance(raw, str) else raw
        if raw in (None, ""):
            if f["req"]:
                errs.append(f"{label} is required.")
            clean[f["n"]] = None
            continue
        try:
            if f["t"] == "text":
                if len(raw) > f["max"]:
                    raise ValueError(f"{label} must be at most {f['max']} characters.")
                raw = str(raw)
            elif f["t"] == "phone":
                if not re.fullmatch(r"\+?[0-9][0-9\- ]{6,14}", str(raw)):
                    raise ValueError(f"{label} must be 7-15 digits (spaces, - and a leading + are allowed).")
                raw = str(raw)
            elif f["t"] in ("int", "fk"):
                if not re.fullmatch(r"-?\d+", str(raw)):
                    raise ValueError(f"{label} must be a whole number.")
                raw = int(raw)
                if "min" in f and raw < f["min"]:
                    raise ValueError(f"{label} must be at least {f['min']}.")
            elif f["t"] == "money":
                raw = Decimal(str(raw))
                if raw.as_tuple().exponent < -2 or not raw.is_finite():
                    raise ValueError(f"{label} must be a valid amount with at most 2 decimals.")
                if raw < Decimal(str(f.get("min", 0))):
                    raise ValueError(f"{label} must be at least {f.get('min', 0)}.")
                if raw >= Decimal("100000000"):
                    raise ValueError(f"{label} is too large.")
            elif f["t"] == "date":
                raw = date.fromisoformat(str(raw))
        except (ValueError, ArithmeticError) as e:
            errs.append(str(e) if "must" in str(e) or "large" in str(e) else f"{label} is not valid.")
            continue
        clean[f["n"]] = raw
    return clean, errs


class ApiError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


# ============================================================================
# 3. SALE LOGIC  (the transaction: all-or-nothing)
# ============================================================================
def to_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def create_sale(data):
    customer_id, employee_id = to_int(data.get("customer_id")), to_int(data.get("employee_id"))
    errs, merged = [], {}
    if not customer_id:
        errs.append("Select a customer.")
    if not employee_id:
        errs.append("Select the employee handling the sale.")
    items = data.get("items") or []
    if not items:
        errs.append("Add at least one medicine to the sale.")
    for it in items:
        mid, qty = to_int(it.get("medicine_id")), to_int(it.get("quantity"))
        if not mid:
            errs.append("Every item row needs a medicine.")
        elif not qty or qty < 1:
            errs.append("Quantity must be a whole number of at least 1.")
        else:
            merged[mid] = merged.get(mid, 0) + qty  # same medicine twice -> one line
    if errs:
        raise ApiError(422, " ".join(dict.fromkeys(errs)))

    cn = connect()
    try:
        cn.start_transaction()
        cur = cn.cursor(dictionary=True)
        for table, pk, val, name in (("customer", "customer_id", customer_id, "Customer"),
                                     ("employee", "employee_id", employee_id, "Employee")):
            cur.execute(f"SELECT {pk} FROM {table} WHERE {pk}=%s", (val,))
            if not cur.fetchone():
                raise ApiError(422, f"{name} does not exist.")
        total, lines = Decimal("0.00"), []
        # Lock each medicine row (FOR UPDATE) in id order: two cashiers selling the same
        # medicine at once cannot both read the same stock, and ordering avoids deadlocks.
        for mid in sorted(merged):
            cur.execute("SELECT medicine_id,name,price,stock,expiry_date FROM medicine WHERE medicine_id=%s FOR UPDATE", (mid,))
            m = cur.fetchone()
            if not m:
                raise ApiError(422, f"Medicine #{mid} does not exist.")
            if m["expiry_date"] < date.today():
                raise ApiError(409, f"{m['name']} expired on {m['expiry_date']} and cannot be sold.")
            if merged[mid] > m["stock"]:
                raise ApiError(409, f"Not enough stock for {m['name']}: requested {merged[mid]}, available {m['stock']}.")
            total += m["price"] * merged[mid]  # total is calculated on the SERVER from DB prices
            lines.append((m, merged[mid]))
        cur.execute("INSERT INTO sales(total_amount,customer_id,employee_id) VALUES (%s,%s,%s)", (total, customer_id, employee_id))
        sale_id = cur.lastrowid
        for m, qty in lines:
            cur.execute("INSERT INTO sale_details(sale_id,medicine_id,quantity,unit_price) VALUES (%s,%s,%s,%s)",
                        (sale_id, m["medicine_id"], qty, m["price"]))
            cur.execute("UPDATE medicine SET stock = stock - %s WHERE medicine_id=%s", (qty, m["medicine_id"]))
        cn.commit()
        return {"sale_id": sale_id, "total_amount": total}
    except Exception:
        cn.rollback()  # any failure undoes the sale AND the stock changes
        raise
    finally:
        cn.close()


# ============================================================================
# 4. API (Flask routes)
# ============================================================================
app = Flask(__name__)


def _json_default(o):
    if isinstance(o, Decimal):
        return float(o)
    if hasattr(o, "isoformat"):
        return o.isoformat(sep=" ") if hasattr(o, "hour") else o.isoformat()
    raise TypeError


app.json.default = _json_default


@app.errorhandler(ApiError)
def _api_error(e):
    return jsonify(error=e.message), e.status


@app.errorhandler(dberr.IntegrityError)
def _integrity(e):
    if e.errno == 1451:
        return jsonify(error="This record is used by other records (for example past sales or medicines) and cannot be deleted."), 409
    if e.errno == 1452:
        return jsonify(error="A selected related record does not exist."), 422
    if e.errno == 4025 or e.errno == 3819:
        return jsonify(error="A value broke a database rule (negative stock, price or quantity)."), 422
    return jsonify(error="Database rule violated: " + str(e.msg)), 409


@app.errorhandler(dberr.Error)
def _db(e):
    return jsonify(error="Database error: " + str(e)), 500


@app.get("/api/meta")
def meta():
    return jsonify({k: dict(label=c["label"], pk=c["pk"], fields=c["fields"]) for k, c in ENT.items()})


@app.get("/api/<ent>")
def list_rows(ent):
    cfg = ENT.get(ent) or (_ for _ in ()).throw(ApiError(404, "Unknown resource."))
    q, sql, args = request.args.get("q", "").strip(), cfg["sql"], []
    if q:
        sql += " WHERE " + " OR ".join(f"{c} LIKE %s" for c in cfg["search"])
        args = [f"%{q}%"] * len(cfg["search"])
        if q.isdigit():
            sql += f" OR {cfg['sql'].split(' FROM ')[1].split()[1]}.{cfg['pk']} = %s"
            args.append(int(q))
    return jsonify(run(sql + f" ORDER BY {cfg['order']}", args))


def _save(ent, rid=None):
    cfg = ENT.get(ent) or (_ for _ in ()).throw(ApiError(404, "Unknown resource."))
    clean, errs = validate(cfg, request.get_json(silent=True) or {})
    if errs:
        raise ApiError(422, " ".join(errs))
    cols = [f["n"] for f in cfg["fields"]]
    if rid is None:
        new = run(f"INSERT INTO {cfg['table']}({','.join(cols)}) VALUES ({','.join(['%s'] * len(cols))})",
                  [clean[c] for c in cols], write=True)
    else:
        if not run(f"SELECT 1 AS x FROM {cfg['table']} WHERE {cfg['pk']}=%s", (rid,), one=True):
            raise ApiError(404, "Record not found.")
        run(f"UPDATE {cfg['table']} SET {','.join(c + '=%s' for c in cols)} WHERE {cfg['pk']}=%s",
            [clean[c] for c in cols] + [rid], write=True)
        new = rid
    return jsonify(run(f"{cfg['sql']} WHERE {cfg['sql'].split(' FROM ')[1].split()[1]}.{cfg['pk']}=%s", (new,), one=True))


@app.post("/api/<ent>")
def create_row(ent):
    return _save(ent), 201


@app.put("/api/<ent>/<int:rid>")
def update_row(ent, rid):
    return _save(ent, rid)


@app.delete("/api/<ent>/<int:rid>")
def delete_row(ent, rid):
    cfg = ENT.get(ent) or (_ for _ in ()).throw(ApiError(404, "Unknown resource."))
    cn = connect()
    try:
        cur = cn.cursor()
        cur.execute(f"DELETE FROM {cfg['table']} WHERE {cfg['pk']}=%s", (rid,))
        cn.commit()
        if cur.rowcount == 0:
            raise ApiError(404, "Record not found.")
    finally:
        cn.close()
    return "", 204


@app.post("/api/sales")
def new_sale():
    return jsonify(create_sale(request.get_json(silent=True) or {})), 201


@app.get("/api/sales")
def list_sales():
    q, sql, args = request.args.get("q", "").strip(), """
        SELECT s.sale_id, s.sale_date, s.total_amount, c.name AS customer, e.name AS employee,
               (SELECT COUNT(*) FROM sale_details d WHERE d.sale_id = s.sale_id) AS items
        FROM sales s JOIN customer c ON c.customer_id=s.customer_id JOIN employee e ON e.employee_id=s.employee_id""", []
    if q:
        sql += " WHERE c.name LIKE %s OR e.name LIKE %s OR s.sale_id = %s OR DATE(s.sale_date) = %s"
        args = [f"%{q}%", f"%{q}%", to_int(q) or 0, q]
    return jsonify(run(sql + " ORDER BY s.sale_id DESC", args))


@app.get("/api/sales/<int:sid>")
def sale_detail(sid):
    head = run("""SELECT s.*, c.name AS customer, e.name AS employee FROM sales s
                  JOIN customer c ON c.customer_id=s.customer_id JOIN employee e ON e.employee_id=s.employee_id
                  WHERE s.sale_id=%s""", (sid,), one=True)
    if not head:
        raise ApiError(404, "Sale not found.")
    head["items"] = run("""SELECT m.name AS medicine, d.quantity, d.unit_price, d.quantity*d.unit_price AS line_total
                           FROM sale_details d JOIN medicine m ON m.medicine_id=d.medicine_id WHERE d.sale_id=%s""", (sid,))
    return jsonify(head)


@app.get("/")
def index():
    return HTML


# ============================================================================
# 5. FRONTEND (plain HTML + JavaScript, no build tools)
# ============================================================================
HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Pharmacy Sales Management</title>
<style>
:root{--ink:#1c2b2a;--mut:#4f6260;--bg:#f3f6f5;--line:#cfdad8;--acc:#0b6b5f;--bad:#a8231c;--warn:#8a4b00}
*{box-sizing:border-box}body{margin:0;font:16px/1.5 system-ui,Segoe UI,sans-serif;color:var(--ink);background:var(--bg)}
header{background:var(--acc);color:#fff;padding:14px 20px}header h1{margin:0;font-size:1.3rem}
nav{display:flex;gap:4px;flex-wrap:wrap;background:#fff;border-bottom:1px solid var(--line);padding:8px 16px}
nav button{background:none;border:0;border-radius:8px;padding:8px 14px;font:inherit;cursor:pointer;color:var(--ink)}
nav button[aria-current=page]{background:var(--acc);color:#fff}
main{max-width:1050px;margin:0 auto;padding:18px}.card{background:#fff;border:1px solid var(--line);border-radius:10px;padding:16px;margin-bottom:16px}
h2{margin:.1em 0 .6em;font-size:1.2rem}button.b{font:inherit;background:var(--acc);color:#fff;border:1px solid var(--acc);border-radius:8px;padding:7px 14px;cursor:pointer}
button.g{font:inherit;background:#fff;color:var(--acc);border:1px solid var(--acc);border-radius:8px;padding:5px 10px;cursor:pointer}
button.d{font:inherit;background:#fff;color:var(--bad);border:1px solid var(--bad);border-radius:8px;padding:5px 10px;cursor:pointer}
:focus-visible{outline:3px solid #f2a900;outline-offset:2px}
label{display:block;font-weight:600;font-size:.88rem;margin-bottom:3px}input,select{width:100%;font:inherit;padding:8px;border:1px solid #7d908d;border-radius:8px;background:#fff}
.grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));align-items:end}.row{display:flex;gap:10px;justify-content:space-between;align-items:center;flex-wrap:wrap}
.tw{overflow-x:auto}table{width:100%;border-collapse:collapse}th,td{padding:8px 6px;border-bottom:1px solid var(--line);text-align:left;font-size:.92rem}
.muted{color:var(--mut)}.empty{padding:24px;text-align:center;color:var(--mut)}
.tag{display:inline-block;padding:1px 8px;border-radius:99px;font-size:.78rem;font-weight:600;border:1px solid var(--warn);color:var(--warn);background:#fdf0dc}
.tag.bad{border-color:var(--bad);color:var(--bad);background:#fdeceb}
#msg{position:sticky;top:0;z-index:5}.m{padding:10px 14px;border-radius:8px;margin-bottom:12px;border:1px solid}
.m.ok{background:#e1f2ef;border-color:var(--acc);color:#073f38}.m.err{background:#fdeceb;border-color:var(--bad);color:#7a1711}
.total{font-size:1.4rem;font-weight:700}@media(max-width:600px){main{padding:10px}}
</style></head><body>
<header><h1>Pharmacy Sales Management System</h1></header><nav id="nav" aria-label="Sections"></nav>
<main><div id="msg" role="status" aria-live="polite"></div><div id="view"></div></main>
<script>
const $=s=>document.querySelector(s);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money=v=>Number(v).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
let META={},SECTIONS=[];
async function api(p,o={}){const r=await fetch('/api'+p,{headers:{'Content-Type':'application/json'},...o});
  if(r.status===204)return null;const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.error||r.statusText);return d}
function say(t,bad){$('#msg').innerHTML=`<div class="m ${bad?'err':'ok'}" ${bad?'role="alert"':''}>${esc(t)}</div>`;if(!bad)setTimeout(()=>$('#msg').innerHTML='',6000)}
const loading=()=>$('#view').innerHTML='<div class="card muted">Loading…</div>';

async function boot(){
  META=await api('/meta');
  SECTIONS=[...Object.keys(META).map(k=>[k,META[k].label]),['sale','New sale'],['history','Sales history']];
  $('#nav').innerHTML=SECTIONS.map(([k,l])=>`<button data-k="${k}">${l}</button>`).join('');
  $('#nav').onclick=e=>{if(e.target.dataset.k)show(e.target.dataset.k)};
  show('sale');
}
function show(k){
  document.querySelectorAll('#nav button').forEach(b=>b.setAttribute('aria-current',b.dataset.k===k?'page':'false'));
  $('#msg').innerHTML='';loading();
  (k==='sale'?saleView:k==='history'?historyView:()=>entityView(k))().catch(e=>$('#view').innerHTML=`<div class="m err">${esc(e.message)}</div>`);
}

async function entityView(k){
  const M=META[k];let editing=null;
  $('#view').innerHTML=`<div class="card"><div class="row"><h2>${M.label}</h2><button class="b" id="add">Add new</button></div>
   <form id="form" hidden></form><div class="row" style="margin:10px 0"><input id="q" type="search" placeholder="Search…" aria-label="Search" style="max-width:320px"></div>
   <div class="tw" id="tbl"></div></div>`;
  const rowsOf=async()=>api(`/${k}?q=${encodeURIComponent($('#q').value)}`);
  async function draw(){
    const rows=await rowsOf();
    if(!rows.length){$('#tbl').innerHTML=`<div class="empty">${$('#q').value?'No records match your search.':'No records yet. Click “Add new” to create one.'}</div>`;return}
    const today=new Date().toISOString().slice(0,10);
    $('#tbl').innerHTML=`<table><thead><tr><th>ID</th>${M.fields.map(f=>`<th>${f.l}</th>`).join('')}<th>Actions</th></tr></thead><tbody>`+
     rows.map(r=>`<tr><td>${r[M.pk]}</td>${M.fields.map(f=>{let v=f.show?r[f.show]:r[f.n];
       if(f.t==='money')v=money(v);let extra='';
       if(k==='medicine'&&f.n==='expiry_date'&&r.expiry_date<today)extra=' <span class="tag bad">Expired</span>';
       if(k==='medicine'&&f.n==='stock'&&r.stock<=10)extra=' <span class="tag">Low</span>';
       return `<td>${esc(v)}${extra}</td>`}).join('')}
       <td style="white-space:nowrap"><button class="g" data-e="${r[M.pk]}">Edit</button> <button class="d" data-d="${r[M.pk]}">Delete</button></td></tr>`).join('')+'</tbody></table>';
    $('#tbl').onclick=async e=>{
      if(e.target.dataset.e){editing=rows.find(r=>r[M.pk]==e.target.dataset.e);await form()}
      if(e.target.dataset.d){const r=rows.find(x=>x[M.pk]==e.target.dataset.d);
        if(!confirm(`Delete this ${k} (ID ${r[M.pk]})? This cannot be undone.`))return;
        try{await api(`/${k}/${r[M.pk]}`,{method:'DELETE'});say('Record deleted.');draw()}catch(x){say(x.message,true)}}};
  }
  async function form(){
    const f=$('#form');f.hidden=false;const opts={};
    for(const x of M.fields)if(x.t==='fk')opts[x.n]=await api('/'+x.ref);
    f.innerHTML=`<h3>${editing?'Edit record':'New record'}</h3><div class="grid">`+M.fields.map(x=>{
      const v=editing?editing[x.n]??'':'',id='f_'+x.n,req=x.req?' required':'';
      const lab=`<label for="${id}">${x.l}${x.req?' *':''}</label>`;
      if(x.t==='fk')return `<div>${lab}<select id="${id}"${req}><option value="">Choose…</option>${opts[x.n].map(o=>`<option value="${o[META[x.ref].pk]}" ${o[META[x.ref].pk]==v?'selected':''}>${esc(o.name)}</option>`).join('')}</select></div>`;
      const type=x.t==='date'?'date':(x.t==='int'||x.t==='money')?'number':'text';
      const step=x.t==='money'?' step="0.01"':'',min=x.min!==undefined?` min="${x.min}"`:'';
      return `<div>${lab}<input id="${id}" type="${type}"${step}${min}${req} value="${esc(v)}"></div>`}).join('')+
      `</div><p><button class="b">${editing?'Save changes':'Save'}</button> <button type="button" class="g" id="cancel">Cancel</button></p>`;
    $('#cancel').onclick=()=>{f.hidden=true;editing=null};
    f.onsubmit=async e=>{e.preventDefault();const body={};M.fields.forEach(x=>body[x.n]=$('#f_'+x.n).value);
      try{await api(editing?`/${k}/${editing[M.pk]}`:`/${k}`,{method:editing?'PUT':'POST',body:JSON.stringify(body)});
        say(editing?'Changes saved.':'Record added.');f.hidden=true;editing=null;draw()}catch(x){say(x.message,true)}};
    f.querySelector('input,select').focus();
  }
  $('#add').onclick=()=>{editing=null;form()};
  let t;$('#q').oninput=()=>{clearTimeout(t);t=setTimeout(()=>draw().catch(x=>say(x.message,true)),250)};
  await draw();
}

async function saleView(){
  const [cust,emp,meds]=await Promise.all([api('/customer'),api('/employee'),api('/medicine')]);
  const today=new Date().toISOString().slice(0,10);
  const sellable=meds.filter(m=>m.expiry_date>=today&&m.stock>0);
  $('#view').innerHTML=`<div class="card"><h2>New sale</h2><form id="sf">
   <div class="grid"><div><label for="c">Customer *</label><select id="c"><option value="">Choose…</option>${cust.map(c=>`<option value="${c.customer_id}">${esc(c.name)}</option>`).join('')}</select></div>
   <div><label for="e">Handled by *</label><select id="e"><option value="">Choose…</option>${emp.map(c=>`<option value="${c.employee_id}">${esc(c.name)} (${esc(c.position)})</option>`).join('')}</select></div></div>
   <h3>Medicines</h3><div id="items"></div>
   <p><button type="button" class="g" id="more">+ Add another medicine</button></p>
   <p class="muted">Estimated total (the server recalculates it from database prices):</p><div class="total" id="tot">0.00</div>
   <p><button class="b" id="go">Save sale</button></p></form></div>`;
  if(!sellable.length){$('#items').innerHTML='<div class="empty">No medicines are in stock and in date. Add stock on the Medicines page.</div>'}
  const rowHtml=()=>`<div class="grid it" style="margin-bottom:8px"><div><label>Medicine</label><select class="m">
    <option value="">Choose…</option>${sellable.map(m=>`<option value="${m.medicine_id}" data-p="${m.price}">${esc(m.name)} — ${money(m.price)} (stock ${m.stock})</option>`).join('')}</select></div>
    <div><label>Quantity</label><input class="q" type="number" min="1" step="1" value="1"></div><div><button type="button" class="d rm">Remove</button></div></div>`;
  const recalc=()=>{let t=0;document.querySelectorAll('.it').forEach(r=>{const o=r.querySelector('.m').selectedOptions[0];
    if(o&&o.dataset.p)t+=Number(o.dataset.p)*(parseInt(r.querySelector('.q').value)||0)});$('#tot').textContent=money(t)};
  const add=()=>{$('#items').insertAdjacentHTML('beforeend',rowHtml());recalc()};
  if(sellable.length)add();
  $('#more').onclick=add;
  $('#items').oninput=recalc;
  $('#items').onclick=e=>{if(e.target.classList.contains('rm')){e.target.closest('.it').remove();recalc()}};
  $('#sf').onsubmit=async e=>{e.preventDefault();
    const items=[...document.querySelectorAll('.it')].map(r=>({medicine_id:r.querySelector('.m').value,quantity:r.querySelector('.q').value}));
    $('#go').disabled=true;
    try{const r=await api('/sales',{method:'POST',body:JSON.stringify({customer_id:$('#c').value,employee_id:$('#e').value,items})});
      say(`Sale #${r.sale_id} saved. Total: ${money(r.total_amount)}. Stock has been updated.`);saleView()}
    catch(x){say(x.message,true);$('#go').disabled=false}};
}

async function historyView(){
  $('#view').innerHTML=`<div class="card"><h2>Sales history</h2><input id="q" type="search" placeholder="Search by sale no., customer, employee or date (YYYY-MM-DD)" aria-label="Search sales" style="max-width:480px">
   <div class="tw" id="tbl" style="margin-top:10px"></div></div><div id="det"></div>`;
  async function draw(){const rows=await api('/sales?q='+encodeURIComponent($('#q').value));
    $('#tbl').innerHTML=!rows.length?'<div class="empty">No sales found.</div>':
     `<table><thead><tr><th>Sale</th><th>Date</th><th>Customer</th><th>Employee</th><th>Items</th><th>Total</th><th></th></tr></thead><tbody>`+
     rows.map(r=>`<tr><td>#${r.sale_id}</td><td>${esc(r.sale_date)}</td><td>${esc(r.customer)}</td><td>${esc(r.employee)}</td><td>${r.items}</td><td>${money(r.total_amount)}</td>
      <td><button class="g" data-v="${r.sale_id}">View</button></td></tr>`).join('')+'</tbody></table>'}
  $('#tbl').onclick=async e=>{if(!e.target.dataset.v)return;try{const s=await api('/sales/'+e.target.dataset.v);
    $('#det').innerHTML=`<div class="card"><h2>Sale #${s.sale_id} details</h2><p class="muted">${esc(s.sale_date)} · Customer: ${esc(s.customer)} · Handled by: ${esc(s.employee)}</p>
     <div class="tw"><table><thead><tr><th>Medicine</th><th>Qty</th><th>Unit price</th><th>Line total</th></tr></thead><tbody>${s.items.map(i=>`<tr><td>${esc(i.medicine)}</td><td>${i.quantity}</td><td>${money(i.unit_price)}</td><td>${money(i.line_total)}</td></tr>`).join('')}</tbody></table></div>
     <p class="total">Total: ${money(s.total_amount)}</p></div>`;$('#det').scrollIntoView()}catch(x){say(x.message,true)}};
  let t;$('#q').oninput=()=>{clearTimeout(t);t=setTimeout(()=>draw().catch(x=>say(x.message,true)),250)};
  await draw();
}
boot().catch(e=>$('#view').innerHTML=`<div class="m err">Could not load the app: ${esc(e.message)}</div>`);
</script></body></html>"""

if __name__ == "__main__":
    if "--print-sql" in sys.argv:
        print(f"CREATE DATABASE IF NOT EXISTS {DB_NAME};\nUSE {DB_NAME};\n")
        print(";\n\n".join(s for s in SCHEMA) + ";")
        sys.exit()
    try:
        init_db(reset="--reset" in sys.argv)
    except mysql.connector.Error as e:
        sys.exit(f"Could not connect to MySQL ({e}).\nCheck that MySQL is running and set DB_USER / DB_PASSWORD.")
    print("Open http://localhost:5000")
    app.run(port=int(os.getenv("PORT", "5000")), debug=False)
