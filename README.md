# Pharmacy Sales Management System
Flask + MySQL project.

## Setup
1. Install Python and MySQL Server, and keep MySQL running.
2. pip install -r requirements.txt
3. Set your MySQL password (PowerShell):
   $env:DB_USER="root"; $env:DB_PASSWORD="your_password"
4. python pharmacy_app.py
5. Open http://localhost:5000

The database and sample data are created automatically on first run.
Use `python pharmacy_app.py --reset` to rebuild the sample data.
