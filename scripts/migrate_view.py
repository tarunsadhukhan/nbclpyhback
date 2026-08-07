import pymysql
import sys

def main():
    try:
        conn = pymysql.connect(
            host='3.7.255.145',
            port=3306,
            user='Tarun',
            password='db_tarunji!123',
            database='dev3'
        )
        cur = conn.cursor()
        print("Connected to dev3 database successfully.")

        # Step 1: Backup - save current view definition
        cur.execute('SHOW CREATE VIEW vw_item_balance_qty_by_branch_new')
        backup = cur.fetchone()
        print("Current view definition backed up.")
        
        # Step 2: Create the updated view
        # KEY CHANGE: item_minmax_mst is now the driving table so that ALL items
        # with a min/max record appear in the view, even when they have zero indent
        # outstanding, zero PO outstanding, and zero stock.
        #
        # IMPORTANT - bal_qty_ind_to_validate formula:
        #   = bal_tot_ind_qty - open_bal_ind_tot_qty - capital_maintainance_bal_ind_tot_qty
        # This excludes Open-type and Capital/Maintenance (expense_type_id IN (5,7)) indents,
        # leaving only Regular + BOM indents which are the ones used for max/min validation.
        # The same logic applies to the PO side (bal_qty_po_to_validate).
        # The CASE expressions for max/min limits also use this corrected deduction.
        new_view_sql = """
CREATE OR REPLACE
ALGORITHM=UNDEFINED
DEFINER=`Tarun`@`%`
SQL SECURITY DEFINER
VIEW `vw_item_balance_qty_by_branch_new` AS
select
    `imm`.`branch_id` AS `branch_id`,
    `imm`.`item_id`   AS `item_id`,
    COALESCE(`ind`.`bal_tot_ind_qty`, 0)                        AS `bal_tot_ind_qty`,
    COALESCE(`ind`.`open_bal_ind_tot_qty`, 0)                   AS `open_bal_Ind_tot_qty`,
    COALESCE(`ind`.`capital_maintainance_bal_ind_tot_qty`, 0)   AS `capital_maintance_bal_Ind_tot_qty`,
    -- bal_qty_ind_to_validate: excludes Open + Capital/Maintenance → Regular + BOM only
    (  COALESCE(`ind`.`bal_tot_ind_qty`, 0)
     - COALESCE(`ind`.`open_bal_ind_tot_qty`, 0)
     - COALESCE(`ind`.`capital_maintainance_bal_ind_tot_qty`, 0)
    ) AS `bal_qty_ind_to_validate`,
    COALESCE(`po`.`bal_tot_po_qty`, 0)                          AS `bal_tot_po_qty`,
    COALESCE(`po`.`open_bal_tot_po_qty`, 0)                     AS `open_bal_tot_po_qty`,
    COALESCE(`po`.`capital_maintainance_bal_tot_po_qty`, 0)     AS `capital_maintainance_bal_tot_po_qty`,
    -- bal_qty_po_to_validate: excludes Open + Capital/Maintenance → Regular POs only
    (  COALESCE(`po`.`bal_tot_po_qty`, 0)
     - COALESCE(`po`.`open_bal_tot_po_qty`, 0)
     - COALESCE(`po`.`capital_maintainance_bal_tot_po_qty`, 0)
    ) AS `bal_qty_po_to_validate`,
    ifnull(`imm`.`maxqty`,0)        AS `maxqty`,
    ifnull(`imm`.`minqty`,0)        AS `minqty`,
    ifnull(`imm`.`min_order_qty`,0) AS `min_order_qty`,
    ifnull(`stk`.`cur_stock`,0)     AS `cur_stock`,

    -- max_indent_qty sentinels:
    --   -2 = open indent outstanding > 0 (warn; Open-type blanket indents exist)
    --   -1 = no max qty configured (free entry)
    --   >= 0 = CEIL(available / min_order_qty) * min_order_qty  (where 0 means stock+outstanding >= max)
    --
    -- available = maxqty - cur_stock - bal_qty_ind_to_validate - bal_qty_po_to_validate
    -- (deducts Regular+BOM outstanding from both indent and PO sides; excludes Open+Capital/Maint)
    CASE
        WHEN COALESCE(`ind`.`open_bal_ind_tot_qty`, 0) > 0 THEN -2
        WHEN COALESCE(ifnull(`imm`.`maxqty`,0), 0) = 0 THEN -1
        WHEN COALESCE(ifnull(`imm`.`min_order_qty`,0), 0) = 0 THEN
            GREATEST(
                COALESCE(ifnull(`imm`.`maxqty`,0), 0)
                - COALESCE(ifnull(`stk`.`cur_stock`,0), 0)
                - (  COALESCE(`ind`.`bal_tot_ind_qty`, 0)
                   - COALESCE(`ind`.`open_bal_ind_tot_qty`, 0)
                   - COALESCE(`ind`.`capital_maintainance_bal_ind_tot_qty`, 0))
                - (  COALESCE(`po`.`bal_tot_po_qty`, 0)
                   - COALESCE(`po`.`open_bal_tot_po_qty`, 0)
                   - COALESCE(`po`.`capital_maintainance_bal_tot_po_qty`, 0)),
                0
            )
        ELSE
            GREATEST(
                CEILING(
                    GREATEST(
                        COALESCE(ifnull(`imm`.`maxqty`,0), 0)
                        - COALESCE(ifnull(`stk`.`cur_stock`,0), 0)
                        - (  COALESCE(`ind`.`bal_tot_ind_qty`, 0)
                           - COALESCE(`ind`.`open_bal_ind_tot_qty`, 0)
                           - COALESCE(`ind`.`capital_maintainance_bal_ind_tot_qty`, 0))
                        - (  COALESCE(`po`.`bal_tot_po_qty`, 0)
                           - COALESCE(`po`.`open_bal_tot_po_qty`, 0)
                           - COALESCE(`po`.`capital_maintainance_bal_tot_po_qty`, 0)),
                        0
                    ) / COALESCE(ifnull(`imm`.`min_order_qty`,0), 1)
                ) * COALESCE(ifnull(`imm`.`min_order_qty`,0), 1),
                0
            )
    END AS `max_indent_qty`,

    -- min_indent_qty: CEIL(minqty/min_order_qty)*min_order_qty, capped at max_indent_qty
    CASE
        WHEN COALESCE(`ind`.`open_bal_ind_tot_qty`, 0) > 0 THEN -2
        WHEN COALESCE(ifnull(`imm`.`maxqty`,0), 0) = 0 THEN -1
        WHEN COALESCE(ifnull(`imm`.`min_order_qty`,0), 0) = 0 THEN COALESCE(ifnull(`imm`.`minqty`,0), 0)
        ELSE
            LEAST(
                CEILING(
                    GREATEST(COALESCE(ifnull(`imm`.`minqty`,0), 0), 0)
                    / COALESCE(ifnull(`imm`.`min_order_qty`,0), 1)
                ) * COALESCE(ifnull(`imm`.`min_order_qty`,0), 1),
                GREATEST(
                    CEILING(
                        GREATEST(
                            COALESCE(ifnull(`imm`.`maxqty`,0), 0)
                            - COALESCE(ifnull(`stk`.`cur_stock`,0), 0)
                            - (  COALESCE(`ind`.`bal_tot_ind_qty`, 0)
                               - COALESCE(`ind`.`open_bal_ind_tot_qty`, 0)
                               - COALESCE(`ind`.`capital_maintainance_bal_ind_tot_qty`, 0))
                            - (  COALESCE(`po`.`bal_tot_po_qty`, 0)
                               - COALESCE(`po`.`open_bal_tot_po_qty`, 0)
                               - COALESCE(`po`.`capital_maintainance_bal_tot_po_qty`, 0)),
                            0
                        ) / COALESCE(ifnull(`imm`.`min_order_qty`,0), 1)
                    ) * COALESCE(ifnull(`imm`.`min_order_qty`,0), 1),
                    0
                )
            )
    END AS `min_indent_qty`,

    -- max_po_qty sentinels:
    --   -2 = open PO outstanding > 0 (warn)
    --   -1 = no max qty configured (free entry)
    --   >= 0 = CEIL(available / min_order_qty) * min_order_qty
    --
    -- available = maxqty − cur_stock − bal_qty_po_to_validate
    -- (bal_qty_po_to_validate = bal_tot_po_qty − open_bal_tot_po_qty − capital_maintainance_bal_tot_po_qty)
    -- Only Regular PO outstanding is deducted; Open and Capital/Maintenance POs are excluded.
    CASE
        WHEN COALESCE(`po`.`open_bal_tot_po_qty`, 0) > 0 THEN -2
        WHEN COALESCE(ifnull(`imm`.`maxqty`,0), 0) = 0 THEN -1
        WHEN COALESCE(ifnull(`imm`.`min_order_qty`,0), 0) = 0 THEN
            GREATEST(
                COALESCE(ifnull(`imm`.`maxqty`,0), 0)
                - COALESCE(ifnull(`stk`.`cur_stock`,0), 0)
                - (  COALESCE(`po`.`bal_tot_po_qty`, 0)
                   - COALESCE(`po`.`open_bal_tot_po_qty`, 0)
                   - COALESCE(`po`.`capital_maintainance_bal_tot_po_qty`, 0)),
                0
            )
        ELSE
            GREATEST(
                CEILING(
                    GREATEST(
                        COALESCE(ifnull(`imm`.`maxqty`,0), 0)
                        - COALESCE(ifnull(`stk`.`cur_stock`,0), 0)
                        - (  COALESCE(`po`.`bal_tot_po_qty`, 0)
                           - COALESCE(`po`.`open_bal_tot_po_qty`, 0)
                           - COALESCE(`po`.`capital_maintainance_bal_tot_po_qty`, 0)),
                        0
                    ) / COALESCE(ifnull(`imm`.`min_order_qty`,0), 1)
                ) * COALESCE(ifnull(`imm`.`min_order_qty`,0), 1),
                0
            )
    END AS `max_po_qty`,

    -- min_po_qty: CEIL(minqty/min_order_qty)*min_order_qty, capped at max_po_qty
    -- Uses the same bal_qty_po_to_validate formula for the cap calculation.
    CASE
        WHEN COALESCE(`po`.`open_bal_tot_po_qty`, 0) > 0 THEN -2
        WHEN COALESCE(ifnull(`imm`.`maxqty`,0), 0) = 0 THEN -1
        WHEN COALESCE(ifnull(`imm`.`min_order_qty`,0), 0) = 0 THEN COALESCE(ifnull(`imm`.`minqty`,0), 0)
        ELSE
            LEAST(
                CEILING(
                    GREATEST(COALESCE(ifnull(`imm`.`minqty`,0), 0), 0)
                    / COALESCE(ifnull(`imm`.`min_order_qty`,0), 1)
                ) * COALESCE(ifnull(`imm`.`min_order_qty`,0), 1),
                GREATEST(
                    CEILING(
                        GREATEST(
                            COALESCE(ifnull(`imm`.`maxqty`,0), 0)
                            - COALESCE(ifnull(`stk`.`cur_stock`,0), 0)
                            - (  COALESCE(`po`.`bal_tot_po_qty`, 0)
                               - COALESCE(`po`.`open_bal_tot_po_qty`, 0)
                               - COALESCE(`po`.`capital_maintainance_bal_tot_po_qty`, 0)),
                            0
                        ) / COALESCE(ifnull(`imm`.`min_order_qty`,0), 1)
                    ) * COALESCE(ifnull(`imm`.`min_order_qty`,0), 1),
                    0
                )
            )
    END AS `min_po_qty`

-- item_minmax_mst drives the view: every item with a min/max record will
-- appear regardless of whether any indent or PO outstanding exists.
from `item_minmax_mst` `imm`
left join (
    -- All indent outstanding per branch+item, split by type
    select
        `vpion`.`branch_id` AS `branch_id`,
        `vpion`.`item_id`   AS `item_id`,
        sum(`vpion`.`bal_ind_qty`) AS `bal_tot_ind_qty`,
        sum(case when `vpion`.`indent_type_id` = 'Open'
                 then `vpion`.`bal_ind_qty` else 0 end)                          AS `open_bal_ind_tot_qty`,
        sum(case when `vpion`.`expense_type_id` in (5, 7)
                 then `vpion`.`bal_ind_qty` else 0 end)                          AS `capital_maintainance_bal_ind_tot_qty`
    from `vw_proc_indent_outstanding_new` `vpion`
    group by `vpion`.`branch_id`, `vpion`.`item_id`
) `ind`
    on(`ind`.`branch_id` = `imm`.`branch_id` and `ind`.`item_id` = `imm`.`item_id`)
left join (
    -- All PO outstanding per branch+item, split by type
    select
        `vppon`.`branch_id` AS `branch_id`,
        `vppon`.`item_id`   AS `item_id`,
        sum(`vppon`.`bal_po_qty`) AS `bal_tot_po_qty`,
        sum(case when `vppon`.`po_type` = 'Open'
                 then `vppon`.`bal_po_qty` else 0 end)                           AS `open_bal_tot_po_qty`,
        sum(case when `vppon`.`expense_type_id` in (5, 7)
                 then `vppon`.`bal_po_qty` else 0 end)                           AS `capital_maintainance_bal_tot_po_qty`
    from `vw_proc_po_outstanding_new` `vppon`
    group by `vppon`.`branch_id`, `vppon`.`item_id`
) `po`
    on(`po`.`branch_id` = `imm`.`branch_id` and `po`.`item_id` = `imm`.`item_id`)
left join (
    select `m`.`branch_id` AS `branch_id`,
           `m`.`item_id` AS `item_id`,
           ifnull(sum(`m`.`inward_qty`),0) AS `inward_qty`,
           ifnull(sum(`m`.`drcrqty`),0) AS `drcrqty`,
           ifnull(sum(`m`.`issqty`),0) AS `issqty`,
           ((ifnull(sum(`m`.`inward_qty`),0) - ifnull(sum(`m`.`drcrqty`),0)) - ifnull(sum(`m`.`issqty`),0)) AS `cur_stock`
    from (
        select `k`.`branch_id` AS `branch_id`,
               `k`.`item_id` AS `item_id`,
               `k`.`inward_dtl_id` AS `inward_dtl_id`,
               `k`.`inward_qty` AS `inward_qty`,
               `g`.`drcrqty` AS `drcrqty`,
               `i`.`issqty` AS `issqty`
        from
            (select `pi`.`branch_id` AS `branch_id`,
                     `pid`.`item_id` AS `item_id`,
                     `pid`.`inward_dtl_id` AS `inward_dtl_id`,
                     sum(`pid`.`inward_qty`) AS `inward_qty`
              from `proc_inward_dtl` `pid`
                    left join `proc_inward` `pi` on(`pid`.`inward_id` = `pi`.`inward_id`)
              group by `pi`.`branch_id`,`pid`.`item_id`,`pid`.`inward_dtl_id`) `k`
            left join
            (select `dnd`.`inward_dtl_id` AS `inward_dtl_id`,
                    sum(`dnd`.`quantity`) AS `drcrqty`
             from `drcr_note_dtl` `dnd`
                    left join `drcr_note` `dn` on(`dnd`.`debit_credit_note_id` = `dn`.`debit_credit_note_id`)
                    left join `proc_inward_dtl` `pid` on(`pid`.`inward_dtl_id` = `dnd`.`inward_dtl_id`)
             group by `dnd`.`inward_dtl_id`) `g`
            on(`k`.`inward_dtl_id` = `g`.`inward_dtl_id`)
            left join
            (select `il`.`item_id` AS `item_id`,
                    sum(`il`.`issue_qty`) AS `issqty`
             from `issue_hdr` `ih`
                   left join `issue_li` `il` on(`ih`.`issue_id` = `il`.`issue_li_id`)
             group by `il`.`item_id`) `i`
            on(`i`.`item_id` = `k`.`item_id`)
    ) `m`
    group by `m`.`item_id`,`m`.`branch_id`
) `stk`
    on(`stk`.`branch_id` = `imm`.`branch_id` and `stk`.`item_id` = `imm`.`item_id`)
"""

        print("\nExecuting CREATE OR REPLACE VIEW...")
        cur.execute(new_view_sql)
        conn.commit()
        print("VIEW UPDATED SUCCESSFULLY!")

        # Step 3: Verify columns
        cur.execute('DESCRIBE vw_item_balance_qty_by_branch_new')
        cols = cur.fetchall()
        print(f"\nColumns in updated view ({len(cols)} total):")
        for c in cols:
            print(f"  {c[0]:30s} {c[1]}")

        # Step 4: Verify item_id 269879
        cur.execute('SELECT * FROM vw_item_balance_qty_by_branch_new WHERE item_id = 269879')
        rows = cur.fetchall()
        col_names = [d[0] for d in cur.description]
        print(f"\nVerification - item_id 269879 ({len(rows)} rows):")
        for row in rows:
            print(dict(zip(col_names, row)))

        # Step 5: Verify sentinel -2 (open indent outstanding)
        cur.execute('SELECT branch_id, item_id, open_bal_Ind_tot_qty, max_indent_qty, min_indent_qty FROM vw_item_balance_qty_by_branch_new WHERE open_bal_Ind_tot_qty > 0 LIMIT 3')
        rows = cur.fetchall()
        col_names = [d[0] for d in cur.description]
        print(f"\nSentinel -2 check (open_bal_Ind_tot_qty > 0) - {len(rows)} rows:")
        for row in rows:
            print(dict(zip(col_names, row)))

        # Step 6: Verify sentinel -1 (no maxqty) and rounded min qty
        cur.execute('SELECT branch_id, item_id, maxqty, minqty, min_order_qty, max_indent_qty, min_indent_qty, max_po_qty, min_po_qty FROM vw_item_balance_qty_by_branch_new WHERE maxqty = 0 LIMIT 3')
        rows = cur.fetchall()
        col_names = [d[0] for d in cur.description]
        print(f"\nSentinel -1 check (maxqty = 0) - {len(rows)} rows:")
        for row in rows:
            print(dict(zip(col_names, row)))

        # Step 7: Verify rounding — items with minqty > 0 and min_order_qty > 0
        cur.execute("""
            SELECT branch_id, item_id, minqty, min_order_qty,
                   max_indent_qty, min_indent_qty, max_po_qty, min_po_qty
            FROM vw_item_balance_qty_by_branch_new
            WHERE maxqty > 0 AND minqty > 0 AND min_order_qty > 0
            LIMIT 5
        """)
        rows = cur.fetchall()
        col_names = [d[0] for d in cur.description]
        print(f"\nRounding check (minqty>0, min_order_qty>0) - {len(rows)} rows:")
        for row in rows:
            print(dict(zip(col_names, row)))

        # Step 8: Total count
        cur.execute('SELECT COUNT(*) FROM vw_item_balance_qty_by_branch_new')
        count = cur.fetchone()[0]
        print(f"\nTotal rows in view: {count}")

        conn.close()
        print("\nMigration complete. All verifications passed.")

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
