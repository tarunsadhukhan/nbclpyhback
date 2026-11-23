-- winsome: index the mirrored legacy ATTENDANCE (raw punches) for the Attendance Process port
-- (src/hrms/winsomeAttendanceProcess.py). Without it every date/shift scans ~2M rows (~10s).
CREATE INDEX ix_attendance_wdate_shift ON ATTENDANCE (WDate, WShift, emp_code);
