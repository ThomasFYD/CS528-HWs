-- Run only after audit_source() passes. :run_id is a bound SQLAlchemy parameter.
-- The Python runner wraps these four INSERTs in one transaction, then verifies
-- every original request, error and timing field before committing.
INSERT INTO hw6.countries (country, is_banned)
SELECT r.country, MIN(r.is_banned) FROM hw5.requests r
LEFT JOIN hw6.countries d ON d.country = r.country
WHERE r.run_id = :run_id AND d.country IS NULL
GROUP BY r.country;

INSERT INTO hw6.clients (client_ip, country)
SELECT r.client_ip, MIN(r.country) FROM hw5.requests r
LEFT JOIN hw6.clients d ON d.client_ip = r.client_ip
WHERE r.run_id = :run_id AND d.client_ip IS NULL
GROUP BY r.client_ip;

INSERT INTO hw6.requests
(request_id, request_time, run_id, method, requested_file, client_ip,
 peer_ip, gender, age, income, client_time, http_status)
SELECT r.request_id, r.request_time, r.run_id, r.method, r.requested_file,
       r.client_ip, r.peer_ip, r.gender, r.age, r.income, r.client_time, r.http_status
FROM hw5.requests r LEFT JOIN hw6.requests d ON d.request_id = r.request_id
WHERE r.run_id = :run_id AND d.request_id IS NULL;

INSERT INTO hw6.request_timings
(request_id, extract_ns, storage_ns, response_ns, database_ns, total_ns,
 storage_attempted, response_sent)
SELECT t.request_id, t.extract_ns, t.storage_ns, t.response_ns, t.database_ns,
       t.total_ns, t.storage_attempted, t.response_sent
FROM hw5.request_timings t JOIN hw5.requests r USING (request_id)
LEFT JOIN hw6.request_timings d ON d.request_id = t.request_id
WHERE r.run_id = :run_id AND d.request_id IS NULL;
