"""Raw SQL builders for Jute Production reports."""

from sqlalchemy import text


def get_maturity_time_report_query():
    """Per-issue × per-production-entry maturity vs target maturity, for a given issue date."""
    return text(
        """
        SELECT
            r.spreader_roll_issue_id,
            r.entry_id_grp,
            r.issue_date,
            r.issue_time,
            r.spell AS issue_spell,
            r.no_of_rolls AS issue_rolls,
            r.wt_per_roll,
            r.issue_dt,
            p.bin_id,
            b.bin_code,
            p.item_id,
            i.item_name,
            p.entry_date AS prod_entry_date,
            p.entry_time AS prod_entry_time,
            p.entry_dt AS prod_entry_dt,
            p.no_of_rolls AS prod_rolls,
            TIMESTAMPDIFF(HOUR, p.entry_dt, r.issue_dt) AS maturity_hrs,
            COALESCE(mm.maturity_hours, 48) AS target_maturity_hrs
        FROM spreader_roll_issue r
        LEFT JOIN spreader_prod_entry p
               ON p.entry_id_grp = r.entry_id_grp
              AND p.wt_per_roll = r.wt_per_roll
              AND p.co_id = r.co_id
              AND p.active = 1
        LEFT JOIN spreader_bin_mst b ON b.bin_id = p.bin_id
        LEFT JOIN item_mst i ON i.item_id = p.item_id
        LEFT JOIN item_maturity_mst mm
               ON mm.item_id = p.item_id AND mm.co_id = r.co_id AND mm.active = 1
        WHERE r.co_id = :co_id
          AND r.active = 1
          AND r.issue_date = :d
        ORDER BY r.issue_time, r.entry_id_grp, p.entry_dt
        """
    )


def get_spreader_production_report_query():
    """Production rows for a date window covering report_date + early hours of next day (C overflow)."""
    return text(
        """
        SELECT
            p.spreader_prod_entry_id,
            p.entry_date,
            p.entry_time,
            p.entry_dt,
            p.spell,
            p.machine_id,
            m.machine_name,
            m.mech_code,
            p.item_id,
            i.item_name,
            p.no_of_rolls,
            p.wt_per_roll,
            (p.no_of_rolls * p.wt_per_roll) AS weight_kg
        FROM spreader_prod_entry p
        LEFT JOIN machine_mst m ON m.machine_id = p.machine_id
        LEFT JOIN item_mst i ON i.item_id = p.item_id
        WHERE p.co_id = :co_id
          AND p.active = 1
          AND (p.entry_date = :d OR (p.entry_date = DATE_ADD(:d, INTERVAL 1 DAY) AND p.entry_time < 6))
        ORDER BY p.entry_date, p.entry_time
        """
    )
