-- Select the exact completed experiment ID printed by run_experiment.py.
-- These queries deliberately exclude curl demonstrations, smoke tests and scans.
USE hw5;
SET @run_id = 'REPLACE_WITH_COMPLETED_RUN_ID';

-- 1. Successful versus unsuccessful HTTP responses.
SELECT SUM(http_status = 200) AS successful,
       SUM(http_status <> 200) AS unsuccessful, COUNT(*) AS total
FROM requests WHERE run_id = @run_id;

-- 2. Requests originating from the assignment's banned countries.
SELECT SUM(is_banned) AS banned_requests FROM requests WHERE run_id = @run_id;

-- 3. Male versus Female (also expose missing/unexpected labels).
SELECT gender, COUNT(*) AS requests FROM requests WHERE run_id = @run_id
GROUP BY gender ORDER BY requests DESC, gender;

-- 4. Top five countries. Alphabetical ordering resolves a cutoff tie explicitly.
SELECT country, COUNT(*) AS requests FROM requests WHERE run_id = @run_id
GROUP BY country ORDER BY requests DESC, country LIMIT 5;

-- 5 and 6. Original age/income labels; do not convert ranges to numbers.
SELECT age, COUNT(*) AS requests FROM requests WHERE run_id = @run_id
GROUP BY age ORDER BY requests DESC, age;
SELECT income, COUNT(*) AS requests FROM requests WHERE run_id = @run_id
GROUP BY income ORDER BY requests DESC, income;

-- Four timing stages, plus total. All stored values are integer nanoseconds.
SELECT COUNT(*) AS samples,
       AVG(t.extract_ns) / 1000000 AS extract_ms,
       AVG(t.storage_ns) / 1000000 AS storage_ms_all_requests,
       AVG(CASE WHEN t.storage_attempted THEN t.storage_ns END) / 1000000 AS storage_ms_attempted,
       AVG(t.response_ns) / 1000000 AS send_ms,
       AVG(t.database_ns) / 1000000 AS database_ms,
       AVG(t.total_ns) / 1000000 AS total_ms,
       SUM(NOT t.response_sent) AS send_failures
FROM request_timings AS t JOIN requests AS r USING (request_id)
WHERE r.run_id = @run_id;

-- The failure table contains exactly the required three fields.
SELECT e.* FROM failed_requests AS e JOIN requests AS r USING (request_time)
WHERE r.run_id = @run_id ORDER BY request_time;

SHOW CREATE TABLE requests;
SHOW CREATE TABLE failed_requests;
SHOW CREATE TABLE request_timings;
