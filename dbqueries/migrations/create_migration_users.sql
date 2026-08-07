-- Create migration helper DB users
-- Reader: read-only on all DBs
-- Writer: DML + DDL on all DBs (no SUPER/RELOAD/SHUTDOWN)
-- Rollback:
--   DROP USER 'migration-reader'@'%';
--   DROP USER 'migration_writer'@'%';

CREATE USER IF NOT EXISTS 'migration-reader'@'%' IDENTIFIED BY 'migration2026';
GRANT SELECT, SHOW VIEW, PROCESS ON *.* TO 'migration-reader'@'%';

CREATE USER IF NOT EXISTS 'migration_writer'@'%' IDENTIFIED BY 'writer2026';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, DROP, ALTER, INDEX, REFERENCES, CREATE VIEW, SHOW VIEW, CREATE ROUTINE, ALTER ROUTINE, EXECUTE, TRIGGER, LOCK TABLES, CREATE TEMPORARY TABLES, EVENT, PROCESS ON *.* TO 'migration_writer'@'%';

FLUSH PRIVILEGES;
