-- 설명용 샘플 스키마. 운영 원본이나 운영 대상에 실행하지 않는다.
-- 아래 숫자(행 2건, 이후 증분 1건)는 절차서 전체에서 같은 예로 사용한다.

CREATE DATABASE IF NOT EXISTS appdb
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE appdb;

CREATE TABLE orders (
  id BIGINT NOT NULL AUTO_INCREMENT,
  customer_id BIGINT NOT NULL,
  status VARCHAR(20) NOT NULL,
  updated_at DATETIME(6) NOT NULL,
  PRIMARY KEY (id),
  KEY idx_orders_updated (updated_at, id)
) ENGINE=InnoDB;

INSERT INTO orders (id, customer_id, status, updated_at) VALUES
  (1, 100, 'paid', '2026-11-13 09:00:00.000000'),
  (2, 101, 'new',  '2026-11-13 09:05:00.000000');

DELIMITER $$
CREATE PROCEDURE appdb.order_count()
BEGIN
  SELECT COUNT(*) AS order_count FROM orders;
END$$
DELIMITER ;
