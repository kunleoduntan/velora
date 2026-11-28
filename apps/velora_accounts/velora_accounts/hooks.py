app_title = "Accounts"
app_description = "Velora financial engine: immutable ledger, Receipts, Payments, General Journal, batches"
required_apps = []
required_velora = ">=0.8,<0.9"
after_install = "velora_accounts.seed.after_install"
before_uninstall = None
doc_events = {}


# PostgreSQL-only: the DATABASE enforces the ledger's rules, so not even a raw UPDATE, a script or a bug can break them. (Elsewhere the Python code still enforces them.)
pg_objects = [
    {"name": "gl_entry_amounts",
     "description": "A ledger line is a positive debit OR a positive credit, never both, never negative.",
     "sql": ["""DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_gl_entry_amounts' AND conrelid = 'tab_gl_entry'::regclass) THEN
                  ALTER TABLE tab_gl_entry ADD CONSTRAINT ck_gl_entry_amounts CHECK (debit >= 0 AND credit >= 0 AND (debit = 0 OR credit = 0)) NOT VALID;
                END IF; END $$"""]},
    {"name": "gl_entry_append_only",
     "description": "A ledger entry's amounts can never be edited and entries can never be deleted. The ONE permitted change is flagging an entry cancelled (0 -> 1), which is how a cancelled voucher leaves the reports. A mistake is corrected by cancelling and amending the document.",
     "sql": ["""CREATE OR REPLACE FUNCTION velora_gl_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                  IF TG_OP = 'UPDATE' AND COALESCE(OLD.is_cancelled, 0) = 0 AND NEW.is_cancelled = 1
                     AND (to_jsonb(OLD) - 'is_cancelled') = (to_jsonb(NEW) - 'is_cancelled') THEN
                    RETURN NEW;                                   -- cancelling: nothing else about the entry may differ
                  END IF;
                  RAISE EXCEPTION 'The general ledger cannot be edited or deleted (%). Cancel the document and amend it instead.', TG_OP USING ERRCODE = 'restrict_violation';
                END $$""",
             "DROP TRIGGER IF EXISTS trg_gl_entry_immutable ON tab_gl_entry",
             "CREATE TRIGGER trg_gl_entry_immutable BEFORE UPDATE OR DELETE ON tab_gl_entry FOR EACH ROW EXECUTE FUNCTION velora_gl_immutable()",
             "DROP TRIGGER IF EXISTS trg_gl_entry_no_truncate ON tab_gl_entry",
             "CREATE TRIGGER trg_gl_entry_no_truncate BEFORE TRUNCATE ON tab_gl_entry FOR EACH STATEMENT EXECUTE FUNCTION velora_gl_immutable()"]},
    {"name": "gl_entry_balanced",
     "description": "Every voucher's debits equal its credits, checked by the database when the transaction commits.",
     "sql": ["CREATE INDEX IF NOT EXISTS ix_gl_entry_voucher ON tab_gl_entry (voucher_type, voucher_no)",
             """CREATE OR REPLACE FUNCTION velora_gl_check_balanced() RETURNS trigger LANGUAGE plpgsql AS $$
                DECLARE diff numeric;
                BEGIN
                  SELECT COALESCE(SUM(debit), 0) - COALESCE(SUM(credit), 0) INTO diff FROM tab_gl_entry WHERE voucher_type = NEW.voucher_type AND voucher_no = NEW.voucher_no;
                  IF diff <> 0 THEN
                    RAISE EXCEPTION 'Voucher % % is out of balance by %: debits must equal credits', NEW.voucher_type, NEW.voucher_no, diff USING ERRCODE = 'check_violation';
                  END IF;
                  RETURN NULL;
                END $$""",
             "DROP TRIGGER IF EXISTS trg_gl_entry_balanced ON tab_gl_entry",
             """CREATE CONSTRAINT TRIGGER trg_gl_entry_balanced AFTER INSERT ON tab_gl_entry DEFERRABLE INITIALLY DEFERRED
                FOR EACH ROW EXECUTE FUNCTION velora_gl_check_balanced()"""]},
    {"name": "fiscal_year_no_overlap",
     "description": "Two fiscal years can never overlap - even if two people create them at the same instant.",
     "requires": ["btree_gist"],
     "sql": ["""DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ex_fiscal_year_no_overlap' AND conrelid = 'tab_fiscal_year'::regclass) THEN
                  ALTER TABLE tab_fiscal_year ADD CONSTRAINT ex_fiscal_year_no_overlap EXCLUDE USING gist (daterange(start_date, end_date, '[]') WITH &&);
                END IF;
              EXCEPTION WHEN exclusion_violation THEN
                RAISE WARNING 'Existing fiscal years overlap, so the overlap constraint was not added: fix them, then re-run migrate with a changed object';
              END $$"""]},
    {"name": "gl_entry_indexes",
     "description": "BRIN for the append-only date column (tiny, fast for ranges); a covering index so balances are answered from the index alone.",
     "sql": ["CREATE INDEX IF NOT EXISTS brin_gl_entry_posting_date ON tab_gl_entry USING brin (posting_date)",
             "DROP INDEX IF EXISTS ix_gl_entry_account_date_cover",
             "CREATE INDEX IF NOT EXISTS ix_gl_entry_live_cover ON tab_gl_entry (account, posting_date) INCLUDE (debit, credit, is_cancelled)"]},
    {"name": "open_invoice_indexes",
     "description": "Partial indexes over only the invoices still owing money: aged-balance reports skip every settled invoice.",
     "sql": ["CREATE INDEX IF NOT EXISTS ix_sales_invoice_open ON tab_sales_invoice (customer, due_date) WHERE docstatus = 1 AND outstanding > 0",
             "CREATE INDEX IF NOT EXISTS ix_purchase_invoice_open ON tab_purchase_invoice (supplier, due_date) WHERE docstatus = 1 AND outstanding > 0"]},
]
