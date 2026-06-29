-- Migration 015: add gender, national_id, phone_number, employment_status to employees
ALTER TABLE employees
    ADD COLUMN IF NOT EXISTS gender TEXT,
    ADD COLUMN IF NOT EXISTS national_id TEXT,
    ADD COLUMN IF NOT EXISTS phone_number TEXT,
    ADD COLUMN IF NOT EXISTS employment_status TEXT NOT NULL DEFAULT 'active';
