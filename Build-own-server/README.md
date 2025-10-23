# Cost Manager (FastAPI) — README

A lightweight, asynchronous REST API to track customers, sales, and payments with category validation and an automatic migration path from an older schema. Built with FastAPI, Pydantic, and SQLite (via aiosqlite).

---

## Overview

This service lets you:
- Manage customers (name, phone, location).
- Record itemized sales linked to a customer.
- Track payments against each sale and maintain running totals (paid and remaining).
- Enforce category and sub-category rules from a JSON configuration file.
- Produce monthly summaries and a list of outstanding balances.
- Migrate data automatically from a legacy schema to a normalized schema.

---

## Architecture at a Glance

- API framework: FastAPI (async).
- Data validation: Pydantic models.
- Database: SQLite using asynchronous access.
- Configuration: categories.json.
- Built-in interactive API docs available at the /docs path when the server is running.

---

## Data Model

### Customers
- id: auto-incremented identifier
- name: required
- phone: required and unique
- location: required
- created_at: timestamp automatically added

### Sales
- id: auto-incremented identifier
- customer_id: required, references customers.id
- item: required
- category: required; must exist in categories.json
- sub_category: required; must be listed under the chosen category
- total_price: required (numeric)
- sale_date: required (YYYY-MM-DD)
- paid: numeric, defaults to 0
- remaining: computed as total_price − paid

### Payments
- id: auto-incremented identifier
- sale_id: required, references sales.id
- amount: required (numeric)
- payment_date: required (YYYY-MM-DD)
- note: optional text

Date values are expected in ISO format (YYYY-MM-DD) and are stored as text in SQLite.

---

## Categories Configuration (categories.json)

- A JSON object mapping a category to an array of allowed sub-categories.
- If the file is missing, a default mapping is used with a single category “misc” and a sub-category “other”.
- Sales creation validates both category and sub-category against this configuration.

Example structure (described, not code):
- electronics → laptop, phone, accessory
- furniture → chair, table

---

## Startup Behaviour & Migration

On startup, the application initializes and migrates the database if it detects an older schema:

1. Checks for a legacy “sales” table that lacks the “customer_id” column.
2. If found, renames legacy tables to sales_old and payments_old.
3. Creates the current schema: customers, sales, payments.
4. Inserts a default “Legacy Customer” (phone 0000000000, location Unknown) and assigns migrated sales to customer id 1.
5. Copies all rows from sales_old into sales with default category “misc” and sub-category “other”.
6. Copies all rows from payments_old into payments.
7. Drops sales_old and payments_old upon successful migration.

Limitation note: the migration assumes that the default “Legacy Customer” is id 1. If the customers table already contained data, this assumption may not hold.

---

## API Endpoints (Summary)

| Method | Path                                 | Purpose                                                                                      |
|-------:|--------------------------------------|----------------------------------------------------------------------------------------------|
| GET    | /categories/                         | Returns the category → sub-category mapping currently in use.                                |
| POST   | /customers/                          | Creates a customer (requires name, phone, location). Enforces phone uniqueness.              |
| GET    | /customers/                          | Lists all customers ordered by name.                                                         |
| GET    | /customers/{customer_id}             | Returns a customer record, that customer’s sales, and a summary of totals.                   |
| POST   | /sales/                              | Creates a sale for an existing customer; validates category/sub-category; sets remaining.    |
| GET    | /sales/                              | Lists sales joined with customer information, ordered by sale_date descending.               |
| GET    | /sales/{sale_id}                     | Returns one sale, joined customer information, and all payments for that sale.               |
| POST   | /payments/                           | Adds a payment to a sale; updates sale paid and remaining; rejects overpayments.             |
| GET    | /monthly-summary/{year}/{month}      | Aggregates new sales and received payments for the month; includes global outstanding total. |
| GET    | /outstanding/                        | Lists all sales with remaining > 0 and the grand total outstanding.                          |

Endpoint behaviour highlights:
- Category validation: the category must exist, and the sub-category must be defined under that category.
- Payment rules: you cannot record a payment larger than a sale’s current remaining balance.
- Phone number uniqueness: creation of duplicate phone numbers is rejected for customers.
- Date format: YYYY-MM-DD for all date fields.

---

## Responses & Computations

- Customer summary fields:
  - total_purchased: sum of total_price across the customer’s sales.
  - total_paid: sum of paid across the customer’s sales.
  - total_remaining: sum of remaining across the customer’s sales.

- Monthly summary fields:
  - month: string in YYYY-MM form.
  - payments_received: total of all payment amounts between the 1st and 31st of the specified month.
  - new_sales_total: total of all sale totals in the same date range.
  - outstanding_balance: sum of all remaining values across every sale in the database.
  - payments_count and new_sales_count: counts of rows included in each aggregate.

Note: the monthly calculator uses a day range from 01 through 31 regardless of the actual length of the month.

---

## Operational Guidance

- The service is asynchronous end-to-end.
- Interactive API docs are available at the /docs path once the server is running.
- The application prints startup messages that include the local URL and database file name.
- No authentication or authorization is included. For production use, add authentication, CORS, rate limiting, input size limits, and a backup strategy for the database file.

---

## Validation & Error Responses

- “Phone number already exists” → attempt to create a duplicate customer phone.
- “Invalid category” or “Invalid sub_category” → category configuration mismatch.
- “Payment exceeds remaining balance” → overpayment attempt is blocked.
- “Customer not found” or “Sale not found” → referenced resource does not exist.

HTTP status codes:
- 400 for validation and business-rule errors.
- 404 when a referenced resource is missing.

---

## Maintenance Notes

- Back up the SQLite database file regularly.
- Keep categories.json under version control to track changes in category definitions.
- Consider adding pagination, filters, and sorting to listing endpoints for large datasets.
- Potential enhancements include: authentication, category management endpoints (CRUD), CSV/Excel exports, soft deletes and audit logs, currency/tax, and data seeding utilities.

---

## License

Insert the license you prefer (e.g., MIT, Apache-2.0).
