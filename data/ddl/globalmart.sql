-- GlobalMart DDL

CREATE SCHEMA IF NOT EXISTS {schema_name};

CREATE TABLE IF NOT EXISTS {schema_name}.dim_store (
    store_id VARCHAR(255),
    store_name VARCHAR(255),
    region_id VARCHAR(255),
    city_id VARCHAR(255),
    country_id VARCHAR(255),
    store_format VARCHAR(255),
    sqft INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_product (
    product_id VARCHAR(255),
    product_name VARCHAR(255),
    category_id VARCHAR(255),
    brand_id VARCHAR(255),
    supplier_id VARCHAR(255),
    list_price NUMERIC(18,2),
    cost NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_customer (
    customer_id VARCHAR(255),
    customer_name VARCHAR(255),
    lifecycle_stage_id VARCHAR(255),
    segment_id VARCHAR(255),
    acquisition_channel_id VARCHAR(255),
    country_id VARCHAR(255),
    loyalty_tier_id VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_geography_region (
    region_id VARCHAR(255),
    region_name VARCHAR(255),
    country_id VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_geography_city (
    city_id VARCHAR(255),
    city_name VARCHAR(255),
    region_id VARCHAR(255),
    country_id VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_geography_country (
    country_id VARCHAR(255),
    country_name VARCHAR(255),
    currency_id VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_channel_master (
    channel_id VARCHAR(255),
    channel_type VARCHAR(255),
    channel_name VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_currency (
    currency_id VARCHAR(255),
    currency_code VARCHAR(255),
    currency_name VARCHAR(255),
    exchange_rate_to_usd NUMERIC(18,6)
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_fiscal_period (
    fiscal_period_id VARCHAR(255),
    fiscal_year INTEGER,
    fiscal_month INTEGER,
    fiscal_quarter INTEGER,
    calendar_date DATE
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_company_entity (
    entity_id VARCHAR(255),
    entity_name VARCHAR(255),
    country_id VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_language (
    language_id VARCHAR(255),
    language_code VARCHAR(255),
    language_name VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_time_of_day_bucket (
    time_bucket_id VARCHAR(255),
    bucket_name VARCHAR(255),
    hour_start INTEGER,
    hour_end INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_employee (
    employee_id VARCHAR(255),
    employee_name VARCHAR(255),
    department_id VARCHAR(255),
    job_role_id VARCHAR(255),
    manager_id VARCHAR(255),
    hire_date DATE
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_supplier (
    supplier_id VARCHAR(255),
    supplier_name VARCHAR(255),
    country_id VARCHAR(255),
    payment_terms_days INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_order_header (
    order_id VARCHAR(255),
    order_date DATE,
    customer_id VARCHAR(255),
    store_id VARCHAR(255),
    region_id VARCHAR(255),
    channel_id VARCHAR(255),
    order_count INTEGER,
    revenue NUMERIC(18,2),
    discount_amount NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_order_line (
    order_line_id VARCHAR(255),
    order_id VARCHAR(255),
    product_id VARCHAR(255),
    quantity INTEGER,
    revenue NUMERIC(18,2),
    cost NUMERIC(18,2),
    discount_pct NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_returns (
    return_id VARCHAR(255),
    order_id VARCHAR(255),
    return_date DATE,
    return_reason_id VARCHAR(255),
    return_amount NUMERIC(18,2),
    quantity_returned INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_daily_store_sales (
    day DATE,
    store_id VARCHAR(255),
    region_id VARCHAR(255),
    sales_amount NUMERIC(18,2),
    transaction_count INTEGER,
    avg_transaction_value NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_gift_card_txn (
    txn_id VARCHAR(255),
    store_id VARCHAR(255),
    txn_date DATE,
    amount NUMERIC(18,2),
    txn_count INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_loyalty_redemption_at_pos (
    redemption_id VARCHAR(255),
    store_id VARCHAR(255),
    redemption_date DATE,
    points_redeemed INTEGER,
    discount_amount NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_price_adjustment (
    adjustment_id VARCHAR(255),
    store_id VARCHAR(255),
    product_id VARCHAR(255),
    adjustment_date DATE,
    price_change NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_sales_by_hour (
    hour_id VARCHAR(255),
    store_id VARCHAR(255),
    sales_date DATE,
    revenue NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_transaction_detail (
    txn_id VARCHAR(255),
    store_id VARCHAR(255),
    txn_date DATE,
    amount NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_payment_method (
    method_id VARCHAR(255),
    method_name VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_tender_type (
    tender_id VARCHAR(255),
    tender_name VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_return_reason (
    reason_id VARCHAR(255),
    reason_name VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_cashier (
    cashier_id VARCHAR(255),
    cashier_name VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_promotion (
    promo_id VARCHAR(255),
    promo_name VARCHAR(255),
    is_promoted VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_store_department (
    dept_id VARCHAR(255),
    dept_name VARCHAR(255),
    store_id VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_till_reconciliation (
    recon_id VARCHAR(255),
    store_id VARCHAR(255),
    recon_date DATE,
    variance_amount NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_layaway (
    layaway_id VARCHAR(255),
    customer_id VARCHAR(255),
    store_id VARCHAR(255),
    layaway_date DATE,
    amount NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_compliment_complaint (
    comment_id VARCHAR(255),
    store_id VARCHAR(255),
    comment_date DATE,
    comment_count INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_aged_inventory (
    aged_id VARCHAR(255),
    product_id VARCHAR(255),
    store_id VARCHAR(255),
    age_days INTEGER,
    quantity INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_competitor_pricing (
    price_id VARCHAR(255),
    product_id VARCHAR(255),
    store_id VARCHAR(255),
    price_check_date DATE,
    competitor_price NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_checkout_time (
    checkout_id VARCHAR(255),
    store_id VARCHAR(255),
    checkout_date DATE,
    avg_checkout_sec INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_web_order_header (
    order_id VARCHAR(255),
    order_date DATE,
    customer_id VARCHAR(255),
    revenue NUMERIC(18,2),
    order_count INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_web_order_line (
    order_line_id VARCHAR(255),
    order_id VARCHAR(255),
    product_id VARCHAR(255),
    quantity INTEGER,
    revenue NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_ecom_event_00 (
    event_id VARCHAR(255),
    customer_id VARCHAR(255),
    event_date DATE,
    event_count INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_ecom_event_01 (
    event_id VARCHAR(255),
    customer_id VARCHAR(255),
    event_date DATE,
    event_count INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_ecom_event_02 (
    event_id VARCHAR(255),
    customer_id VARCHAR(255),
    event_date DATE,
    event_count INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_ecom_event_03 (
    event_id VARCHAR(255),
    customer_id VARCHAR(255),
    event_date DATE,
    event_count INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_ecom_event_04 (
    event_id VARCHAR(255),
    customer_id VARCHAR(255),
    event_date DATE,
    event_count INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_ecom_event_05 (
    event_id VARCHAR(255),
    customer_id VARCHAR(255),
    event_date DATE,
    event_count INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_ecom_event_06 (
    event_id VARCHAR(255),
    customer_id VARCHAR(255),
    event_date DATE,
    event_count INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_ecom_event_07 (
    event_id VARCHAR(255),
    customer_id VARCHAR(255),
    event_date DATE,
    event_count INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_ecom_event_08 (
    event_id VARCHAR(255),
    customer_id VARCHAR(255),
    event_date DATE,
    event_count INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_ecom_event_09 (
    event_id VARCHAR(255),
    customer_id VARCHAR(255),
    event_date DATE,
    event_count INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_ecom_event_10 (
    event_id VARCHAR(255),
    customer_id VARCHAR(255),
    event_date DATE,
    event_count INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_ecom_event_11 (
    event_id VARCHAR(255),
    customer_id VARCHAR(255),
    event_date DATE,
    event_count INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_ecom_event_12 (
    event_id VARCHAR(255),
    customer_id VARCHAR(255),
    event_date DATE,
    event_count INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_ecom_event_13 (
    event_id VARCHAR(255),
    customer_id VARCHAR(255),
    event_date DATE,
    event_count INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_ecom_event_14 (
    event_id VARCHAR(255),
    customer_id VARCHAR(255),
    event_date DATE,
    event_count INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_customer_event (
    event_id VARCHAR(255),
    customer_id VARCHAR(255),
    event_date DATE,
    event_type_id VARCHAR(255),
    event_count INTEGER,
    event_value NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_loyalty_points_earned (
    transaction_id VARCHAR(255),
    customer_id VARCHAR(255),
    earn_date DATE,
    points INTEGER,
    order_amount NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_loyalty_points_redeemed (
    redemption_id VARCHAR(255),
    customer_id VARCHAR(255),
    redemption_date DATE,
    points_redeemed INTEGER,
    reward_value NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_nps_response (
    survey_id VARCHAR(255),
    customer_id VARCHAR(255),
    survey_date DATE,
    nps_score INTEGER,
    response_count INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_customer_feedback (
    feedback_id VARCHAR(255),
    customer_id VARCHAR(255),
    feedback_date DATE,
    sentiment_score NUMERIC(18,2),
    feedback_count INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_tier_change (
    change_id VARCHAR(255),
    customer_id VARCHAR(255),
    change_date DATE,
    old_tier_id VARCHAR(255),
    new_tier_id VARCHAR(255),
    change_count INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_customer_segment (
    segment_id VARCHAR(255),
    segment_name VARCHAR(255),
    segment_description VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_lifecycle_stage (
    stage_id VARCHAR(255),
    stage_name VARCHAR(255),
    stage_order INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_acquisition_channel (
    channel_id VARCHAR(255),
    channel_name VARCHAR(255),
    channel_cost NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_household (
    household_id VARCHAR(255),
    household_name VARCHAR(255),
    member_count INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_loyalty_tier (
    tier_id VARCHAR(255),
    tier_name VARCHAR(255),
    tier_level INTEGER,
    min_points INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_reward_type (
    reward_id VARCHAR(255),
    reward_name VARCHAR(255),
    points_cost INTEGER,
    reward_category VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_customer_attr_00 (
    attr_id VARCHAR(255),
    customer_id VARCHAR(255),
    attr_date DATE,
    metric NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_customer_attr_01 (
    attr_id VARCHAR(255),
    customer_id VARCHAR(255),
    attr_date DATE,
    metric NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_customer_attr_02 (
    attr_id VARCHAR(255),
    customer_id VARCHAR(255),
    attr_date DATE,
    metric NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_customer_attr_03 (
    attr_id VARCHAR(255),
    customer_id VARCHAR(255),
    attr_date DATE,
    metric NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_customer_attr_04 (
    attr_id VARCHAR(255),
    customer_id VARCHAR(255),
    attr_date DATE,
    metric NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_customer_attr_05 (
    attr_id VARCHAR(255),
    customer_id VARCHAR(255),
    attr_date DATE,
    metric NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_product_performance_daily (
    day DATE,
    product_id VARCHAR(255),
    units_sold INTEGER,
    revenue NUMERIC(18,2),
    margin NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_markdown_event (
    event_id VARCHAR(255),
    product_id VARCHAR(255),
    event_date DATE,
    markdown_amount NUMERIC(18,2),
    units_sold INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_planogram_compliance (
    compliance_id VARCHAR(255),
    store_id VARCHAR(255),
    product_id VARCHAR(255),
    check_date DATE,
    compliance_score NUMERIC(18,2),
    out_of_stock_days INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_range_review_outcome (
    review_id VARCHAR(255),
    product_id VARCHAR(255),
    review_date DATE,
    outcome_id VARCHAR(255),
    decision_count INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_product_rating (
    rating_id VARCHAR(255),
    product_id VARCHAR(255),
    rating_date DATE,
    avg_rating NUMERIC(18,2),
    review_count INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_category_l1 (
    category_l1_id VARCHAR(255),
    category_l1_name VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_category_l2 (
    category_l2_id VARCHAR(255),
    category_l2_name VARCHAR(255),
    category_l1_id VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_brand (
    brand_id VARCHAR(255),
    brand_name VARCHAR(255),
    brand_owner VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_season (
    season_id VARCHAR(255),
    season_name VARCHAR(255),
    start_date DATE,
    end_date DATE
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_product_lifecycle_stage (
    stage_id VARCHAR(255),
    stage_name VARCHAR(255),
    stage_order INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_private_label (
    label_id VARCHAR(255),
    label_name VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_product_attr_00 (
    attr_id VARCHAR(255),
    product_id VARCHAR(255),
    attr_date DATE,
    metric NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_product_attr_01 (
    attr_id VARCHAR(255),
    product_id VARCHAR(255),
    attr_date DATE,
    metric NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_product_attr_02 (
    attr_id VARCHAR(255),
    product_id VARCHAR(255),
    attr_date DATE,
    metric NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_product_attr_03 (
    attr_id VARCHAR(255),
    product_id VARCHAR(255),
    attr_date DATE,
    metric NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_product_attr_04 (
    attr_id VARCHAR(255),
    product_id VARCHAR(255),
    attr_date DATE,
    metric NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_product_attr_05 (
    attr_id VARCHAR(255),
    product_id VARCHAR(255),
    attr_date DATE,
    metric NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_product_attr_06 (
    attr_id VARCHAR(255),
    product_id VARCHAR(255),
    attr_date DATE,
    metric NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_product_attr_07 (
    attr_id VARCHAR(255),
    product_id VARCHAR(255),
    attr_date DATE,
    metric NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_inventory_snapshot_daily (
    day DATE,
    product_id VARCHAR(255),
    warehouse_id VARCHAR(255),
    on_hand_units INTEGER,
    inventory_value NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_stock_movement (
    movement_id VARCHAR(255),
    product_id VARCHAR(255),
    warehouse_id VARCHAR(255),
    movement_date DATE,
    movement_qty INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_purchase_order_header (
    po_id VARCHAR(255),
    supplier_id VARCHAR(255),
    po_date DATE,
    po_count INTEGER,
    po_amount NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_purchase_order_line (
    po_line_id VARCHAR(255),
    po_id VARCHAR(255),
    product_id VARCHAR(255),
    quantity INTEGER,
    line_amount NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_goods_receipt (
    receipt_id VARCHAR(255),
    po_id VARCHAR(255),
    receipt_date DATE,
    receipt_qty INTEGER,
    variance_qty INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_transfer_order (
    transfer_id VARCHAR(255),
    from_warehouse_id VARCHAR(255),
    to_warehouse_id VARCHAR(255),
    transfer_date DATE,
    transfer_qty INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_write_off (
    writeoff_id VARCHAR(255),
    product_id VARCHAR(255),
    warehouse_id VARCHAR(255),
    writeoff_date DATE,
    writeoff_qty INTEGER,
    writeoff_cost NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_supplier_scorecard (
    scorecard_id VARCHAR(255),
    supplier_id VARCHAR(255),
    scorecard_date DATE,
    quality_score NUMERIC(18,2),
    delivery_score NUMERIC(18,2),
    cost_score NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_warehouse (
    warehouse_id VARCHAR(255),
    warehouse_name VARCHAR(255),
    city_id VARCHAR(255),
    warehouse_type VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_lead_time_bucket (
    bucket_id VARCHAR(255),
    bucket_name VARCHAR(255),
    days_min INTEGER,
    days_max INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_reorder_status (
    status_id VARCHAR(255),
    status_name VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_stock_location (
    location_id VARCHAR(255),
    location_name VARCHAR(255),
    warehouse_id VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_inbound_carrier (
    carrier_id VARCHAR(255),
    carrier_name VARCHAR(255),
    country_id VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_inv_attr_00 (
    attr_id VARCHAR(255),
    product_id VARCHAR(255),
    warehouse_id VARCHAR(255),
    attr_date DATE,
    metric INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_inv_attr_01 (
    attr_id VARCHAR(255),
    product_id VARCHAR(255),
    warehouse_id VARCHAR(255),
    attr_date DATE,
    metric INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_inv_attr_02 (
    attr_id VARCHAR(255),
    product_id VARCHAR(255),
    warehouse_id VARCHAR(255),
    attr_date DATE,
    metric INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_inv_attr_03 (
    attr_id VARCHAR(255),
    product_id VARCHAR(255),
    warehouse_id VARCHAR(255),
    attr_date DATE,
    metric INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_inv_attr_04 (
    attr_id VARCHAR(255),
    product_id VARCHAR(255),
    warehouse_id VARCHAR(255),
    attr_date DATE,
    metric INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_inv_attr_05 (
    attr_id VARCHAR(255),
    product_id VARCHAR(255),
    warehouse_id VARCHAR(255),
    attr_date DATE,
    metric INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_inv_attr_06 (
    attr_id VARCHAR(255),
    product_id VARCHAR(255),
    warehouse_id VARCHAR(255),
    attr_date DATE,
    metric INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_inv_attr_07 (
    attr_id VARCHAR(255),
    product_id VARCHAR(255),
    warehouse_id VARCHAR(255),
    attr_date DATE,
    metric INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_campaign_spend_daily (
    day DATE,
    campaign_id VARCHAR(255),
    spend NUMERIC(18,2),
    spend_count INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_email_send (
    send_id VARCHAR(255),
    campaign_id VARCHAR(255),
    send_date DATE,
    send_count INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_email_open (
    open_id VARCHAR(255),
    send_id VARCHAR(255),
    open_date DATE,
    open_count INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_email_click (
    click_id VARCHAR(255),
    send_id VARCHAR(255),
    click_date DATE,
    click_count INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_social_impression (
    impression_id VARCHAR(255),
    campaign_id VARCHAR(255),
    impression_date DATE,
    impression_count INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_paid_search_click (
    click_id VARCHAR(255),
    campaign_id VARCHAR(255),
    click_date DATE,
    click_count INTEGER,
    click_cost NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_display_impression (
    impression_id VARCHAR(255),
    campaign_id VARCHAR(255),
    impression_date DATE,
    impression_count INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_campaign (
    campaign_id VARCHAR(255),
    campaign_name VARCHAR(255),
    campaign_type VARCHAR(255),
    channel_id VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_creative (
    creative_id VARCHAR(255),
    creative_name VARCHAR(255),
    creative_type VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_audience_segment (
    segment_id VARCHAR(255),
    segment_name VARCHAR(255),
    audience_size INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_utm_source (
    source_id VARCHAR(255),
    source_name VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_ad_network (
    network_id VARCHAR(255),
    network_name VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_mkt_attr_00 (
    attr_id VARCHAR(255),
    campaign_id VARCHAR(255),
    attr_date DATE,
    metric NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_mkt_attr_01 (
    attr_id VARCHAR(255),
    campaign_id VARCHAR(255),
    attr_date DATE,
    metric NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_mkt_attr_02 (
    attr_id VARCHAR(255),
    campaign_id VARCHAR(255),
    attr_date DATE,
    metric NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_mkt_attr_03 (
    attr_id VARCHAR(255),
    campaign_id VARCHAR(255),
    attr_date DATE,
    metric NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_mkt_attr_04 (
    attr_id VARCHAR(255),
    campaign_id VARCHAR(255),
    attr_date DATE,
    metric NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_daily_pnl (
    day DATE,
    entity_id VARCHAR(255),
    revenue NUMERIC(18,2),
    cogs NUMERIC(18,2),
    opex NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_cogs_detail (
    cogs_id VARCHAR(255),
    product_id VARCHAR(255),
    cost_date DATE,
    cost NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_opex_transaction (
    transaction_id VARCHAR(255),
    cost_center_id VARCHAR(255),
    transaction_date DATE,
    amount NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_capex_project (
    project_id VARCHAR(255),
    project_date DATE,
    approved_budget NUMERIC(18,2),
    spent_amount NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_intercompany_recharge (
    recharge_id VARCHAR(255),
    from_entity_id VARCHAR(255),
    to_entity_id VARCHAR(255),
    recharge_date DATE,
    recharge_amount NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_budget_plan (
    budget_id VARCHAR(255),
    cost_center_id VARCHAR(255),
    budget_date DATE,
    budget_amount NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_cost_center (
    cost_center_id VARCHAR(255),
    cost_center_name VARCHAR(255),
    entity_id VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_gl_account (
    account_id VARCHAR(255),
    account_name VARCHAR(255),
    account_type VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_budget_version (
    version_id VARCHAR(255),
    version_name VARCHAR(255),
    fiscal_year INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_cost_category (
    category_id VARCHAR(255),
    category_name VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_project (
    project_id VARCHAR(255),
    project_name VARCHAR(255),
    project_status VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_fin_attr_00 (
    attr_id VARCHAR(255),
    entity_id VARCHAR(255),
    attr_date DATE,
    metric NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_fin_attr_01 (
    attr_id VARCHAR(255),
    entity_id VARCHAR(255),
    attr_date DATE,
    metric NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_fin_attr_02 (
    attr_id VARCHAR(255),
    entity_id VARCHAR(255),
    attr_date DATE,
    metric NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_fin_attr_03 (
    attr_id VARCHAR(255),
    entity_id VARCHAR(255),
    attr_date DATE,
    metric NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_fin_attr_04 (
    attr_id VARCHAR(255),
    entity_id VARCHAR(255),
    attr_date DATE,
    metric NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_fin_attr_05 (
    attr_id VARCHAR(255),
    entity_id VARCHAR(255),
    attr_date DATE,
    metric NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_fin_attr_06 (
    attr_id VARCHAR(255),
    entity_id VARCHAR(255),
    attr_date DATE,
    metric NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_fin_attr_07 (
    attr_id VARCHAR(255),
    entity_id VARCHAR(255),
    attr_date DATE,
    metric NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_store_staffing_daily (
    day DATE,
    store_id VARCHAR(255),
    staff_hours NUMERIC(18,2),
    staff_count INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_shrinkage_event (
    event_id VARCHAR(255),
    store_id VARCHAR(255),
    event_date DATE,
    shrinkage_amount NUMERIC(18,2),
    unit_count INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_maintenance_request (
    request_id VARCHAR(255),
    store_id VARCHAR(255),
    request_date DATE,
    maintenance_cost NUMERIC(18,2),
    downtime_hours NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_footfall_hourly (
    hour_id VARCHAR(255),
    store_id VARCHAR(255),
    footfall_date DATE,
    hour INTEGER,
    visitor_count INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_energy_consumption (
    consumption_id VARCHAR(255),
    store_id VARCHAR(255),
    consumption_date DATE,
    kwh NUMERIC(18,2),
    cost NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_store_visit_census (
    visit_id VARCHAR(255),
    store_id VARCHAR(255),
    visit_date DATE,
    visitor_count INTEGER,
    sqft INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_store_format (
    format_id VARCHAR(255),
    format_name VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_shrinkage_category (
    category_id VARCHAR(255),
    category_name VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_maintenance_type (
    type_id VARCHAR(255),
    type_name VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_shift_type (
    shift_id VARCHAR(255),
    shift_name VARCHAR(255),
    hour_start INTEGER,
    hour_end INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_ops_attr_00 (
    attr_id VARCHAR(255),
    store_id VARCHAR(255),
    attr_date DATE,
    metric NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_ops_attr_01 (
    attr_id VARCHAR(255),
    store_id VARCHAR(255),
    attr_date DATE,
    metric NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_ops_attr_02 (
    attr_id VARCHAR(255),
    store_id VARCHAR(255),
    attr_date DATE,
    metric NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_ops_attr_03 (
    attr_id VARCHAR(255),
    store_id VARCHAR(255),
    attr_date DATE,
    metric NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_ops_attr_04 (
    attr_id VARCHAR(255),
    store_id VARCHAR(255),
    attr_date DATE,
    metric NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_ops_attr_05 (
    attr_id VARCHAR(255),
    store_id VARCHAR(255),
    attr_date DATE,
    metric NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_ops_attr_06 (
    attr_id VARCHAR(255),
    store_id VARCHAR(255),
    attr_date DATE,
    metric NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_employee_hours (
    record_id VARCHAR(255),
    employee_id VARCHAR(255),
    hours_date DATE,
    hours_worked NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_payroll_transaction (
    transaction_id VARCHAR(255),
    employee_id VARCHAR(255),
    department_id VARCHAR(255),
    payroll_date DATE,
    gross_pay NUMERIC(18,2),
    deductions NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_absence (
    absence_id VARCHAR(255),
    employee_id VARCHAR(255),
    absence_date DATE,
    absence_hours NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_training_completion (
    completion_id VARCHAR(255),
    employee_id VARCHAR(255),
    completion_date DATE,
    training_cost NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_headcount_snapshot (
    snapshot_id VARCHAR(255),
    snapshot_date DATE,
    total_headcount INTEGER,
    active_count INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_recruitment (
    position_id VARCHAR(255),
    open_date DATE,
    recruitment_count INTEGER,
    recruitment_cost NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_job_role (
    role_id VARCHAR(255),
    role_name VARCHAR(255),
    salary_band VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_department (
    department_id VARCHAR(255),
    department_name VARCHAR(255),
    manager_id VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_contract_type (
    contract_id VARCHAR(255),
    contract_type_name VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_absence_reason (
    reason_id VARCHAR(255),
    reason_name VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_training_type (
    training_id VARCHAR(255),
    training_name VARCHAR(255),
    training_cost NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_hr_attr_00 (
    attr_id VARCHAR(255),
    employee_id VARCHAR(255),
    attr_date DATE,
    metric NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_hr_attr_01 (
    attr_id VARCHAR(255),
    employee_id VARCHAR(255),
    attr_date DATE,
    metric NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_hr_attr_02 (
    attr_id VARCHAR(255),
    employee_id VARCHAR(255),
    attr_date DATE,
    metric NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_hr_attr_03 (
    attr_id VARCHAR(255),
    employee_id VARCHAR(255),
    attr_date DATE,
    metric NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_hr_attr_04 (
    attr_id VARCHAR(255),
    employee_id VARCHAR(255),
    attr_date DATE,
    metric NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_loyalty_enrollment (
    enrollment_id VARCHAR(255),
    customer_id VARCHAR(255),
    enrollment_date DATE,
    enrollment_count INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_referral (
    referral_id VARCHAR(255),
    customer_id VARCHAR(255),
    referral_date DATE,
    referral_count INTEGER,
    referral_bonus NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_bonus_event (
    event_id VARCHAR(255),
    customer_id VARCHAR(255),
    event_date DATE,
    bonus_points INTEGER,
    bonus_cost NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_partner_redemption (
    redemption_id VARCHAR(255),
    customer_id VARCHAR(255),
    redemption_date DATE,
    points_used INTEGER,
    partner_discount NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_loyalty_expiry (
    expiry_id VARCHAR(255),
    customer_id VARCHAR(255),
    expiry_date DATE,
    points_expired INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_referral_source (
    source_id VARCHAR(255),
    source_name VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_partner (
    partner_id VARCHAR(255),
    partner_name VARCHAR(255),
    partner_category VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_bonus_type (
    bonus_id VARCHAR(255),
    bonus_name VARCHAR(255),
    bonus_multiplier NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_loyalty_campaign (
    campaign_id VARCHAR(255),
    campaign_name VARCHAR(255),
    campaign_start DATE,
    campaign_end DATE
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_loyalty_attr_00 (
    attr_id VARCHAR(255),
    customer_id VARCHAR(255),
    attr_date DATE,
    metric NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_loyalty_attr_01 (
    attr_id VARCHAR(255),
    customer_id VARCHAR(255),
    attr_date DATE,
    metric NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_loyalty_attr_02 (
    attr_id VARCHAR(255),
    customer_id VARCHAR(255),
    attr_date DATE,
    metric NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_lease_payment (
    payment_id VARCHAR(255),
    store_id VARCHAR(255),
    payment_date DATE,
    lease_payment NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_utility_cost (
    cost_id VARCHAR(255),
    store_id VARCHAR(255),
    cost_date DATE,
    utility_cost NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_renovation_spend (
    project_id VARCHAR(255),
    store_id VARCHAR(255),
    spend_date DATE,
    renovation_cost NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_waste_disposal (
    disposal_id VARCHAR(255),
    store_id VARCHAR(255),
    disposal_date DATE,
    disposal_cost NUMERIC(18,2),
    waste_tons NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_property (
    property_id VARCHAR(255),
    property_name VARCHAR(255),
    city_id VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_lease_type (
    lease_id VARCHAR(255),
    lease_type_name VARCHAR(255),
    lease_term_years INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_facilities_category (
    category_id VARCHAR(255),
    category_name VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_utility_type (
    utility_id VARCHAR(255),
    utility_name VARCHAR(255),
    unit_of_measure VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_re_attr_00 (
    attr_id VARCHAR(255),
    store_id VARCHAR(255),
    attr_date DATE,
    metric NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_re_attr_01 (
    attr_id VARCHAR(255),
    store_id VARCHAR(255),
    attr_date DATE,
    metric NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_re_attr_02 (
    attr_id VARCHAR(255),
    store_id VARCHAR(255),
    attr_date DATE,
    metric NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_re_attr_03 (
    attr_id VARCHAR(255),
    store_id VARCHAR(255),
    attr_date DATE,
    metric NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_re_attr_04 (
    attr_id VARCHAR(255),
    store_id VARCHAR(255),
    attr_date DATE,
    metric NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_re_attr_05 (
    attr_id VARCHAR(255),
    store_id VARCHAR(255),
    attr_date DATE,
    metric NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_fraud_alert (
    alert_id VARCHAR(255),
    alert_date DATE,
    alert_count INTEGER,
    alert_value NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_chargeback (
    chargeback_id VARCHAR(255),
    chargeback_date DATE,
    chargeback_count INTEGER,
    chargeback_amount NUMERIC(18,2)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_audit_finding (
    finding_id VARCHAR(255),
    finding_date DATE,
    finding_count INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_risk_category (
    category_id VARCHAR(255),
    category_name VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_audit_type (
    audit_id VARCHAR(255),
    audit_type_name VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_compliance_framework (
    framework_id VARCHAR(255),
    framework_name VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS {schema_name}.dim_fraud_type (
    fraud_id VARCHAR(255),
    fraud_type_name VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_risk_attr_00 (
    attr_id VARCHAR(255),
    attr_date DATE,
    metric INTEGER
);

CREATE TABLE IF NOT EXISTS {schema_name}.fact_risk_attr_01 (
    attr_id VARCHAR(255),
    attr_date DATE,
    metric INTEGER
);

-- fact_search_event: the 215th table.
--
-- `sql_channel_attribution` selects FROM {schema_name}.fact_search_event, but no DDL and no
-- CSV for it has ever existed — open and unclosed in the predecessor repo, and the reason a
-- cold rebuild could not resolve that dataset. Its column set is derived from that
-- statement's references: s.session_id, s.customer_id, s.traffic_source, s.session_date.
--
-- This is the one GlobalMart table whose rows are manufactured rather than inherited. See
-- scripts/take_custody.py and the `synthesised` key in data/table-manifest.json.
CREATE TABLE IF NOT EXISTS {schema_name}.fact_search_event (
    session_id VARCHAR(255),
    customer_id VARCHAR(255),
    traffic_source VARCHAR(255),
    session_date DATE
);
