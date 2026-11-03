-- MySQL 8.4. The runner creates the separate hw6 database first.
-- Source hw5 tables remain unchanged. Only the complete formal HW5 run is migrated.
CREATE TABLE IF NOT EXISTS hw6.countries (
    country VARCHAR(128) NOT NULL PRIMARY KEY,
    is_banned BOOLEAN NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS hw6.clients (
    client_ip VARCHAR(45) NOT NULL PRIMARY KEY,
    country VARCHAR(128) NOT NULL,
    FOREIGN KEY (country) REFERENCES hw6.countries(country)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS hw6.requests (
    request_id VARCHAR(36) NOT NULL PRIMARY KEY,
    request_time DATETIME(6) NOT NULL UNIQUE,
    run_id VARCHAR(64),
    method VARCHAR(32) NOT NULL,
    requested_file VARCHAR(1024) NOT NULL,
    client_ip VARCHAR(45) NOT NULL,
    peer_ip VARCHAR(45),
    gender VARCHAR(32),
    age VARCHAR(32),
    income VARCHAR(32),
    client_time VARCHAR(64),
    http_status INTEGER NOT NULL,
    FOREIGN KEY (client_ip) REFERENCES hw6.clients(client_ip),
    INDEX (run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS hw6.request_timings (
    request_id VARCHAR(36) NOT NULL PRIMARY KEY,
    extract_ns BIGINT NOT NULL,
    storage_ns BIGINT NOT NULL,
    response_ns BIGINT NOT NULL,
    database_ns BIGINT NOT NULL,
    total_ns BIGINT NOT NULL,
    storage_attempted BOOLEAN NOT NULL,
    response_sent BOOLEAN NOT NULL,
    FOREIGN KEY (request_id) REFERENCES hw6.requests(request_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- Views expose derived/repeated values without storing them redundantly.
CREATE OR REPLACE VIEW hw6.request_details AS
SELECT r.request_id, r.request_time, r.run_id, r.method, r.requested_file,
       c.country, r.client_ip, r.peer_ip, r.gender, r.age, r.income,
       co.is_banned, r.client_time,
       TIME_FORMAT(STR_TO_DATE(r.client_time, '%Y-%m-%d %H:%i:%s'), '%H:%i:%s') AS time_of_day,
       r.http_status
FROM hw6.requests r JOIN hw6.clients c USING (client_ip)
JOIN hw6.countries co USING (country);

CREATE OR REPLACE VIEW hw6.failed_requests AS
SELECT request_time, requested_file, http_status AS error_code
FROM hw6.requests WHERE http_status <> 200;
