-- One-shot DDL to bring dev DB to v2 billing schema.
-- See docs/BILLING_DESIGN.md §3.2 / §3.3 / §3.3.2.
-- Safe for dev only: TRUNCATE drops the test plan row(s).

SET FOREIGN_KEY_CHECKS = 0;

-- 0. Drop dependent rows on plans (orders / invoices / etc. reference plan_id).
TRUNCATE TABLE manager_billing_payment_events;
TRUNCATE TABLE manager_billing_invoice_transactions;
TRUNCATE TABLE manager_billing_invoice_items;
TRUNCATE TABLE manager_billing_invoices;
TRUNCATE TABLE manager_billing_refunds;
TRUNCATE TABLE manager_billing_order_effects;
TRUNCATE TABLE manager_billing_orders;
TRUNCATE TABLE manager_billing_plans;

-- 1. server_meta gets plan_id link (which plan currently owns this server).
ALTER TABLE manager_server_meta
    ADD COLUMN plan_id BIGINT NULL AFTER expiration_date,
    ADD KEY idx_server_meta_plan (plan_id);

-- 2. plans: drop kind, add period_options, lock resource fields, add CHECKs.
ALTER TABLE manager_billing_plans
    DROP KEY idx_billing_plans_active_kind,
    DROP COLUMN kind,
    ADD COLUMN period_options LONGTEXT
        CHARACTER SET utf8mb4 COLLATE utf8mb4_bin
        NOT NULL CHECK (json_valid(period_options))
        AFTER currency_code,
    MODIFY node_id          INT NOT NULL,
    MODIFY egg_id           INT NOT NULL,
    MODIFY nest_id          INT NOT NULL,
    MODIFY cpu              INT NOT NULL,
    MODIFY memory_mb        INT NOT NULL,
    MODIFY disk_mb          INT NOT NULL,
    MODIFY swap_mb          INT NOT NULL DEFAULT 0,
    MODIFY io               INT NOT NULL DEFAULT 500,
    MODIFY database_limit   INT NOT NULL DEFAULT 0,
    MODIFY backup_limit     INT NOT NULL DEFAULT 0,
    MODIFY allocation_limit INT NOT NULL,
    MODIFY docker_image     VARCHAR(255) NOT NULL,
    MODIFY startup_command  TEXT NOT NULL,
    MODIFY env_defaults     LONGTEXT
        CHARACTER SET utf8mb4 COLLATE utf8mb4_bin
        NOT NULL CHECK (json_valid(env_defaults)),
    ADD CONSTRAINT chk_billing_plans_cpu_pos    CHECK (cpu > 0),
    ADD CONSTRAINT chk_billing_plans_memory_pos CHECK (memory_mb > 0),
    ADD CONSTRAINT chk_billing_plans_disk_pos   CHECK (disk_mb > 0),
    ADD CONSTRAINT chk_billing_plans_alloc_pos  CHECK (allocation_limit > 0),
    ADD KEY idx_billing_plans_active (is_active);

-- 3. orders: add period / pricing snapshot columns + CHECKs.
ALTER TABLE manager_billing_orders
    ADD COLUMN period_count INT NOT NULL DEFAULT 1 AFTER kind,
    ADD COLUMN discount_pct DECIMAL(5,2) NOT NULL DEFAULT 0.00 AFTER period_count,
    ADD COLUMN total_fen    INT NOT NULL AFTER discount_pct,
    ADD COLUMN total_days   INT NOT NULL AFTER total_fen,
    ADD CONSTRAINT chk_billing_orders_period_count_pos CHECK (period_count > 0),
    ADD CONSTRAINT chk_billing_orders_total_fen_pos    CHECK (total_fen > 0),
    ADD CONSTRAINT chk_billing_orders_total_days_pos   CHECK (total_days >= 0);

SET FOREIGN_KEY_CHECKS = 1;
